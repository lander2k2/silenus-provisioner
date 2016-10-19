import random
import string

import boto3
from troposphere import Template, Ref, Tags, ec2


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

    def provision_tier(self):

        cf_template = Template()
        cf_template.add_version('2010-09-09')
        cf_template.add_description('Tier: {}'.format(self.jurisdiction.name))

        if self.jurisdiction.configuration['support_cluster']:
            vpc_labels = (('Primary', 'primary'),
                           ('Support', 'support'))
        else:
            vpc_labels = (('Primary', 'primary'),)

        for vpc_label in vpc_labels:

            tag_name = '{}_{}'.format(self.jurisdiction.name,
                                      vpc_label[1])
            cidr_key = '{}_cluster_cidr'.format(vpc_label[1])

            tags=Tags(Name=tag_name,
                      control_group=self.jurisdiction.parent_jurisdiction.name,
                      tier=self.jurisdiction.name)

            vpc = cf_template.add_resource(ec2.VPC(
                '{}VPC'.format(vpc_label[0]),
                CidrBlock=self.jurisdiction.configuration[cidr_key],
                EnableDnsHostnames=True,
                EnableDnsSupport=True,
                InstanceTenancy='default',
                Tags=tags))

            rt = cf_template.add_resource(ec2.RouteTable(
                '{}RouteTable'.format(vpc_label[0]),
                VpcId=Ref(vpc),
                Tags=tags))

            igw = cf_template.add_resource(ec2.InternetGateway(
                '{}InternetGateway'.format(vpc_label[0]),
                Tags=tags))

            external_route = cf_template.add_resource(ec2.Route(
                '{}ExternalRoute'.format(vpc_label[0]),
                GatewayId=Ref(igw),
                DestinationCidrBlock='0.0.0.0/0',
                RouteTableId=Ref(rt)))

            gateway_attach = cf_template.add_resource(ec2.VPCGatewayAttachment(
                '{}ExternalGateWayAttachement'.format(vpc_label[0]),
                InternetGatewayId=Ref(igw),
                VpcId=Ref(vpc)))

        cf_template_content = cf_template.to_json()

        cf_client = boto3.client('cloudformation',
                        region_name=self.jurisdiction.parent_jurisdiction.configuration['region'])

        stack_name = 'Tier{}'.format(self.jurisdiction.id)
        cf_stack_id = cf_client.create_stack(StackName=stack_name,
                                             TemplateBody=cf_template_content)

        return {'cloudformation_stack': cf_stack_id['StackId']}

    def activate_tier(self):

        cf_client = boto3.client('cloudformation',
                        region_name=self.jurisdiction.parent_jurisdiction.configuration['region'])

        stacks = cf_client.describe_stacks(
                            StackName=self.jurisdiction.assets['cloudformation_stack'])

        stack_status = stacks['Stacks'][0]['StackStatus']
        if stack_status in ('CREATE_COMPLETE', 'UPDATE_COMPLETE'):
            return True
        else:
            return False

    def decommission_tier(self):

        cf_client = boto3.client('cloudformation',
                        region_name=self.jurisdiction.parent_jurisdiction.configuration['region'])

        cf_client.delete_stack(
                    StackName=self.jurisdiction.assets['cloudformation_stack'])

        return {'cloudformation_stack': None}

