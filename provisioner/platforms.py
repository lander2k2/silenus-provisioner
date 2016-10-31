import itertools
import random
import string

import boto3
from troposphere import Template, Ref, Tags, ec2, s3, elasticloadbalancing

from provisioner.tasks import monitor_cloudformation_stack, monitor_cluster_network


class AWS(object):
    def __init__(self, jurisdiction):
        self.jurisdiction = jurisdiction

        j_type = self.jurisdiction.jurisdiction_type.name
        if j_type == 'control_group':
            self.region = self.jurisdiction.configuration['region']
        elif j_type == 'tier':
            self.region = self.jurisdiction.parent.configuration['region']
        elif j_type == 'cluster':
            self.region = self.jurisdiction.parent.parent.configuration['region']

    def provision_control_group(self):

        cf_template = Template()
        cf_template.add_version('2010-09-09')
        cf_template.add_description('Control Group: {}'.format(self.jurisdiction.name))

        bucket_name = 'control-group-alpha-bucket-{}'.format(
                        ''.join(random.choice(string.ascii_lowercase) for _ in range(8)))

        bucket = cf_template.add_resource(s3.Bucket(
            'ControlGroupBucket',
            AccessControl='Private',
            BucketName=bucket_name,
            Tags=Tags(Name=bucket_name,
                      control_group=self.jurisdiction.name)))

        cf_template_content = cf_template.to_json()

        stack_name = 'ControlGroup{}'.format(self.jurisdiction.id)

        cf_client = boto3.client('cloudformation', region_name=self.region)
        cf_stack_id = cf_client.create_stack(StackName=stack_name,
                                             TemplateBody=cf_template_content)

        return {'cloudformation_stack': {'stack_id': cf_stack_id['StackId'],
                                         'status': None}}

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
                      control_group=self.jurisdiction.parent.name,
                      tier=self.jurisdiction.name)

            vpc = cf_template.add_resource(ec2.VPC(
                '{}Vpc'.format(vpc_label[0]),
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
                '{}ExternalGatewayAttachement'.format(vpc_label[0]),
                InternetGatewayId=Ref(igw),
                VpcId=Ref(vpc)))

        cf_template_content = cf_template.to_json()

        stack_name = 'Tier{}'.format(self.jurisdiction.id)

        cf_client = boto3.client('cloudformation', region_name=self.region)
        cf_stack_id = cf_client.create_stack(StackName=stack_name,
                                             TemplateBody=cf_template_content)

        return {'cloudformation_stack': {'stack_id': cf_stack_id['StackId'],
                                         'status': None}}

    def provision_cluster_network(self):

        cf_template = Template()
        cf_template.add_version('2010-09-09')
        cf_template.add_description('Cluster: {}'.format(self.jurisdiction.name))

        ec2_client = boto3.client('ec2', region_name=self.region)

        # tier vpc
        vpc_filter = {
                'Name': 'tag:tier',
                'Values': [self.jurisdiction.parent.name]
            }
        tier_vpcs = ec2_client.describe_vpcs(Filters=[vpc_filter])

        for vpc in tier_vpcs['Vpcs']:
            if vpc['CidrBlock'] == self.jurisdiction.parent.configuration['primary_cluster_cidr']:
                vpc_id = vpc['VpcId']

        vpc_rt = ec2_client.describe_route_tables(Filters=[vpc_filter])
        rt_id = vpc_rt['RouteTables'][0]['RouteTableId']

        # subnets
        azs = ec2_client.describe_availability_zones()
        az_names = []
        for a in azs['AvailabilityZones']:
            if a['State'] == 'available':
                az_names.append(a['ZoneName'])
        if 'us-east-1c' in az_names:       # AWS glitch: has status available
            az_names.remove('us-east-1c')  # but cloudformation says no

        az_subnet_assign = zip(self.jurisdiction.configuration['host_subnet_cidrs'],
                               itertools.cycle(az_names))

        subnet_counter = 0
        for assign in az_subnet_assign:
            tag_name = '{}_s{}'.format(self.jurisdiction.name,
                                       subnet_counter)
            tags=Tags(Name=tag_name,
                      control_group=self.jurisdiction.parent.parent.name,
                      tier=self.jurisdiction.parent.name,
                      cluster=self.jurisdiction.name)

            subnet = cf_template.add_resource(ec2.Subnet(
                'Subnet{}'.format(subnet_counter),
                AvailabilityZone=assign[1],
                CidrBlock=assign[0],
                MapPublicIpOnLaunch=True,
                VpcId=vpc_id,
                Tags=tags))

            subnet_rt_assoc = cf_template.add_resource(ec2.SubnetRouteTableAssociation(
                'Subnet{}RouteTableAssociation'.format(subnet_counter),
                RouteTableId=rt_id,
                SubnetId=Ref(subnet)))

            if subnet_counter == 0:
                controller_listener = elasticloadbalancing.Listener(
                        LoadBalancerPort=443,
                        InstancePort=443,
                        Protocol='TCP')
                controller_elb = cf_template.add_resource(elasticloadbalancing.LoadBalancer(
                    'ControllerELB',
                    Listeners=[controller_listener],
                    Subnets=[Ref(subnet)],
                    Tags=Tags(Name='{}_controller'.format(self.jurisdiction.name),
                              control_group=self.jurisdiction.parent.parent.name,
                              tier=self.jurisdiction.parent.name,
                              cluster=self.jurisdiction.name)))

                if self.jurisdiction.parent.configuration['dedicated_etcd'] == True:
                    etcd_listener = elasticloadbalancing.Listener(
                            LoadBalancerPort=2379,
                            InstancePort=2379,
                            Protocol='TCP')
                    etcd_elb = cf_template.add_resource(elasticloadbalancing.LoadBalancer(
                        'EtcdELB',
                        Listeners=[etcd_listener],
                        Scheme='internal',
                        Subnets=[Ref(subnet)],
                        Tags=Tags(Name='{}_etcd'.format(self.jurisdiction.name),
                                  control_group=self.jurisdiction.parent.parent.name,
                                  tier=self.jurisdiction.parent.name,
                                  cluster=self.jurisdiction.name)))

            subnet_counter +=1

        cf_template_content = cf_template.to_json()

        stack_name = 'Cluster{}'.format(self.jurisdiction.id)

        cf_client = boto3.client('cloudformation', region_name=self.region)
        cf_stack_id = cf_client.create_stack(StackName=stack_name,
                                             TemplateBody=cf_template_content)

        return {'cloudformation_stack': {'stack_id': cf_stack_id['StackId'],
                                         'status': None}}

    def provision_cluster_nodes(self):
        return 'testing 1 2 3'

    def provision_cluster(self):
        assets = self.provision_cluster_network()
        monitor_cloudformation_stack.delay(self.jurisdiction.id, final=False)
        monitor_cluster_network.delay(self.jurisdiction.id)

        return assets

    def decommission_jurisdiction(self):

        cf_client = boto3.client('cloudformation', region_name=self.region)
        cf_client.delete_stack(
                    StackName=self.jurisdiction.assets['cloudformation_stack']['stack_id'])

        return {'cloudformation_stack': {'stack_id': None,
                                         'status': None}}

