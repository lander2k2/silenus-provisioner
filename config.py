import os

DATABASE_HOST = os.environ.get('DATABASE_HOST', 'localhost')
DATABASE_NAME = os.environ.get('DATABASE_NAME', 'silenus_provisioner')
DATABASE_USER = os.environ.get('DATABASE_USER', 'silenus')
DATABASE_PWD = os.environ.get('DATABASE_PWD')

