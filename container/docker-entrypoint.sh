#!/bin/bash

USAGE="Usage: docker-entrypoint.sh <api|worker>"

if [ "$1" == "" ]; then
    echo "No argument provided."
    echo $USAGE
    exit 1
elif [ "$1" == "api" ]; then
    # give the database and message broker containers time to fire up
    /bin/sleep 5
    echo "Preparing provisioner database..."
    su provisioner -c "/usr/local/bin/python /var/www/provisioner/database.py"
    echo "Starting nginx and gunicorn..."
    /usr/local/bin/supervisord -c /etc/supervisor.d/api-supervisord.conf -n
    exit 0
elif [ "$1" == "worker" ]; then
    echo "Starting celery worker..."
    /usr/local/bin/supervisord -c /etc/supervisor.d/worker-supervisord.conf -n
    exit 0
else
    echo "Invalid argument provided."
    echo $USAGE
    exit 1
fi

