import datetime

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Boolean
from sqlalchemy.orm import relationship, backref
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSONB, HSTORE


Base = declarative_base()


class JurisdictionType(Base):
    """
    JurisdictionType allows for the definition and description of standard types
    of Jurisdiction objects. The JurisdictionType objects define the hierarchy
    that derived Jurisdiction objects will use.
    """
    __tablename__ = 'jurisdiction_type'

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    parent_id   = Column(Integer, ForeignKey('jurisdiction_type.id'), default=None)

    jurisdiction_type = relationship('JurisdictionType',
                                     backref=backref('child_jurisdiction_types', remote_side=[id]),
                                     foreign_keys=parent_id)

    def __attributes__(self):
        return {
            'id':          self.id,
            'name':        self.name,
            'description': self.description,
            'parent_id':   self.parent_id
        }


class ConfigurationTemplate(Base):
    """
    A ConfigurationTemplate allows for the definition of standard configurations
    for Jurisdictions.  ConfigurationTemplate objects are assigned to particular
    JurisdictionType objects and Jurisdiction objects that are of that type can
    have the standard configurations assigned when instantiated.
    """
    __tablename__ = 'configuration_template'

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    name                 = Column(Text, nullable=False)
    configuration        = Column(JSONB, nullable=False)
    default              = Column(Boolean, default=False)
    jurisdiction_type_id = Column(Integer, ForeignKey('jurisdiction_type.id'),
                                     default=None)

    jurisdiction_type = relationship('JurisdictionType', backref='configurations',
                                     foreign_keys=jurisdiction_type_id)

    unique_default = UniqueConstraint(default, jurisdiction_type_id)

    def __attributes__(self):
        return {
            'id':                   self.id,
            'name':                 self.name,
            'configuration':        self.configuration,
            'default':              self.default,
            'jurisdiction_type_id': self.jurisdiction_type_id
        }


class UserdataTemplate(Base):
    """
    A jinja2 template for generating node userdata cloud-config files.
    """
    __tablename__ = 'userdata_template'

    id      = Column(Integer, primary_key=True, autoincrement=True)
    name    = Column(Text, nullable=False, unique=True)
    role    = Column(Text, nullable=False)
    content = Column(Text, nullable=False)


class Jurisdiction(Base):
    """
    A Jurisdiction object represents a scope of authority for a group of
    infrastrural resources. Jurisdiction objects can be nested within other
    Jurisdictions of a different JurisdictionType.
    """
    __tablename__ = 'jurisdiction'

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    name                  = Column(Text, nullable=False, unique=True)
    created_on            = Column(DateTime(timezone=True), default=datetime.datetime.utcnow())
    active                = Column(Boolean, default=False)
    configuration         = Column(JSONB, nullable=False)
    assets                = Column(JSONB)
    jurisdiction_metadata = Column(HSTORE)
    jurisdiction_type_id  = Column(Integer, ForeignKey('jurisdiction_type.id'),
                                   nullable=False)
    parent_id             = Column(Integer, ForeignKey('jurisdiction.id'), default=None)
    #userdata_template_id  = Column(Integer, ForeignKey('userdata_template.id'), default=None)

    jurisdiction_type = relationship('JurisdictionType', backref='jurisdictions',
                                     foreign_keys=jurisdiction_type_id)
    children          = relationship('Jurisdiction',
                                     backref=backref('parent', remote_side=[id]))
    #userdata_template = relationship('UserdataTemplate', backref='jurisdictions',
    #                                 foreign_keys=userdata_template_id)

    def __attributes__(self):
        return {
            'id':                   self.id,
            'name':                 self.name,
            'created_on':           self.created_on,
            'active':               self.active,
            'assets':               self.assets,
            'configuration':        self.configuration,
            'metadata':             self.jurisdiction_metadata,
            'jurisdiction_type_id': self.jurisdiction_type_id,
            'parent_id':            self.parent_id
        }

