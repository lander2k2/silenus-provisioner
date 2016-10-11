from models import JurisdictionType, ConfigurationTemplate


PROVISIONER_DEFAULTS = {
    'jurisdiction_types': [
        {'id': 1,
         'name': 'control_group',
         'description': 'A control group defines a group of infrastructural resources that are usually in a particular data center or geographic zone. A control group possesses its own private newtwork space and will usually contain several tiers.',
         'parent_id': None},
        {'id': 2,
         'name': 'tier',
         'description': 'A tier is assigned to a control group and represents a level of criticality for the workloads running in it. Common tiers are Development, Staging and Production.',
         'parent_id': 1},
        {'id': 3,
         'name': 'cluster',
         'description': 'A cluster lives in a tier and hosts containerized workloads. The clusters workloads are controlled by a container orchestration tool.',
         'parent_id': 2}
    ],
    'configuration_templates': [
        {'id': 1,
         'name': 'default_control_group',
         'configuration': {'clusters_cidr': '10.0.0.0/8',
                           'orchestrator': 'kubernetes',
                           'platform': 'amazon_web_services'},
         'default': True,
         'jurisdiction_type_id': 1},
        {'id': 2,
         'name': 'dev_tier',
         'configuration': {'cidr': '10.0.0.0/10',
                           'controllers': 1,
                           'dedicated_etcd': False,
                           'workers': 2},
         'default': True,
         'jurisdiction_type_id': 2},
        {'id': 3,
         'name': 'dev01_cluster',
         'configuration': {'cluster_dns_ip': '10.2.0.10',
                           'controller_ips': ['10.0.0.50'],
                           'etcd_ips': ['10.0.0.50'],
                           'host_cidr': '10.0.0.0/16',
                           'host_subnet_cidrs': ['10.0.0.0/20', '10.0.16.0/20'],
                           'kubernetes_api_ip': '10.2.0.1',
                           'pod_cidr': '10.1.0.0/16',
                           'service_cidr': '10.2.0.0/24'},
         'default': True,
         'jurisdiction_type_id': 3}
    ]
}


def load_defaults(db):
    """
    Adds default jurisdiction types:
      * control_group
      * tier
      * cluster
    Adds default configuration for each of the three jurisdiction types
    """
    pd = PROVISIONER_DEFAULTS

    # jurisdiction types
    with db.transaction() as session:
        session.add(JurisdictionType(name=pd['jurisdiction_types'][0]['name'],
                                     description=pd['jurisdiction_types'][0]['description']))

    with db.transaction() as session:
        session.add(JurisdictionType(name=pd['jurisdiction_types'][1]['name'],
                                     description=pd['jurisdiction_types'][1]['description'],
                                     parent_id=pd['jurisdiction_types'][1]['parent_id']))

    with db.transaction() as session:
        session.add(JurisdictionType(name=pd['jurisdiction_types'][2]['name'],
                                     description=pd['jurisdiction_types'][2]['description'],
                                     parent_id=pd['jurisdiction_types'][2]['parent_id']))

    # configurations
    with db.transaction() as session:
        session.add(ConfigurationTemplate(
                    name=pd['configuration_templates'][0]['name'],
                    configuration=pd['configuration_templates'][0]['configuration'],
                    default=pd['configuration_templates'][0]['default'],
                    jurisdiction_type_id=pd['configuration_templates'][0]['jurisdiction_type_id']))

        session.add(ConfigurationTemplate(
                    name=pd['configuration_templates'][1]['name'],
                    configuration=pd['configuration_templates'][1]['configuration'],
                    default=pd['configuration_templates'][1]['default'],
                    jurisdiction_type_id=pd['configuration_templates'][1]['jurisdiction_type_id']))

        session.add(ConfigurationTemplate(
                    name=pd['configuration_templates'][2]['name'],
                    configuration=pd['configuration_templates'][2]['configuration'],
                    default=pd['configuration_templates'][2]['default'],
                    jurisdiction_type_id=pd['configuration_templates'][2]['jurisdiction_type_id']))
