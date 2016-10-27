import os
import time

import boto3
import celery
from celery import Celery
from sqlalchemy.orm.attributes import flag_modified

from provisioner import db
from provisioner.models import Jurisdiction


app = Celery('tasks', broker='amqp://{0}@{1}//'.format(
                            os.environ.get('SILENUS_PROVISIONER_MQ_USER'),
                            os.environ.get('SILENUS_PROVISIONER_MQ_HOST')))


@app.task
def monitor_cloudformation_stack(jurisdiction_id, stack_id):

    with db.transaction() as session:
        j = session.query(Jurisdiction).filter_by(id=jurisdiction_id).one()

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
        cf_stack = cf_client.describe_stacks(StackName=stack_id)
        latest_status = cf_stack['Stacks'][0]['StackStatus']
        if latest_status != status:
            with db.transaction() as session:
                j = session.query(Jurisdiction).filter_by(id=jurisdiction_id).one()
                assets = j.assets
                assets['cloudformation_stack']['status'] = latest_status
                j.assets = assets
                flag_modified(j, 'assets')
                if latest_status in ('CREATE_COMPLETE', 'UPDATE_COMPLETE'):
                    j.active = True
                    complete = True
                elif latest_status[-6:] == 'FAILED':
                    complete = True
            status = latest_status
            checks += 1
            if checks > 30:
                complete = True

