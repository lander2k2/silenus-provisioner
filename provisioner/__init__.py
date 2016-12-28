import os
from provisioner.database import Database

db = Database(os.environ.get('DB_HOST'),
              os.environ.get('POSTGRES_DB'),
              os.environ.get('POSTGRES_USER'),
              os.environ.get('POSTGRES_PASSWORD'))

