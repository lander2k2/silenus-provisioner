#!/usr/bin/env python
import os
from contextlib import contextmanager
from subprocess import call

import sqlalchemy

import defaults
import models


class Database(object):
    def __init__(self, host, name, user, pwd):
        self.name = name
        self.engine = sqlalchemy.create_engine(
                        'postgresql://{0}:{1}@{2}/{3}'.format(user, pwd, host, name))
        self.Session = sqlalchemy.orm.sessionmaker(bind=self.engine)

    def create(self):
        call(['createdb', self.name])
        self.engine.execute('CREATE EXTENSION hstore')
        models.Base.metadata.create_all(self.engine)

    @contextmanager
    def transaction(self):
        session = self.Session()
        try:
            yield session
            session.commit()
        except:
            session.rollback()
            raise
        finally:
            session.close()


if __name__ == '__main__':
    db = Database(os.environ.get('SILENUS_PROVISIONER_DB_HOST'),
                  os.environ.get('SILENUS_PROVISIONER_DB_NAME'),
                  os.environ.get('SILENUS_PROVISIONER_DB_USER'),
                  os.environ.get('SILENUS_PROVISIONER_DB_PWD'))
    db.create()
    defaults.load_defaults(db)

