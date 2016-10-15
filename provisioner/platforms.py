import random
import string

import boto3


class AWS(object):
    def __init__(self, jurisdiction):
        self.jurisdiction = jurisdiction

    def provision_control_group(self):
        region = self.jurisdiction.configuration['region']

        bucket_name = 'cg-alpha-bucket-{}'.format(
                        ''.join(random.choice(string.ascii_lowercase) for _ in range(8)))

        s3_client = boto3.client('s3', region_name=region)
        if region == 'us-east-1':
            r = s3_client.create_bucket(
                                ACL='private',
                                Bucket=bucket_name)
        else:
            r = s3_client.create_bucket(
                                ACL='private',
                                Bucket=bucket_name,
                                CreateBucketConfiguration={
                                    'LocationConstraint': region
                                })

        return {'s3_bucket': bucket_name}

    def decommission_control_group(self):
        bucket_name = self.jurisdiction.assets['s3_bucket']

        s3_client = boto3.client('s3', region_name=self.jurisdiction.configuration['region'])
        s3_client.delete_bucket(Bucket=bucket_name)

        return {'s3_bucket': None}

