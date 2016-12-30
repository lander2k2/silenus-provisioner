#!/usr/bin/env python
import os
from contextlib import contextmanager
from subprocess import call

import psycopg2
import sqlalchemy

from provisioner import defaults
from provisioner import models


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
    db_host = os.environ.get('DB_HOST')
    db_name = os.environ.get('POSTGRES_DB')
    db_user = os.environ.get('POSTGRES_USER')
    db_pwd = os.environ.get('POSTGRES_PASSWORD')

    try:
        psycopg2.connect(host=db_host, database=db_name, user=db_user, password=db_pwd)
        exit('Database already exists')
    except psycopg2.OperationalError as e:
        err_msg = 'database "{}" does not exist'.format(db_name)
        if err_msg in str(e):
            db = Database(db_host, db_name, db_user, db_pwd)
            db.create()
            defaults.load_defaults(db)
        else:
            raise

