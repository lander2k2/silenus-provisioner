import os
from provisioner.database import Database

db = Database(os.environ.get('SILENUS_PROVISIONER_DB_HOST'),
              os.environ.get('SILENUS_PROVISIONER_DB_NAME'),
              os.environ.get('SILENUS_PROVISIONER_DB_USER'),
              os.environ.get('SILENUS_PROVISIONER_DB_PWD'))

