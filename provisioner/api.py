import os

import falcon
import hug
import sqlalchemy
from sqlalchemy.orm.exc import NoResultFound

from provisioner import db
from provisioner.database import Database
from provisioner.models import JurisdictionType, Jurisdiction, ConfigurationTemplate
from provisioner.platforms import AWS
from provisioner.tasks import monitor_cloudformation_stack


def get_objects(obj, obj_id, session):
    """Retrieve objects from database"""

    if obj_id:
        try:
            query = session.query(obj).filter_by(id=obj_id).one()
        except NoResultFound:
            msg = "{0} with id {1} does not exist".format(obj.__name__, obj_id)
            raise falcon.HTTPBadRequest('Bad request', msg)
    else:
        query = session.query(obj).all()

    return query


def get_object_attributes(obj, obj_id, session):
    """Retrieve the attributes of an object"""

    if obj_id:
        objects = [get_objects(obj, obj_id, session)]
    else:
        objects = get_objects(obj, obj_id, session)

    object_attributes = []
    for o in objects:
        object_attributes.append(o.__attributes__())

    return object_attributes


@hug.get('/get_jurisdiction_types/', version=1)
def get_jurisdiction_types(jurisdiction_type_id: hug.types.number=None):
    """
    A jurisdiciton is a group of instructure resources that have a particular
    extent of operation and control. Jurisdictions of different types may be
    nested within one another with nested jurisdictions have narrower extent
    of operation and control.

    There are three default jurisdiction types:
        * Control Group - the widest scope of operation and control. It includes
          infrastructure used to manage multiple tiers.
        * Tier - a narrower scope of infrastructure. A tier represents a level
          of criticality of workload. For example, a  production tier's uptime
          is highly critical and tightly controlled as compared to a development
          tier. There may be zero or more tiers in a control group.
        * Cluster - the narrowest scope of operation and control. It represents
          of servers running containerized workloads using a container orchestration
          tool.  There may be zero or more clusters per tier.

    It is possible to create and define more jurisdiction types in addition
    to the defaults listed above. This handler returns jurisdiction types currently
    in the system.
    """
    with db.transaction() as session:
        jt_attrs = get_object_attributes(JurisdictionType,
                                         jurisdiction_type_id,
                                         session)

    return {'data': jt_attrs}


@hug.get('/get_configuration_templates/', version=1)
def get_configuration_templates(configuration_template_id: hug.types.number=None):
    """
    A configuration template defines the default configuration values for a
    jurisdiction type.

    This handler returns the configuration templates currently in the system.
    """
    with db.transaction() as session:
        ct_attrs = get_object_attributes(ConfigurationTemplate,
                                         configuration_template_id,
                                         session)

    return {'data': ct_attrs}


@hug.get('/get_jurisdictions/', version=1)
def get_jurisdictions(jurisdiction_id: hug.types.number=None):
    """
    A jurisdiciton is a group of instructure resources that have a particular
    extent of operation and control. Jurisdictions of different types may be
    nested within one another with nested jurisdictions have narrower extent
    of operation and control.

    This handler returns the jurisdictions currently in the system.
    """
    with db.transaction() as session:
        j_attrs = get_object_attributes(Jurisdiction,
                                        jurisdiction_id,
                                        session)

    return {'data': j_attrs}


@hug.post('/create_jurisdiction/', version=1)
def create_jurisdiction(jurisdiction_name: hug.types.text,
                        jurisdiction_type_id: hug.types.number,
                        configuration_template_id: hug.types.number,
                        parent_id: hug.types.number=None):
    """
    A jurisdiciton is a group of instructure resources that have a particular
    extent of operation and control. Jurisdictions of different types may be
    nested within one another with nested jurisdictions have narrower extent
    of operation and control.

    This handler allows the user to create a jurisdiction by providing a
    jurisdiction type ID, a configuration template ID and, optionally, a
    parent ID if the jurisdiction is nested within another jurisdiction.

    Creating a jurisdiction creates a new database records which defines the
    jurisdiction's attributes but does not actually provision any infrastructure.

    After creation, default configuration values may be modified and then the
    jurisdiction may be provisioned which actually stands up the infrastructure
    required.
    """
    with db.transaction() as session:
        name_exists = session.query(sqlalchemy.sql.exists().where(
                            Jurisdiction.name == jurisdiction_name)).scalar()
        if name_exists:
            msg = "Jurisdiction '{}' already exists".format(jurisdiction_name)
            raise falcon.HTTPBadRequest('Bad request', msg)

        jurisdiction_type = get_objects(JurisdictionType,
                                        jurisdiction_type_id,
                                        session)
        configuration_template = get_objects(ConfigurationTemplate,
                                             configuration_template_id,
                                             session)
        if configuration_template.jurisdiction_type_id != jurisdiction_type.id:
            msg = """
                ConfigurationTemplate with id {0} is not a template for
                JurisdictionType '{1}'
            """.format(configuration_template_id, jurisdiction_type.name)
            raise falcon.HTTPBadRequest('Bad request', ' '.join(msg.split()))
        if parent_id:
            parent = get_objects(Jurisdiction, parent_id, session)

        new_jurisdiction = Jurisdiction(name=jurisdiction_name,
                                        jurisdiction_type_id=jurisdiction_type.id,
                                        configuration=configuration_template.configuration,
                                        parent_id=parent_id)
        session.add(new_jurisdiction)

    with db.transaction() as session:
        jurisdiction = session.query(Jurisdiction).filter_by(name=jurisdiction_name)[0]
        data = jurisdiction.__attributes__()

    return {'data': data}


@hug.put('/edit_jurisdiction/', version=1)
def edit_jurisdiction(jurisdiction_id: hug.types.number, **edits):
    """
    A jurisdiciton is a group of instructure resources that have a particular
    extent of operation and control. Jurisdictions of different types may be
    nested within one another with nested jurisdictions have narrower extent
    of operation and control.

    This handler allows the user to edit the configuration values of a
    jurisdiction after it has been created and before it has been provisioned.
    """
    # need to change metadata key - sqlalchemy uses metadata as table attribute
    if 'metadata' in edits:
        edits['jurisdiction_metadata'] = edits.pop('metadata')

    with db.transaction() as session:
        jurisdiction = get_objects(Jurisdiction, jurisdiction_id, session)

        for attr in edits:
            if attr in ('name', 'jurisdiction_metadata', 'configuration'):
                jurisdiction.__setattr__(attr, edits[attr])
            else:
                msg = '{} is not a Jurisdiction attribute that can be edited'.format(attr)
                raise falcon.HTTPBadRequest('Bad request', msg)

    with db.transaction() as session:
        jurisdiction = session.query(Jurisdiction).filter_by(id=jurisdiction_id)[0]
        data = jurisdiction.__attributes__()

    return {'data': data}


@hug.put('/provision_jurisdiction/', version=1)
def provision_jurisdiction(jurisdiction_id: hug.types.number):
    """
    A jurisdiciton is a group of instructure resources that have a particular
    extent of operation and control. Jurisdictions of different types may be
    nested within one another with nested jurisdictions have narrower extent
    of operation and control.

    This handler provisions the infrastructure after a jurisdiction has been
    created and edited as needed.
    """
    with db.transaction() as session:
        j = get_objects(Jurisdiction, jurisdiction_id, session)

        if j.active == True:
            msg = 'Jurisdiction with id {} is already active'.format(jurisdiction_id)
            raise falcon.HTTPBadRequest('Bad request', msg)

        jurisdiction_type = j.jurisdiction_type.name

        if jurisdiction_type == 'control_group':
            if j.configuration['platform'] == 'amazon_web_services':
                platform = AWS(j)
                assets = platform.provision_control_group()
                monitor_cloudformation_stack.delay(j.id)
            else:
                msg = 'Platform {} not supported'.format(j.configuration['platform'])
                raise falcon.HTTPBadRequest('Bad request', msg)
        elif jurisdiction_type == 'tier':
            control_group = j.parent
            if not control_group.active:
                msg = 'Control group {} is inactive. Tier must be provisioned in active control group'.format(control_group.name)
                raise falcon.HTTPBadRequest('Bad request', msg)
            if control_group.configuration['platform'] == 'amazon_web_services':
                platform = AWS(j)
                assets = platform.provision_tier()
                monitor_cloudformation_stack.delay(j.id)
            else:
                msg = 'Platform {} not supported'.format(j.configuration['platform'])
                raise falcon.HTTPBadRequest('Bad request', msg)
        elif jurisdiction_type == 'cluster':
            tier = j.parent
            control_group = j.parent.parent
            if not tier.active:
                msg = 'Tier {} is inactive. Tier must be provisioned in active control group'.format(tier.name)
                raise falcon.HTTPBadRequest('Bad request', msg)
            if control_group.configuration['platform'] == 'amazon_web_services':
                platform = AWS(j)
                assets = platform.provision_cluster()
            else:
                msg = 'Platform {} not supported'.format(j.configuration['platform'])
                raise falcon.HTTPBadRequest('Bad request', msg)
        else:
            msg = 'Jurisdiction type {} not supported'.format(jurisdiction_type)
            raise falcon.HTTPBadRequests('Bad request', msg)

        j.assets = assets

        data = j.__attributes__()

    return {'data': data}


@hug.put('/decommission_jurisdiction/', version=1)
def decommission_jurisdiction(jurisdiction_id: hug.types.number):
    """
    A jurisdiciton is a group of instructure resources that have a particular
    extent of operation and control. Jurisdictions of different types may be
    nested within one another with nested jurisdictions have narrower extent
    of operation and control.

    This handler removes the jurisdiction's infrastructure but does not delete
    the jurisdiction from the system. A jurisdiction may be re-provisioned
    after being decommissioned.
    """
    with db.transaction() as session:
        j = get_objects(Jurisdiction, jurisdiction_id, session)

        if j.active == False:
            msg = 'Jurisdiction with id {} not active'.format(jurisdiction_id)
            raise falcon.HTTPBadRequest('Bad request', msg)

        jurisdiction_type = j.jurisdiction_type.name

        if jurisdiction_type == 'control_group':
            for child in j.children:
                if child.active == True:
                    msg = 'Child jurisdiction with id {} is still active'.format(child.id)
                    raise falcon.HTTPBadRequest('Bad request', msg)

            if j.configuration['platform'] == 'amazon_web_services':
                platform = AWS(j)
                assets = platform.decommission_jurisdiction()
            else:
                msg = 'Platform {} not supported'.format(j.platform)
                raise falcon.HTTPBadRequest('Bad request', msg)
        elif jurisdiction_type == 'tier':
            for child in j.children:
                if child.active == True:
                    msg = 'Child jurisdiction with id {} is still active'.format(child.id)
                    raise falcon.HTTPBadRequest('Bad request', msg)
            control_group = j.parent
            if control_group.configuration['platform'] == 'amazon_web_services':
                platform = AWS(j)
                assets = platform.decommission_jurisdiction()
            else:
                msg = 'Platform {} not supported'.format(j.platform)
                raise falcon.HTTPBadRequest('Bad request', msg)
        elif jurisdiction_type == 'cluster':
            control_group = j.parent.parent
            if control_group.configuration['platform'] == 'amazon_web_services':
                platform = AWS(j)
                assets = platform.decommission_jurisdiction()
            else:
                msg = 'Platform {} not supported'.format(j.platform)
                raise falcon.HTTPBadRequest('Bad request', msg)
        else:
            msg = 'Jurisdiction type {} not supported'.format(jurisdiction_type)
            raise falcon.HTTPBadRequests('Bad request', msg)

        j.active = False
        j.assets = assets

        data = j.__attributes__()

    return {'data': data}

