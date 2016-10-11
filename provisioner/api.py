import os

import falcon
import hug
import sqlalchemy

from provisioner import db
from models import JurisdictionType, Jurisdiction, ConfigurationTemplate


def get_objects(obj, obj_id, session):

    if obj_id:
        query = session.query(obj).filter_by(id=obj_id)
        if query.count() == 0:
            msg = "{0} with id {1} does not exist".format(obj.__name__, obj_id)
            raise falcon.HTTPBadRequest('Bad request', msg)
    else:
        query = session.query(obj).all()

    return query


def get_object_attributes(obj, obj_id, session):

    objects = get_objects(obj, obj_id, session)

    object_attributes = []
    for o in objects:
        object_attributes.append(o.__attributes__())

    return object_attributes


@hug.get('/get_jurisdiction_types/', version=1)
def get_jurisdiction_types(jurisdiction_type_id: hug.types.number=None):

    with db.transaction() as session:
        jt_attrs = get_object_attributes(JurisdictionType,
                                         jurisdiction_type_id,
                                         session)

    return jt_attrs


@hug.get('/get_configuration_templates/', version=1)
def get_configuration_templates(configuration_template_id: hug.types.number=None):

    with db.transaction() as session:
        ct_attrs = get_object_attributes(ConfigurationTemplate,
                                         configuration_template_id,
                                         session)

    return ct_attrs


@hug.get('/get_jurisdictions/', version=1)
def get_jurisdictions(jurisdiction_id: hug.types.number=None):

    with db.transaction() as session:
        j_attrs = get_object_attributes(Jurisdiction,
                                        jurisdiction_id,
                                        session)

    return j_attrs


@hug.post('/create_jurisdiction/', version=1)
def create_jurisdiction(jurisdiction_name: hug.types.text,
                        jurisdiction_type_id: hug.types.number,
                        configuration_template_id: hug.types.number,
                        parent_id: hug.types.number=None):

    with db.transaction() as session:
        name_exists = session.query(sqlalchemy.sql.exists().where(
                            Jurisdiction.name == jurisdiction_name)).scalar()
        if name_exists:
            msg = "Jurisdiction '{}' already exists".format(jurisdiction_name)
            raise falcon.HTTPBadRequest('Bad request', msg)

        jurisdiction_type = get_objects(JurisdictionType,
                                        jurisdiction_type_id,
                                        session)[0]
        configuration_template = get_objects(ConfigurationTemplate,
                                             configuration_template_id,
                                             session)[0]
        if configuration_template.jurisdiction_type_id != jurisdiction_type.id:
            msg = """
                ConfigurationTemplate with id {0} is not a template for
                JurisdictionType '{1}'
            """.format(configuration_template_id, jurisdiction_type.name)
            raise falcon.HTTPBadRequest('Bad request', ' '.join(msg.split()))
        if parent_id:
            parent = get_objects(Jurisdiction, parent_id, session)[0]

        new_jurisdiction = Jurisdiction(name=jurisdiction_name,
                                        jurisdiction_type_id=jurisdiction_type.id,
                                        configuration=configuration_template.configuration,
                                        parent_id=parent_id)
        session.add(new_jurisdiction)

    with db.transaction() as session:
        jurisdiction = session.query(Jurisdiction).filter_by(name=jurisdiction_name)[0]
        response = jurisdiction.__attributes__()

    return response


@hug.put('/edit_jurisdiction/', version=1)
def edit_jurisdiction(jurisdiction_id: hug.types.number, **edits):

    # need to change metadata key - sqlalchemy uses metadata as table attribute
    if 'metadata' in edits:
        edits['jurisdiction_metadata'] = edits.pop('metadata')

    with db.transaction() as session:
        jurisdiction = get_objects(Jurisdiction, jurisdiction_id, session)[0]

        for attr in edits:
            if attr in ('name', 'jurisdiction_metadata', 'configuration'):
                jurisdiction.__setattr__(attr, edits[attr])
            else:
                msg = '{} is not a Jurisdiction attribute that can be edited'.format(attr)
                raise falcon.HTTPBadRequest('Bad request', msg)

    with db.transaction() as session:
        jurisdiction = session.query(Jurisdiction).filter_by(id=jurisdiction_id)[0]
        response = jurisdiction.__attributes__()

    return response
