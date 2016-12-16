import base64
import gzip
import itertools
import random
import string

import boto3
import jinja2
import requests
from OpenSSL.crypto import PKey, X509, X509Req, X509Extension
from OpenSSL.crypto import dump_privatekey, dump_certificate_request, dump_certificate
from OpenSSL.crypto import TYPE_RSA, FILETYPE_PEM
from troposphere import Template, Ref, Tags, Output, ImportValue, Export, AWSHelperFn
from troposphere import ec2, s3, elasticloadbalancing, autoscaling, iam, cloudwatch, policies

from provisioner import db
from provisioner.tasks import monitor_cloudformation_stack, monitor_cluster_network
from provisioner.tasks import monitor_cluster_nodes, monitor_decommission
from provisioner.models import UserdataTemplate


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

        self.standard_egress = [
                {
                    'CidrIp': '0.0.0.0/0',
                    'FromPort': 0,
                    'ToPort': 65535,
                    'IpProtocol': 'tcp'
                },
                {
                    'CidrIp': '0.0.0.0/0',
                    'FromPort': 0,
                    'ToPort': 65535,
                    'IpProtocol': 'udp'
                }
            ]

        self.standard_ingress = [
                {
                    'CidrIp': '0.0.0.0/0',
                    'FromPort': 3,
                    'ToPort': -1,
                    'IpProtocol': 'icmp'
                },
                {
                    'CidrIp': '0.0.0.0/0',
                    'FromPort': 22,
                    'ToPort': 22,
                    'IpProtocol': 'tcp'
                }
            ]

    def _save_to_s3(self, filepath, str_content):
        s3_client = boto3.client('s3', region_name=self.region)

        j_type = self.jurisdiction.jurisdiction_type.name
        if j_type == 'control_group':
            bucket = self.jurisdiction.assets['s3_bucket']
        elif j_type == 'tier':
            bucket = self.jurisdiction.parent.assets['s3_bucket']
        elif j_type == 'cluster':
            bucket = self.jurisdiction.parent.parent.assets['s3_bucket']

        s3_client.put_object(ACL='private',
                             Bucket=bucket,
                             Key=filepath,
                             Body=str_content)

    def _compress_encode(self, b_content):
        return base64.b64encode(gzip.compress(b_content))

    def _kms_encrypt(self, kms_key_arn, b_content):
        kms_client = boto3.client('kms', region_name=self.region)

        encrypted_content = kms_client.encrypt(
                                KeyId=kms_key_arn,
                                Plaintext=b_content)

        return encrypted_content['CiphertextBlob']

    def _generate_cluster_tls_assets(self):
        """
        Generate cluster's root certificate authority and a cluster
        admin key pair. Upload to S3 bucket.
        """
        # cluster root CA
        ca_key = PKey()
        ca_key.generate_key(TYPE_RSA, 2048)
        ca_key_filepath = '{0}/credentials/ca-key.pem'.format(self.jurisdiction.name)
        self._save_to_s3(ca_key_filepath,
                         dump_privatekey(FILETYPE_PEM, ca_key).decode('utf-8'))

        ca_csr = X509Req()
        ca_csr.set_version(0)
        ca_csr.get_subject().CN = '{}-ca'.format(self.jurisdiction.name)
        ca_csr.set_pubkey(ca_key)
        ca_csr.sign(ca_key,'sha1')
        ca_csr_filepath = '{0}/credentials/ca.csr'.format(self.jurisdiction.name)
        self._save_to_s3(ca_csr_filepath,
                         dump_certificate_request(FILETYPE_PEM, ca_csr).decode('utf-8'))

        ca = X509()
        ca.set_version(2)
        ca.set_serial_number(random.getrandbits(64))
        ca.gmtime_adj_notBefore(0)
        ca.gmtime_adj_notAfter(60*60*24*365*10)
        ca.set_subject(ca_csr.get_subject())
        ca.set_issuer(ca.get_subject())
        ca.set_pubkey(ca_csr.get_pubkey())
        ca.add_extensions([
            X509Extension(b'subjectKeyIdentifier', False, b'hash', subject=ca)
        ])
        ca.add_extensions([
            X509Extension(b'authorityKeyIdentifier', False,
                          b'keyid:always,issuer:always', issuer=ca)
        ])
        ca.add_extensions([
            X509Extension(b'basicConstraints', False, b'CA:TRUE')
        ])
        ca.sign(ca_key, 'sha1')
        ca_filepath = '{0}/credentials/ca.pem'.format(self.jurisdiction.name)
        self._save_to_s3(ca_filepath,
                         dump_certificate(FILETYPE_PEM, ca).decode('utf-8'))

        # cluster admin key pair
        admin_key = PKey()
        admin_key.generate_key(TYPE_RSA, 2048)
        admin_key_filepath = '{0}/credentials/admin-key.pem'.format(self.jurisdiction.name)
        self._save_to_s3(admin_key_filepath,
                         dump_privatekey(FILETYPE_PEM, admin_key).decode('utf-8'))

        admin_csr = X509Req()
        admin_csr.set_version(0)
        admin_csr.get_subject().CN = '{}-admin'.format(self.jurisdiction.name)
        admin_csr.set_pubkey(admin_key)
        admin_csr.sign(admin_key,'sha1')
        admin_csr_filepath = '{0}/credentials/admin.csr'.format(self.jurisdiction.name)
        self._save_to_s3(admin_csr_filepath,
                         dump_certificate_request(FILETYPE_PEM, admin_csr).decode('utf-8'))

        admin = X509()
        admin.set_version(1)
        admin.set_serial_number(random.getrandbits(64))
        admin.gmtime_adj_notBefore(0)
        admin.gmtime_adj_notAfter(60*60*24*365*10)
        admin.set_issuer(ca.get_subject())
        admin.set_subject(admin_csr.get_subject())
        admin.set_pubkey(admin_csr.get_pubkey())
        admin.sign(ca_key, 'sha1')
        admin_filepath = '{0}/credentials/admin.pem'.format(self.jurisdiction.name)
        self._save_to_s3(admin_filepath,
                         dump_certificate(FILETYPE_PEM, admin).decode('utf-8'))

        return ca, ca_key

    def _generate_apiserver_tls_assets(self, cluster_ca, cluster_ca_key, load_balancer):
        """
        Generate Kubernetes API server key pair and upload to S3 bucket.
        """
        apiserver_subject_alt_names = 'DNS:{}, '.format(load_balancer)
        for name in self.jurisdiction.configuration['kubernetes_api_dns_names']:
            apiserver_subject_alt_names += 'DNS:{}, '.format(name)
        for ip in self.jurisdiction.configuration['controller_ips']:
            apiserver_subject_alt_names += 'IP:{}, '.format(ip)
        apiserver_subject_alt_names += 'IP:{}'.format(
                            self.jurisdiction.configuration['kubernetes_api_ip'])

        apiserver_key = PKey()
        apiserver_key.generate_key(TYPE_RSA, 2048)
        apiserver_key_filepath = '{0}/credentials/apiserver-key.pem'.format(self.jurisdiction.name)
        self._save_to_s3(apiserver_key_filepath,
                         dump_privatekey(FILETYPE_PEM, apiserver_key).decode('utf-8'))

        apiserver_csr = X509Req()
        apiserver_csr.set_version(0)
        apiserver_csr.get_subject().CN = '{}-apiserver'.format(self.jurisdiction.name)
        apiserver_csr.set_pubkey(apiserver_key)
        apiserver_csr.add_extensions([
            X509Extension(b'basicConstraints', False, b'CA:FALSE'),
            X509Extension(b'keyUsage', False, b'nonRepudiation, digitalSignature, keyEncipherment'),
            X509Extension(b'subjectAltName', False, apiserver_subject_alt_names.encode('utf-8'))
        ])
        apiserver_csr.sign(apiserver_key,'sha1')
        apiserver_csr_filepath = '{0}/credentials/apiserver.csr'.format(self.jurisdiction.name)
        self._save_to_s3(apiserver_csr_filepath,
                         dump_certificate_request(FILETYPE_PEM, apiserver_csr).decode('utf-8'))

        apiserver = X509()
        apiserver.set_version(2)
        apiserver.set_serial_number(random.getrandbits(64))
        apiserver.gmtime_adj_notBefore(0)
        apiserver.gmtime_adj_notAfter(60*60*24*365*10)
        apiserver.set_issuer(cluster_ca.get_subject())
        apiserver.set_subject(apiserver_csr.get_subject())
        apiserver.set_pubkey(apiserver_csr.get_pubkey())
        apiserver.add_extensions(apiserver_csr.get_extensions())
        apiserver.sign(cluster_ca_key, 'sha1')
        apiserver_filepath = '{0}/credentials/apiserver.pem'.format(self.jurisdiction.name)
        self._save_to_s3(apiserver_filepath,
                         dump_certificate(FILETYPE_PEM, apiserver).decode('utf-8'))

        return (dump_privatekey(FILETYPE_PEM, apiserver_key),
                dump_certificate(FILETYPE_PEM, apiserver))

    def _generate_worker_tls_assets(self, cluster_ca, cluster_ca_key):
        """
        Generate worker's key pair and upload to S3 bucket.
        """
        worker_key = PKey()
        worker_key.generate_key(TYPE_RSA, 2048)
        worker_key_filepath = '{0}/credentials/worker-key.pem'.format(self.jurisdiction.name)
        self._save_to_s3(worker_key_filepath,
                         dump_privatekey(FILETYPE_PEM, worker_key).decode('utf-8'))

        worker_csr = X509Req()
        worker_csr.set_version(0)
        worker_csr.get_subject().CN = '{}-worker'.format(self.jurisdiction.name)
        worker_csr.set_pubkey(worker_key)
        worker_csr.add_extensions([
            X509Extension(b'basicConstraints', False, b'CA:FALSE'),
            X509Extension(b'keyUsage', False, b'nonRepudiation, digitalSignature, keyEncipherment'),
            X509Extension(b'subjectAltName', False, b'DNS:*.*.compute.internal, DNS:*.ec2.internal')
        ])
        worker_csr.sign(worker_key,'sha1')
        worker_csr_filepath = '{0}/credentials/worker.csr'.format(self.jurisdiction.name)
        self._save_to_s3(worker_csr_filepath,
                         dump_certificate_request(FILETYPE_PEM, worker_csr).decode('utf-8'))

        worker = X509()
        worker.set_version(2)
        worker.set_serial_number(random.getrandbits(64))
        worker.gmtime_adj_notBefore(0)
        worker.gmtime_adj_notAfter(60*60*24*365*10)
        worker.set_issuer(cluster_ca.get_subject())
        worker.set_subject(worker_csr.get_subject())
        worker.set_pubkey(worker_csr.get_pubkey())
        worker.add_extensions(worker_csr.get_extensions())
        worker.sign(cluster_ca_key, 'sha1')
        worker_filepath = '{0}/credentials/worker.pem'.format(self.jurisdiction.name)
        self._save_to_s3(worker_filepath,
                         dump_certificate(FILETYPE_PEM, worker).decode('utf-8'))

        return (dump_privatekey(FILETYPE_PEM, worker_key),
                dump_certificate(FILETYPE_PEM, worker))

    def _generate_userdata(self, role, kms_key_arn, count, load_balancers,
                           cluster_ca, cluster_ca_key):
        """
        Generate userdata file from template and save to S3 bucket.
        """
        assert role in ('worker', 'controller', 'etcd')

        # assemble template variables
        template_vars = {
            'count': str(count),
            'region': self.region
        }
        template_vars['controller_elb_dns'] = load_balancers['controller']
        if 'etcd' in load_balancers:
            template_vars['etcd_elb_dns'] = load_balancers['etcd']

        template_vars['enc_cluster_ca'] = self._compress_encode(
                                              self._kms_encrypt(
                                                  kms_key_arn,
                                                  dump_certificate(FILETYPE_PEM, cluster_ca)
                                              )
                                          ).decode('utf-8')
        if role == 'worker':
            worker_key, worker_cert = self._generate_worker_tls_assets(cluster_ca,
                                                                       cluster_ca_key)
            template_vars['enc_worker_key'] = self._compress_encode(
                                                 self._kms_encrypt(
                                                     kms_key_arn,
                                                     worker_key
                                                 )
                                              ).decode('utf-8')
            template_vars['enc_worker_cert'] = self._compress_encode(
                                                  self._kms_encrypt(
                                                      kms_key_arn,
                                                      worker_cert
                                                  )
                                               ).decode('utf-8')
        elif role == 'controller':
            apiserver_key, apiserver_cert = self._generate_apiserver_tls_assets(
                                                        cluster_ca,
                                                        cluster_ca_key,
                                                        load_balancers['controller'])
            template_vars['enc_apiserver_key'] = self._compress_encode(
                                                     self._kms_encrypt(
                                                         kms_key_arn,
                                                         apiserver_key
                                                     )
                                                 ).decode('utf-8')
            template_vars['enc_apiserver_cert'] = self._compress_encode(
                                                     self._kms_encrypt(
                                                         kms_key_arn,
                                                         apiserver_cert
                                                     )
                                                  ).decode('utf-8')

        template_vars.update(self.jurisdiction.configuration)
        template_vars.update(self.jurisdiction.parent.configuration)
        template_vars.update(self.jurisdiction.parent.parent.configuration)

        # generate userdata from template
        template_id = self.jurisdiction.configuration['userdata_template_ids'][role]
        with db.transaction() as session:
            template = session.query(UserdataTemplate.content).filter_by(id=template_id).one()
        userdata_template = jinja2.Template(template.content)
        userdata_content = userdata_template.render(template_vars)

        # save userdata file to s3 bucket
        s3_client = boto3.client('s3', region_name=self.region)
        userdata_filepath = '{0}/userdata/cloud-config-{1}-{2}'.format(
                                        self.jurisdiction.name, role, count)
        self._save_to_s3(userdata_filepath, userdata_content)

        return self._compress_encode(userdata_content.encode('utf-8')).decode('utf-8')

    def provision_control_group(self):

        cg_template = Template()
        cg_template.add_version('2010-09-09')
        cg_template.add_description('Control Group: {}'.format(self.jurisdiction.name))

        rand = ''.join(random.choice(string.ascii_lowercase) for _ in range(8))
        bucket_name = 'control-group-alpha-bucket-{}'.format(rand)

        bucket = cg_template.add_resource(s3.Bucket(
            'ControlGroupBucket',
            AccessControl='Private',
            BucketName=bucket_name,
            Tags=Tags(Name=bucket_name,
                      control_group=self.jurisdiction.name)
        ))

        cg_template_content = cg_template.to_json()

        stack_name = 'ControlGroup{}'.format(str(self.jurisdiction.id).zfill(2))

        cf_client = boto3.client('cloudformation', region_name=self.region)
        cf_stack = cf_client.create_stack(StackName=stack_name,
                                             TemplateBody=cg_template_content)

        return {
            'cloudformation_stack': {
                'stack_id': cf_stack['StackId'],
                'status': None
            },
            's3_bucket': bucket_name
        }

    def provision_tier(self):

        tier_template = Template()
        tier_template.add_version('2010-09-09')
        tier_template.add_description('Tier: {}'.format(self.jurisdiction.name))

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

            vpc = tier_template.add_resource(ec2.VPC(
                '{}Vpc'.format(vpc_label[0]),
                CidrBlock=self.jurisdiction.configuration[cidr_key],
                EnableDnsHostnames=True,
                EnableDnsSupport=True,
                InstanceTenancy='default',
                Tags=tags
            ))

            tier_template.add_output(Output(
                'TierVpc{}Output'.format(vpc_label[0]),
                Description='ID for {} VPC'.format(vpc_label[1]),
                Value=Ref(vpc),
                Export=Export('{}-vpc-{}'.format(self.jurisdiction.id, vpc_label[1]))
            ))

            rt = tier_template.add_resource(ec2.RouteTable(
                '{}RouteTable'.format(vpc_label[0]),
                VpcId=Ref(vpc),
                Tags=tags
            ))

            tier_template.add_output(Output(
                'TierRouteTable{}Output'.format(vpc_label[0]),
                Description='ID for {} VPC route table'.format(vpc_label[1]),
                Value=Ref(rt),
                Export=Export('{}-rt-{}'.format(self.jurisdiction.id, vpc_label[1]))
            ))

            igw = tier_template.add_resource(ec2.InternetGateway(
                '{}InternetGateway'.format(vpc_label[0]),
                Tags=tags
            ))

            external_route = tier_template.add_resource(ec2.Route(
                '{}ExternalRoute'.format(vpc_label[0]),
                GatewayId=Ref(igw),
                DestinationCidrBlock='0.0.0.0/0',
                RouteTableId=Ref(rt)
            ))

            gateway_attach = tier_template.add_resource(ec2.VPCGatewayAttachment(
                '{}ExternalGatewayAttachement'.format(vpc_label[0]),
                InternetGatewayId=Ref(igw),
                VpcId=Ref(vpc)
            ))

        tier_template_content = tier_template.to_json()

        stack_name = 'Tier{}'.format(str(self.jurisdiction.id).zfill(3))

        cf_client = boto3.client('cloudformation', region_name=self.region)
        cf_stack = cf_client.create_stack(StackName=stack_name,
                                             TemplateBody=tier_template_content)

        return {
            'cloudformation_stack': {
                'stack_id': cf_stack['StackId'],
                'status': None
            }
        }

    def provision_cluster_network(self):

        net_template = Template()
        net_template.add_version('2010-09-09')
        net_template.add_description('Network for Cluster: {}'.format(self.jurisdiction.name))

        ec2_client = boto3.client('ec2', region_name=self.region)

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
        azs_used = []

        subnet_counter = 0
        for assign in az_subnet_assign:
            if assign[1] not in azs_used:
                azs_used.append(assign[1])

            tag_name = '{}_s{}'.format(self.jurisdiction.name,
                                       subnet_counter)
            tags=Tags(Name=tag_name,
                      control_group=self.jurisdiction.parent.parent.name,
                      tier=self.jurisdiction.parent.name,
                      cluster=self.jurisdiction.name)

            subnet = net_template.add_resource(ec2.Subnet(
                'Subnet{}'.format(subnet_counter),
                AvailabilityZone=assign[1],
                CidrBlock=assign[0],
                MapPublicIpOnLaunch=True,
                VpcId=ImportValue('{}-vpc-primary'.format(self.jurisdiction.parent.id)),
                Tags=tags
            ))

            net_template.add_output(Output(
                'ClusterSubnet{}Output'.format(subnet_counter),
                Description='ID for subnet {}'.format(subnet_counter),
                Value=Ref(subnet),
                Export=Export('{}-subnet-{}'.format(self.jurisdiction.id, subnet_counter))
            ))

            subnet_rt_assoc = net_template.add_resource(ec2.SubnetRouteTableAssociation(
                'Subnet{}RouteTableAssociation'.format(subnet_counter),
                RouteTableId=ImportValue('{}-rt-primary'.format(self.jurisdiction.parent.id)),
                SubnetId=Ref(subnet)
            ))

            if subnet_counter == 0:
                security_group_elb_controller = net_template.add_resource(ec2.SecurityGroup(
                    'SecurityGroupElbController',
                    GroupDescription='Kubernetes controller ELB security group',
                    SecurityGroupEgress=self.standard_egress,
                    SecurityGroupIngress=self.standard_ingress + [
                        {
                            'CidrIp': '0.0.0.0/0',
                            'FromPort': 443,
                            'ToPort': 443,
                            'IpProtocol': 'tcp'
                        }
                    ],
                    VpcId=ImportValue('{}-vpc-primary'.format(self.jurisdiction.parent.id)),
                    Tags=Tags(Name='{}_sg_elb_controller'.format(self.jurisdiction.name),
                              control_group=self.jurisdiction.parent.parent.name,
                              tier=self.jurisdiction.parent.name,
                              cluster=self.jurisdiction.name)
                ))

                elb_controller = net_template.add_resource(elasticloadbalancing.LoadBalancer(
                    'ElbController',
                    Listeners=[
                        {
                            'LoadBalancerPort': '443',
                            'InstancePort': '443',
                            'Protocol': 'TCP'
                        }
                    ],
                    SecurityGroups=[
                        Ref(security_group_elb_controller)
                    ],
                    Subnets=[
                        Ref(subnet)
                    ],
                    Tags=Tags(Name='{}_controller'.format(self.jurisdiction.name),
                              control_group=self.jurisdiction.parent.parent.name,
                              tier=self.jurisdiction.parent.name,
                              cluster=self.jurisdiction.name)
                ))

                net_template.add_output(Output(
                    'ElbControllerOutput',
                    Description='ID for controller ELB',
                    Value=Ref(elb_controller),
                    Export=Export('{}-elb-controller'.format(self.jurisdiction.id))
                ))

                if self.jurisdiction.parent.configuration['dedicated_etcd']:
                    security_group_elb_etcd = net_template.add_resource(ec2.SecurityGroup(
                        'SecurityGroupElbEtcd',
                        GroupDescription='Kubernetes etcd ELB security group',
                        SecurityGroupEgress=self.standard_egress,
                        SecurityGroupIngress=self.standard_ingress,
                        VpcId=ImportValue('{}-vpc-primary'.format(self.jurisdiction.parent.id)),
                        Tags=Tags(Name='{}_sg_elb_etcd'.format(self.jurisdiction.name),
                                  control_group=self.jurisdiction.parent.parent.name,
                                  tier=self.jurisdiction.parent.name,
                                  cluster=self.jurisdiction.name)
                    ))

                    elb_etcd = net_template.add_resource(elasticloadbalancing.LoadBalancer(
                        'ElbEtcd',
                        Listeners=[
                            {
                                'LoadBalancerPort': '2379',
                                'InstancePort': '2379',
                                'Protocol': 'TCP'
                            }
                        ],
                        Scheme='internal',
                        SecurityGroups=[
                            Ref(security_group_elb_etcd)
                        ],
                        Subnets=[
                            Ref(subnet)
                        ],
                        Tags=Tags(Name='{}_etcd'.format(self.jurisdiction.name),
                                  control_group=self.jurisdiction.parent.parent.name,
                                  tier=self.jurisdiction.parent.name,
                                  cluster=self.jurisdiction.name)
                    ))

                    net_template.add_output(Output(
                        'ElbEtcdOutput',
                        Description='ID for etcd ELB',
                        Value=Ref(elb_etcd),
                        Export=Export('{}-elb-etcd'.format(self.jurisdiction.id))
                    ))

            subnet_counter +=1

        net_template_content = net_template.to_json()

        stack_name = 'ClusterNet{}'.format(str(self.jurisdiction.id).zfill(4))

        cf_client = boto3.client('cloudformation', region_name=self.region)
        cf_stack = cf_client.create_stack(StackName=stack_name,
                                          TemplateBody=net_template_content)

        return {
            'cloudformation_stack': {
                'network': {
                    'stack_id': cf_stack['StackId'],
                    'status': None
                }
            }
        }

    def provision_cluster_nodes(self):

        node_template = Template()
        node_template.add_version('2010-09-09')
        node_template.add_description('Nodes for Cluster: {}'.format(self.jurisdiction.name))

        # ceritificate authority
        cluster_ca, cluster_ca_key = self._generate_cluster_tls_assets()

        # ec2 key pair
        ec2_client = boto3.client('ec2', region_name=self.region)
        ec2_key_pair = ec2_client.create_key_pair(KeyName=self.jurisdiction.name)
        private_key_content = ec2_key_pair['KeyMaterial']

        s3_client = boto3.client('s3', region_name=self.region)
        private_key_filepath = '{0}/credentials/{0}.pem'.format(self.jurisdiction.name)
        self._save_to_s3(private_key_filepath, private_key_content)

        # kms key
        kms_client = boto3.client('kms', region_name=self.region)
        kms_key = kms_client.create_key(Description=self.jurisdiction.name)
        kms_key_arn = kms_key['KeyMetadata']['Arn']

        kms_client.create_alias(TargetKeyId=kms_key_arn,
                                AliasName='alias/{}'.format(self.jurisdiction.name))

        # amazone machine image
        url = 'https://coreos.com/dist/aws/aws-{}.json'.format(
                        self.jurisdiction.configuration['coreos_release_channel'])
        image_ids = requests.get(url, timeout=20)
        ami = image_ids.json()[self.region]['hvm']

        # load balancers
        elb_client = boto3.client('elb', region_name=self.region)
        load_balancers = {}
        marker = None
        elb_search_complete = False
        while not elb_search_complete:
            if marker:
                all_elbs = elb_client.describe_load_balancers(Marker=marker)
            else:
                all_elbs = elb_client.describe_load_balancers()  # cannot filter by tag :/
            marker = all_elbs.get('NextMarker')
            if not marker:
                elb_search_complete = True
            for elb in all_elbs['LoadBalancerDescriptions']:  # doesn't have tags in description :/
                elb_tags = elb_client.describe_tags(LoadBalancerNames=[elb['LoadBalancerName']])
                for tag in elb_tags['TagDescriptions'][0]['Tags']:
                    if tag['Key'] == 'Name' and tag['Value'] == '{}_controller'.format(self.jurisdiction.name):
                        load_balancers['controller'] = elb['DNSName']
                    elif tag['Key'] == 'Name' and tag['Value'] == '{}_etcd'.format(self.jurisdiction.name):
                        load_balancers['etcd'] = elb['DNSName']
                if self.jurisdiction.parent.configuration['dedicated_etcd']:
                    if len(load_balancers) == 2:
                        elb_search_complete = True
                        break
                else:
                    if load_balancers:
                        elb_search_complete = True
                        break

        # universal tags
        cluster_tags = {
                'control_group': self.jurisdiction.parent.parent.name,
                'tier': self.jurisdiction.parent.name,
                'cluster': self.jurisdiction.name
            }

        # security groups
        security_group_controller_tags = {
                'Name': '{}_controller'.format(self.jurisdiction.name)
            }
        security_group_controller_tags.update(cluster_tags)

        security_group_controller = node_template.add_resource(ec2.SecurityGroup(
            'SecurityGroupController',
            GroupDescription='Kubernetes controller node security group',
            SecurityGroupEgress=self.standard_egress,
            SecurityGroupIngress=self.standard_ingress + [
                {
                    'CidrIp': '0.0.0.0/0',
                    'FromPort': 443,
                    'ToPort': 443,
                    'IpProtocol': 'tcp'
                }
            ],
            VpcId=ImportValue('{}-vpc-primary'.format(self.jurisdiction.parent.id)),
            Tags=Tags(**security_group_controller_tags)
        ))

        node_template.add_output(Output(
            'SecurityGroupControllerOutput',
            Description='ID for controller security group',
            Value=Ref(security_group_controller),
            Export=Export('{}-security-group-controller'.format(self.jurisdiction.id))
        ))

        security_group_worker_tags = {
                'Name': '{}_worker'.format(self.jurisdiction.name)
            }
        security_group_worker_tags.update(cluster_tags)

        security_group_worker = node_template.add_resource(ec2.SecurityGroup(
            'SecurityGroupWorker',
            GroupDescription='Kubernetes worker node security group',
            SecurityGroupEgress=self.standard_egress,
            SecurityGroupIngress=self.standard_ingress + [
                {
                    'CidrIp': self.jurisdiction.parent.parent.configuration['control_cluster_cidr'],
                    'FromPort': 30900,
                    'ToPort': 30900,
                    'IpProtocol': 'tcp'
                }
            ],
            VpcId=ImportValue('{}-vpc-primary'.format(self.jurisdiction.parent.id)),
            Tags=Tags(**security_group_worker_tags)
        ))

        ingress_flannel_controller_to_worker = node_template.add_resource(ec2.SecurityGroupIngress(
            'IngressFlannelControllerToWorker',
            FromPort=8472,
            ToPort=8472,
            IpProtocol='udp',
            GroupId=Ref(security_group_worker),
            SourceSecurityGroupId=Ref(security_group_controller)
        ))

        ingress_flannel_worker_to_controller = node_template.add_resource(ec2.SecurityGroupIngress(
            'IngressFlannelWorkerToController',
            FromPort=8472,
            ToPort=8472,
            IpProtocol='udp',
            GroupId=Ref(security_group_controller),
            SourceSecurityGroupId=Ref(security_group_worker)
        ))

        ingress_flannel_worker_to_worker = node_template.add_resource(ec2.SecurityGroupIngress(
            'IngressFlannelWorkerToWorker',
            FromPort=8472,
            ToPort=8472,
            IpProtocol='udp',
            GroupId=Ref(security_group_worker),
            SourceSecurityGroupId=Ref(security_group_worker)
        ))

        ingress_kubelet_controller_to_worker = node_template.add_resource(ec2.SecurityGroupIngress(
            'IngressKubeletControllerToWorker',
            FromPort=10250,
            ToPort=10250,
            IpProtocol='tcp',
            GroupId=Ref(security_group_worker),
            SourceSecurityGroupId=Ref(security_group_controller)
        ))

        ingress_kubelet_worker_to_controller = node_template.add_resource(ec2.SecurityGroupIngress(
            'IngressKubeletWorkerToController',
            FromPort=10255,
            ToPort=10255,
            IpProtocol='tcp',
            GroupId=Ref(security_group_controller),
            SourceSecurityGroupId=Ref(security_group_worker)
        ))

        ingress_kubelet_worker_to_worker = node_template.add_resource(ec2.SecurityGroupIngress(
            'IngressKubeletWorkerToWorker',
            FromPort=10255,
            ToPort=10255,
            IpProtocol='tcp',
            GroupId=Ref(security_group_worker),
            SourceSecurityGroupId=Ref(security_group_worker)
        ))

        ingress_cadvisor_controller_to_worker = node_template.add_resource(ec2.SecurityGroupIngress(
            'IngressCadvisorControllerToWorker',
            FromPort=4194,
            ToPort=4194,
            IpProtocol='tcp',
            GroupId=Ref(security_group_worker),
            SourceSecurityGroupId=Ref(security_group_controller)
        ))

        if self.jurisdiction.parent.configuration['dedicated_etcd']:
            security_group_etcd_tags = {
                    'Name': '{}_etcd'.format(self.jurisdiction.name)
                }
            security_group_etcd_tags.update(cluster_tags)

            security_group_etcd = node_template.add_resource(ec2.SecurityGroup(
                'SecurityGroupEtcd',
                GroupDescription='Kubernetes etcd node security group',
                SecurityGroupEgress=self.standard_egress,
                SecurityGroupIngress=self.standard_ingress,
                VpcId=ImportValue('{}-vpc-primary'.format(self.jurisdiction.parent.id)),
                Tags=Tags(**security_group_etcd_tags)
            ))

            node_template.add_output(Output(
                'SecurityGroupEtcdOutput',
                Description='ID for etcd security group',
                Value=Ref(security_group_etcd),
                Export=Export('{}-security-group-etcd'.format(self.jurisdiction.id))
            ))

            etcd_group_ref = Ref(security_group_etcd)

            ingress_etcd_peer = node_template.add_resource(ec2.SecurityGroupIngress(
                'IngressEtcdPeer',
                FromPort=2379,
                ToPort=2380,
                IpProtocol='tcp',
                GroupId=etcd_group_ref,
                SourceSecurityGroupId=etcd_group_ref
            ))

            ingress_etcd_controller_to_etcd = node_template.add_resource(ec2.SecurityGroupIngress(
                'IngressEtcdControllerToEtcd',
                FromPort=2379,
                ToPort=2379,
                IpProtocol='tcp',
                GroupId=etcd_group_ref,
                SourceSecurityGroupId=Ref(security_group_controller)
            ))
        else:
            etcd_group_ref = Ref(security_group_controller)

            ingress_etcd_controller_to_etcd = node_template.add_resource(ec2.SecurityGroupIngress(
                'IngressEtcdControllerToEtcd',
                FromPort=2379,
                ToPort=2380,
                IpProtocol='tcp',
                GroupId=etcd_group_ref,
                SourceSecurityGroupId=Ref(security_group_controller)
            ))

        ingress_etcd_worker_to_etcd = node_template.add_resource(ec2.SecurityGroupIngress(
            'IngressEtcdWorkerToEtcd',
            FromPort=2379,
            ToPort=2379,
            IpProtocol='tcp',
            GroupId=etcd_group_ref,
            SourceSecurityGroupId=Ref(security_group_worker)
        ))

        # workers
        iam_policy_worker = iam.Policy(
            'IamPolicyWorker',
            PolicyName='root',
            PolicyDocument={
                'Statement': [
                    {
                        'Action': 'ec2:Describe*',
                        'Effect': 'Allow',
                        'Resource': '*'
                    },
                    {
                        'Action': 'ec2:AttachVolume',
                        'Effect': 'Allow',
                        'Resource': '*'
                    },
                    {
                        'Action': 'ec2:DetachVolume',
                        'Effect': 'Allow',
                        'Resource': '*'
                    },
                    {
                        'Action': 'kms:Decrypt',
                        'Effect': 'Allow',
                        'Resource': kms_key_arn
                    },
                    {
                        'Action': [
			    'ecr:GetAuthorizationToken',
			    'ecr:BatchCheckLayerAvailability',
			    'ecr:GetDownloadUrlForLayer',
			    'ecr:GetRepositoryPolicy',
			    'ecr:DescribeRepositories',
			    'ecr:ListImages',
			    'ecr:BatchGetImage'
                        ],
                        'Effect': 'Allow',
                        'Resource': '*'
                    }
                ],
                'Version': '2012-10-17'
            }
        )

        iam_role_worker = node_template.add_resource(iam.Role(
            'IamRoleWorker',
            AssumeRolePolicyDocument={
                'Statement': [
                    {
                        'Action': [
                            'sts:AssumeRole'
                        ],
                        'Effect': 'Allow',
                        'Principal': {
                            'Service': [
                                'ec2.amazonaws.com'
                            ]
                        }
                    }
                ],
                'Version': '2012-10-17'
            },
            Path='/',
            Policies=[
                iam_policy_worker
            ]
        ))

        iam_instance_profile_worker = node_template.add_resource(iam.InstanceProfile(
            'IamInstanceProfileWorker',
            Path='/',
            Roles=[Ref(iam_role_worker)]
        ))

        launch_config_worker = node_template.add_resource(autoscaling.LaunchConfiguration(
            'LaunchConfigWorker',
            BlockDeviceMappings=[
                {
                    'DeviceName': '/dev/xvda',
                    'Ebs': {'VolumeSize': 30}
                }
            ],
            IamInstanceProfile=Ref(iam_instance_profile_worker),
            ImageId=ami,
            InstanceType=self.jurisdiction.parent.configuration['worker_instance_type'],
            KeyName=self.jurisdiction.name,
            SecurityGroups=[Ref(security_group_worker)],
            UserData=self._generate_userdata('worker', kms_key_arn,
                                             0, load_balancers,
                                             cluster_ca, cluster_ca_key)
        ))

        rolling_update_policy_worker = policies.AutoScalingRollingUpdate(
            'RollingUpdatePolicyWorker',
            MaxBatchSize=1,
            MinInstancesInService=self.jurisdiction.parent.configuration['initial_workers'],
            PauseTime='PT5M'
        )

        auto_scale_worker_tags = {
                'Name': '{}_worker'.format(self.jurisdiction.name)
            }
        auto_scale_worker_tags.update(cluster_tags)

        auto_scale_worker = node_template.add_resource(autoscaling.AutoScalingGroup(
            'AutoScaleWorker',
            HealthCheckGracePeriod=600,
            HealthCheckType='EC2',
            LaunchConfigurationName=Ref(launch_config_worker),
            DesiredCapacity=self.jurisdiction.parent.configuration['initial_workers'],
            MaxSize=self.jurisdiction.parent.configuration['initial_workers'] * 2,
            MinSize=self.jurisdiction.parent.configuration['initial_workers'],
            VPCZoneIdentifier=[ImportValue('{}-subnet-{}'.format(self.jurisdiction.id, next(itertools.count()))) for cidr in self.jurisdiction.configuration['host_subnet_cidrs']],
            UpdatePolicy=rolling_update_policy_worker,
            Tags=autoscaling.Tags(**auto_scale_worker_tags)
        ))

        # controllers
        iam_policy_controller = iam.Policy(
            'IamPolicyController',
            PolicyName='root',
            PolicyDocument={
                'Statement': [
                    {
                        'Action': 'ec2:*',
                        'Effect': 'Allow',
                        'Resource': '*'
                    },
                    {
                        'Action': 'elasticloadbalancing:*',
                        'Effect': 'Allow',
                        'Resource': '*'
                    },
                    {
                        'Action': 'kms:Decrypt',
                        'Effect': 'Allow',
                        'Resource': kms_key_arn
                    }
                ],
                'Version': '2012-10-17'
            }
        )

        iam_role_controller = node_template.add_resource(iam.Role(
            'IamRoleController',
            AssumeRolePolicyDocument={
                'Statement': [
                    {
                        'Action': [
                            'sts:AssumeRole'
                        ],
                        'Effect': 'Allow',
                        'Principal': {
                            'Service': [
                                'ec2.amazonaws.com'
                            ]
                        }
                    }
                ],
                'Version': '2012-10-17'
            },
            Path='/',
            Policies=[
                iam_policy_controller
            ]
        ))

        iam_instance_profile_controller = node_template.add_resource(iam.InstanceProfile(
            'IamInstanceProfileController',
            Path='/',
            Roles=[Ref(iam_role_controller)]))

        controller_metric_dimensions = []
        controller_refs = []
        controller_count = 0
        for ip in self.jurisdiction.configuration['controller_ips']:
            controller_name = '{}_controller_{}'.format(self.jurisdiction.name,
                                                        controller_count)
            network_iface_controller = ec2.NetworkInterfaceProperty(
                'NetworkIfaceController',
                AssociatePublicIpAddress=False,
                DeleteOnTermination=True,
                DeviceIndex=0,
                GroupSet=[
                    Ref(security_group_controller)
                ],
                PrivateIpAddress=ip,
                SubnetId=ImportValue('{}-subnet-0'.format(self.jurisdiction.id))
            )

            instance_controller_tags = {
                    'Name': controller_name
                }
            instance_controller_tags.update(cluster_tags)

            instance_controller = node_template.add_resource(ec2.Instance(
                'InstanceController',
                BlockDeviceMappings=[
                    {
                        'DeviceName': '/dev/xvda',
                        'Ebs': {
                            'VolumeSize': 30
                        }
                    }
                ],
                IamInstanceProfile=Ref(iam_instance_profile_controller),
                ImageId=ami,
                InstanceType=self.jurisdiction.parent.configuration['controller_instance_type'],
                KeyName=self.jurisdiction.name,
                NetworkInterfaces=[
                    network_iface_controller
                ],
                UserData=self._generate_userdata('controller', kms_key_arn,
                                                 controller_count, load_balancers,
                                                 cluster_ca, cluster_ca_key),
                Tags=Tags(**instance_controller_tags)
            ))

            node_template.add_output(Output(
                'InstanceController{}output'.format(controller_count),
                Description='ID for controller instance with IP {}'.format(ip),
                Value=Ref(instance_controller),
                Export=Export('{}-instance-controller-{}'.format(self.jurisdiction.id,
                                                                 ip.replace('.', '-')))
            ))

            eip_controller = node_template.add_resource(ec2.EIP(
                'EipController',
                Domain='vpc',
                InstanceId=Ref(instance_controller)
            ))

            metric_dimension_controller = cloudwatch.MetricDimension(
                'MetricDimensionController',
                Name='controller_{}'.format(controller_count),
                Value=Ref(instance_controller)
            )

            controller_metric_dimensions.append(metric_dimension_controller)
            controller_refs.append(Ref(instance_controller))
            controller_count += 1

        etcd_refs = []
        etcd_count = 0
        if self.jurisdiction.parent.configuration['dedicated_etcd']:
            for ip in self.jurisdiction.parent.configuration['etcd_ips']:
                etcd_name = '{}_etcd_{}'.format(self.jurisdiction.name, etcd_count)

                network_iface_etcd = ec2.NetworkInterfaceProperty(
                    'NetworkIfaceEtcd',
                    AssociatePublicIpAddress=False,
                    DeleteOnTermination=True,
                    DeviceIndex=0,
                    GroupSet=[
                        Ref(security_group_etcd)
                    ],
                    PrivateIpAddress=ip,
                    SubnetId=ImportValue('{}-subnet-0'.format(self.jurisdiction.id))
                )

                instance_etcd_tags = {
                        'Name': etcd_name
                    }
                instance_etcd_tags.update(cluster_tags)

                instance_etcd = node_template.add_resource(ec2.Instance(
                    'InstanceEtcd',
                    BlockDeviceMappings=[
                        {
                            'DeviceName': '/dev/xvda',
                            'Ebs': {
                                'VolumeSize': 30
                            }
                        }
                    ],
                    IamInstanceProfile=Ref(iam_instance_profile_controller),
                    ImageId=ami,
                    InstanceType=self.jurisdiction.parent.configuration['etcd_instance_type'],
                    KeyName=self.jurisdiction.name,
                    NetworkInterfaces=[
                        network_iface_etcd
                    ],
                    UserData=self._generate_userdata('etcd', kms_key_arn,
                                                     etcd_count, load_balancers,
                                                     cluster_ca, cluster_ca_key),
                    Tags=Tags(**instance_etcd_tags)
                ))

                node_template.add_output(Output(
                    'InstanceEtcd{}Output'.format(etcd_count),
                    Description='ID for etcd instance with IP {}'.format(ip),
                    Value=Ref(instance_etcd),
                    Export=Export('{}-instance-etcd-{}'.format(self.jurisdiction.id,
                                                               ip.replace('.', '-')))
                ))

                eip_etcd = node_template.add_resource(ec2.EIP(
                    'EipEtcd',
                    Domain='vpc',
                    InstanceId=Ref(instance_etcd)
                ))

                metric_dimension_etcd = cloudwatch.MetricDimension(
                    'MetricDimensionEtcd',
                    Name='etcd_{}'.format(etcd_count),
                    Value=Ref(instance_etcd)
                )

                controller_metric_dimensions.append(metric_dimension_etcd)
                etcd_refs.append(Ref(instance_etcd))
                etcd_count += 1

        alarm_controller_recover = node_template.add_resource(cloudwatch.Alarm(
            'AlarmControllerRecover',
            AlarmActions=[
                'arn:aws:automate:{}:ec2:recover'.format(self.region)
            ],
            AlarmDescription='Trigger a recovery when system check fails for 5 consecutive minutes',
            ComparisonOperator='GreaterThanThreshold',
            Dimensions=controller_metric_dimensions,
            EvaluationPeriods='5',
            MetricName='StatusCheckFailed_System',
            Namespace='AWS/EC2',
            Period='60',
            Statistic='Minimum',
            Threshold='0'
        ))

        node_template_content = node_template.to_json()

        stack_name = 'ClusterNodes{}'.format(str(self.jurisdiction.id).zfill(4))

        cf_client = boto3.client('cloudformation', region_name=self.region)
        cf_stack = cf_client.create_stack(StackName=stack_name,
                                          TemplateBody=node_template_content,
                                          Capabilities=['CAPABILITY_IAM'])

        return {
            'cloudformation_stack': {
                'nodes': {
                    'stack_id': cf_stack['StackId'],
                    'status': None
                }
            },
            'ec2_key_pair': ec2_key_pair['KeyName'],
            'kms_key': kms_key_arn,
            'load_balancers': load_balancers
        }

    def register_elb_instances(self):

        # collect required export names
        cf_client = boto3.client('cloudformation', region_name=self.region)

        controller_elb_name = '{}-elb-controller'.format(self.jurisdiction.id)
        controller_sg_name = '{}-security-group-controller'.format(self.jurisdiction.id)
        required_exports = {
            controller_elb_name: None,
            controller_sg_name: None
        }
        for ip in self.jurisdiction.configuration['controller_ips']:
            instance_key = '{}-instance-controller-{}'.format(self.jurisdiction.id,
                                                              ip.replace('.', '-'))
            required_exports[instance_key] = None

        if self.jurisdiction.parent.configuration['dedicated_etcd']:
            etcd_elb_name = '{}-elb-etcd'.format(self.jurisdiction.id)
            etcd_sg_name = '{}-security-group-etcd'.format(self.jurisdiction.id)
            etcd_required_exports = {
                etcd_elb_name: None,
                etcd_sg_name: None
            }
            for ip in self.jurisdiction.configuration['etcd_ips']:
                instance_key = '{}-instance-etcd-{}'.format(self.jurisdiction.id,
                                                            ip.replace('.', '-'))
                etcd_required_exports[instance_key] = None
            required_exports.update(etcd_required_exports)

        # get export values from cloudformation
        complete = False
        next_token = None
        while not complete:
            if not next_token:
                cf_exports = cf_client.list_exports()
            else:
                cf_exports = cf_client.list_exports(NextToken=next_token)
            next_token = cf_exports.get('NextToken')
            for existing_export in cf_exports['Exports']:
                for required_export in required_exports.keys():
                    if existing_export['Name'] == required_export:
                        required_exports[required_export] = existing_export['Value']
                        break
                # stop looking if all required exports collected
                all_collected = True
                for e in required_exports:
                    if not required_exports[e]:
                        all_collected = False
                if all_collected:
                    complete = True
                    break
            if not next_token:
                complete = True

        # register instances with ELBs
        elb_client = boto3.client('elb', region_name=self.region)

        controller_instances = []
        for export in required_exports:
            if 'instance-controller' in export:
                controller_instances.append({'InstanceId': required_exports[export]})
        elb_client.register_instances_with_load_balancer(
                        LoadBalancerName=required_exports[controller_elb_name],
                        Instances=controller_instances)

        if self.jurisdiction.parent.configuration['dedicated_etcd']:
            etcd_instances = []
            for export in required_exports:
                if 'instance-etcd' in export:
                    etcd_instances.append({'InstanceId': required_exports[export]})
            elb_client.register_instances_with_load_balancer(
                            LoadBalancerName=required_exports[etcd_elb_name],
                            Instances=etcd_instances)

    def provision_cluster(self):

        assets = self.provision_cluster_network()
        monitor_cloudformation_stack.delay(self.jurisdiction.id,
                                           interim_operation=True,
                                           stack_key='network')
        monitor_cluster_network.delay(self.jurisdiction.id)
        monitor_cluster_nodes.delay(self.jurisdiction.id)

        return assets

    def decommission_jurisdiction(self):

        cf_client = boto3.client('cloudformation', region_name=self.region)

        if self.jurisdiction.jurisdiction_type.name == 'cluster':
            ec2_client = boto3.client('ec2', region_name=self.region)
            ec2_client.delete_key_pair(
                KeyName=self.jurisdiction.assets['ec2_key_pair'])

            kms_client = boto3.client('kms', region_name=self.region)
            kms_client.delete_alias(
                    AliasName='alias/{}'.format(self.jurisdiction.name))
            kms_client.schedule_key_deletion(
                    KeyId=self.jurisdiction.assets['kms_key'])

            net_stack_id = self.jurisdiction.assets['cloudformation_stack']['network']['stack_id']
            nodes_stack_id = self.jurisdiction.assets['cloudformation_stack']['nodes']['stack_id']

            cf_client.delete_stack(StackName=nodes_stack_id)

            monitor_decommission.delay(self.jurisdiction.id,
                                       nodes_stack_id, net_stack_id)

        else:
            if self.jurisdiction.jurisdiction_type.name == 'control_group':
                s3_client = boto3.client('s3', region_name=self.region)
                objects = s3_client.list_objects_v2(
                                Bucket=self.jurisdiction.assets['s3_bucket'])
                delete = []
                for obj in objects['Contents']:
                    delete.append({'Key': obj['Key']})
                s3_client.delete_objects(
                            Bucket=self.jurisdiction.assets['s3_bucket'],
                            Delete={
                                'Objects': delete
                            })

            cf_client.delete_stack(
                StackName=self.jurisdiction.assets['cloudformation_stack']['stack_id'])

        return {}

