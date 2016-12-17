#!/usr/bin/env python

import datetime
import json
import requests
import sys
import time
from pprint import pprint


class ApiClient(object):

    def __init__(self, endpoint='http://localhost:8000/v1/'):
        self.endpoint = endpoint

    def call(self, method, uri='', payload=None):
        assert method in ('get', 'post', 'put', 'delete')

        e = self.endpoint + uri

        print('Called endpoint: {}'.format(e))
        print('Payload sent: {}'.format(payload))
        begin = datetime.datetime.now()

        if method == 'get':
            r = requests.get(e, params=payload)
        elif method == 'post':
            r = requests.post(e, params=payload)
        elif method == 'put':
            r = requests.put(e, params=payload)
        elif method == 'delete':
            r = requests.delete(e, params=payload)

        end = datetime.datetime.now()
        print('Response received. Elapsed time: {}'.format(end - begin))
        print('Response status code:', r.status_code)
        if r.status_code < 500:
            print('Response:')
            pprint(r.json())

    def ping(self):
        self.call('get')

    def prime(self):
        u = 'create_jurisdiction'

        cg_payload = {'configuration_template_id': 1,
                      'jurisdiction_name': 'alpha',
                      'jurisdiction_type_id': 1}

        tier_payload = {'configuration_template_id': 2,
                        'jurisdiction_name': 'alpha_dev',
                        'jurisdiction_type_id': 2,
                        'parent_id': 1}

        cluster_payload = {'configuration_template_id': 3,
                           'jurisdiction_name': 'alpha_dev_01',
                           'jurisdiction_type_id': 3,
                           'parent_id': 2}

        self.call('post', uri=u, payload=cg_payload)
        print('############################################################')
        self.call('post', uri=u, payload=tier_payload)
        print('############################################################')
        self.call('post', uri=u, payload=cluster_payload)


if __name__ == '__main__':

    usage = """
        Usage:
            ./dev_client.py <method> <uri> <payload>
            ./dev_client.py prime
    """
    if len(sys.argv) == 1:
        exit(usage)

    if sys.argv[1] in ('--help', '-h', 'help'):
        exit(usage)

    if sys.argv[1] == 'prime':
        client = ApiClient()
        client.prime()
    elif len(sys.argv) != 4:
        exit(usage)
    else:
        method = sys.argv[1]
        uri = sys.argv[2]
        payload = sys.argv[3]

        client = ApiClient()
        client.call(method, uri, json.loads(payload))

