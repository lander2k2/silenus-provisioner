from contextlib import contextmanager

import sqlalchemy

import config
import models
from models import JurisdictionType, ConfigurationTemplate


engine = sqlalchemy.create_engine(
                'postgresql://{0}:{1}@{2}/{3}'.format(config.DATABASE_USER,
                                                      config.DATABASE_PWD,
                                                      config.DATABASE_HOST,
                                                      config.DATABASE_NAME))


def create():
    engine.execute('CREATE EXTENSION hstore')
    models.Base.metadata.create_all(engine)


def connect():
    Session = sqlalchemy.orm.sessionmaker(bind=engine)
    return Session()


@contextmanager
def transaction():
    session = connect()
    try:
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()


def load_defaults():
    """
    Adds default jurisdiction types:
      * control_group
      * tier
      * cluster
    Adds default configuration for each of the three jurisdiction types
    """
    # jurisdiction types
    with trandaction() as session:
        control_group_descr = """
        A control group defines a group of infrastructural resources that are usually
        in a particular data center or geographic zone. A control group possesses it's own
        private newtwork space and will usually contain several tiers.
        """
        control_group_type = JurisdictionType(name='control_group',
                                              description=' '.join(control_group_descr.split()))
        session.add(control_group_type)

    with transaction() as session:
        tier_descr = """
        A tier is assigned to a control group and represents a level of criticality
        for the workloads running in it. Common tiers are Development, Staging and Production.
        """
        tier_type = JurisdictionType(name='tier',
                                     description=' '.join(tier_descr.split()),
                                     parent_id = control_group_type.id)
        session.add(tier_type)


    with transaction() as session:
        cluster_descr = """
        A cluster lives in a tier and hosts containerized workloads. The cluster's 
        workloads are controlled by a container orchestration tool.
        """
        cluster_type = JurisdictionType(name='cluster',
                                        description=' '.join(cluster_descr.split()),
                                        parent_id = tier_type.id)
        session.add(cluster_type)

    # configurations

    with transaction() as session:
        control_group_config = {
            'platform': 'amazon_web_services',
            'orchestrator': 'kubernetes',
            'clusters_cidr': '10.0.0.0/8'
        }
        control_group_config = ConfigurationTemplate(name='default_control_group',
                                                     configuration=control_group_config,
                                                     default=True,
                                                     jurisdiction_type_id=control_group_type.id)
        session.add(control_group_config)

        tier_config = {
            'controllers': 1,
            'workers': 2,
            'dedicated_etcd': False,
            'cidr': '10.0.0.0/10'
        }
        tier_config = ConfigurationTemplate(name='dev_tier',
                                            configuration=tier_config,
                                            default=True,
                                            jurisdiction_type_id=tier_type.id)
        session.add(tier_config)

        cluster_config = {
            'host_cidr': '10.0.0.0/16',
            'host_subnet_cidrs': [
                '10.0.0.0/20',
                '10.0.16.0/20'
            ],
            'pod_cidr': '10.1.0.0/16',
            'service_cidr': '10.2.0.0/24',
            'controller_ips': ['10.0.0.50'],
            'etcd_ips': ['10.0.0.50'],
            'kubernetes_api_ip': '10.2.0.1',
            'cluster_dns_ip': '10.2.0.10'
        }
        cluster_config = ConfigurationTemplate(name='dev01_cluster',
                                               configuration=cluster_config,
                                               default=True,
                                               jurisdiction_type_id=cluster_type.id)
        session.add(cluster_config)
    
