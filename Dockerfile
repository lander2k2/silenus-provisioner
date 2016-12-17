FROM python:3

RUN apt-get update && apt-get install -y \
    nginx

COPY provisioner /var/www/provisioner
COPY requirements /var/www/requirements

RUN pip install -r /var/www/requirements/container.txt

COPY container/nginx.conf /etc/nginx/
COPY container/supervisord.conf /etc/supervisor.d/

ENV PYTHONPATH /var/www

EXPOSE 80

CMD ["supervisord", "-c", "/etc/supervisor.d/supervisord.conf", "-n"]

