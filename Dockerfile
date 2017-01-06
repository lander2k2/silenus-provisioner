FROM python:3

RUN apt-get update && apt-get install -y \
    nginx

RUN useradd -s /bin/bash provisioner

COPY provisioner /var/www/provisioner
COPY requirements /var/www/requirements
RUN pip install -r /var/www/requirements/container.txt
RUN chown -R provisioner /var/www

COPY container/nginx.conf /etc/nginx/

COPY container/api-supervisord.conf /etc/supervisor.d/
COPY container/worker-supervisord.conf /etc/supervisor.d/
RUN chgrp provisioner /usr/local/bin/supervisord
RUN chgrp provisioner /etc/supervisor.d/*-supervisord.conf
RUN chmod g+x /usr/local/bin/supervisord
RUN chmod g+r /etc/supervisor.d/*-supervisord.conf

RUN chgrp provisioner /usr/local/bin/gunicorn
RUN chmod g+x /usr/local/bin/gunicorn

RUN chgrp provisioner /usr/local/bin/celery
RUN chmod g+x /usr/local/bin/celery

COPY container/docker-entrypoint.sh /
RUN chmod +x /docker-entrypoint.sh

RUN chgrp provisioner /var/log
RUN chmod g+w /var/log

ENV PYTHONPATH /var/www

EXPOSE 80

ENTRYPOINT ["/bin/bash", "/docker-entrypoint.sh"]

