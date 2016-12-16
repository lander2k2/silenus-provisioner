import os
import time

import boto3
import celery
from celery import Celery
from sqlalchemy.orm.attributes import flag_modified

from provisioner import db
from provisioner.models import Jurisdiction


mq = Celery('tasks', broker='amqp://{0}@{1}//'.format(
                            os.environ.get('SILENUS_PROVISIONER_MQ_USER'),
                            os.environ.get('SILENUS_PROVISIONER_MQ_HOST')))
mq.conf.update(CELERY_TASK_SERIALIZER = 'json')
mq.conf.update(CELERY_RESULT_SERIALIZER = 'json')


@mq.task
def monitor_cloudformation_stack(jurisdiction_id, interim_operation=False,
                                 stack_key=None):
    """
    Checks on status of clouformation staxck every 30 seconds and updates status.
    When cloudformation creation or update is complete, it also updates
    active attribute to True. If interim_operation argument is set to True
    the jurisdiction will *not* be marked active.
    """
    with db.transaction() as session:
        j = session.query(Jurisdiction).filter_by(id=jurisdiction_id).one()

        j_assets = j.assets
        if stack_key:
            j_stack_id = j.assets['cloudformation_stack'][stack_key]['stack_id']
        else:
            j_stack_id = j.assets['cloudformation_stack']['stack_id']
        j_type = j.jurisdiction_type.name
        if j_type == 'control_group':
            region = j.configuration['region']
        elif j_type == 'tier':
            region = j.parent.configuration['region']
        elif j_type == 'cluster':
            region = j.parent.parent.configuration['region']

    complete = False
    checks = 0
    status = None
    while not complete:
        time.sleep(30)
        cf_client = boto3.client('cloudformation', region_name=region)
        cf_stack = cf_client.describe_stacks(StackName=j_stack_id)
        latest_status = cf_stack['Stacks'][0]['StackStatus']
        if latest_status != status:
            with db.transaction() as session:
                j = session.query(Jurisdiction).filter_by(id=jurisdiction_id).one()
                assets = j.assets
                if stack_key:
                    assets['cloudformation_stack'][stack_key]['status'] = latest_status
                else:
                    assets['cloudformation_stack']['status'] = latest_status
                j.assets = assets
                flag_modified(j, 'assets')
                if latest_status in ('CREATE_COMPLETE', 'UPDATE_COMPLETE'):
                    if not interim_operation:
                        j.active = True
                    complete = True
                elif latest_status[-6:] == 'FAILED':
                    complete = True
            status = latest_status
            checks += 1
            if checks > 30:
                complete = True


@mq.task
def monitor_cluster_network(jurisdiction_id):
    """
    Monitor the readiness of a cluster's network components during cluster
    provisioning. Once cluster network componenets are ready, cluster nodes
    can be provisioned.
    """
    network_ready = False
    checks = 0
    while not network_ready:
        time.sleep(30)
        with db.transaction() as session:
            j = session.query(Jurisdiction).filter_by(id=jurisdiction_id).one()
            if j.parent.parent.configuration['platform'] == 'amazon_web_services':
                from provisioner.platforms import AWS
                if j.assets['cloudformation_stack']['network']['status'] == 'CREATE_COMPLETE':
                    network_ready = True
                    platform = AWS(j)
                    node_assets = platform.provision_cluster_nodes()
                    node_stack = node_assets.pop('cloudformation_stack')
                    assets = j.assets
                    assets['cloudformation_stack'].update(node_stack)
                    assets.update(node_assets)
                    j.assets = assets
                    flag_modified(j, 'assets')
                    monitor_cloudformation_stack.delay(jurisdiction_id,
                                                       interim_operation=True,
                                                       stack_key='nodes')
                else:
                    checks += 1
                    if checks > 30:
                        network_ready = True


@mq.task
def monitor_cluster_nodes(jurisdiction_id):
    """
    Monitor the readiness of the cluster's nodes during cluster provisioning.
    Once the nodes are ready, the controller/s can be attached to the load
    balancer/s.
    """
    nodes_ready = False
    checks = 0
    while not nodes_ready:
        time.sleep(30)
        with db.transaction() as session:
            j = session.query(Jurisdiction).filter_by(id=jurisdiction_id).one()
            if j.parent.parent.configuration['platform'] == 'amazon_web_services':
                from provisioner.platforms import AWS
                if 'nodes' in j.assets['cloudformation_stack']:
                    if j.assets['cloudformation_stack']['nodes']['status'] == 'CREATE_COMPLETE':
                        nodes_ready = True
                        platform = AWS(j)
                        platform.register_elb_instances()
                        j.active = True
                    else:
                        checks += 1
                        if checks > 30:
                            nodes_ready = True
                else:
                    checks += 1
                    if checks > 30:
                        nodes_ready = True


@mq.task
def monitor_decommission(jurisdiction_id, nodes_stack_id, net_stack_id):
    """
    Monitor the cluster node stack deletion. Once it's complete, trigger the
    deletion of the cluster network stack.
    """
    with db.transaction() as session:
        j = session.query(Jurisdiction).filter_by(id=jurisdiction_id).one()
        region = j.parent.parent.configuration['region']
        cf_client = boto3.client('cloudformation', region_name=region)

        deletion_complete = False
        checks = 0
        while not deletion_complete:
            time.sleep(30)
            if j.parent.parent.configuration['platform'] == 'amazon_web_services':
                node_stack = cf_client.describe_stacks(StackName=nodes_stack_id)
                status = node_stack['Stacks'][0]['StackStatus']
                if status == 'DELETE_COMPLETE':
                    cf_client.delete_stack(StackName=net_stack_id)
                    deletion_complete = True
                elif status[-6:] == 'FAILED':
                    deletion_complete = True
                checks += 1
                if checks > 30:
                    deletion_complete = True

