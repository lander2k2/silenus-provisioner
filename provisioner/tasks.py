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


@mq.task
def monitor_cloudformation_stack(jurisdiction_id, final=True):
    """
    Checks on status of clouformation staxck every 30 seconds and updates status.
    When cloudformation creation or update is complete, it also updates
    active attribute to True. If "final" argument is set to False, this indicates
    that an interim opertaion is being monitored, and the ojbect will *not*
    be marked as active.
    """
    with db.transaction() as session:
        j = session.query(Jurisdiction).filter_by(id=jurisdiction_id).one()

        j_assets = j.assets
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
                assets['cloudformation_stack']['status'] = latest_status
                j.assets = assets
                flag_modified(j, 'assets')
                if latest_status in ('CREATE_COMPLETE', 'UPDATE_COMPLETE'):
                    if final == True:
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
    Monitor the readiness of a cluter's network components during cluster
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
                if j.assets['cloudformation_stack']['status'] == 'CREATE_COMPLETE':
                    network_ready = True
                    ##############################
                    platform = AWS(j)
                    test_data = platform.provision_cluster_nodes()
                    assets = j.assets
                    assets['test_data'] = test_data
                    j.assets = assets
                    flag_modified(j, 'assets')
                    ##############################
                    monitor_cloudformation_stack.delay(jurisdiction_id)

            else:
                checks += 1
                if checks > 30:
                    network_ready = True

