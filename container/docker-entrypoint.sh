#!/bin/bash

# give the database and message broker time to start up
/bin/sleep 5

echo "Preparing provisioner database..."
/usr/local/bin/python /var/www/provisioner/database.py

echo "Starting supervisor..."
/usr/local/bin/supervisord -c /etc/supervisor.d/supervisord.conf -n

exit 0

