#!/usr/bin/env python
import os
import time
import unittest
from subprocess import call, check_output, CalledProcessError

import boto3
import falcon


class TestProvisioner(unittest.TestCase):

    supervisor_conf = os.path.join(
                          os.path.dirname(os.path.realpath(__file__)),
                          '..', 'dev', 'supervisord.conf'
                      )

    def setUp(self):
        try:
            output = check_output(['supervisorctl', '-c', self.supervisor_conf,
                                   'status', 'provisioner:worker'])
            status = output.decode('utf-8')
        except CalledProcessError as e:
            status = str(e.stdout)

        if 'RUNNING' in status:
            self.worker_running = True
            call(['supervisorctl', '-c', self.supervisor_conf,
                  'stop', 'provisioner:worker'])
        else:
            self.worker_running = False

        call(['supervisorctl', '-c', self.supervisor_conf,
              'start', 'test_worker'])

        os.environ['POSTGRES_DB'] = os.environ.get('TEST_POSTGRES_DB')
        db.create()
        defaults.load_defaults(db)

    def tearDown(self):
        call(['supervisorctl', '-c', self.supervisor_conf,
              'stop', 'test_worker'])

        if self.worker_running:
            call(['supervisorctl', '-c', self.supervisor_conf,
                  'start', 'provisioner:worker'])

        db.engine.dispose()
        call(['dropdb', os.environ.get('POSTGRES_DB')])

        os.environ['POSTGRES_DB'] = existing_db_name

    def test_jurisdiction_types(self):
        # request non-existent
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.get_jurisdiction_types,
                          jurisdiction_type_id=99999)

        # request all
        self.assertListEqual(prov_defaults['jurisdiction_types'],
                             api.get_jurisdiction_types()['data'])

        # request particulars
        for x in range(3):
            self.assertListEqual([prov_defaults['jurisdiction_types'][x]],
                                 api.get_jurisdiction_types(jurisdiction_type_id=x+1)['data'])

    def test_configuration_templates(self):
        # request non-existent
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.get_configuration_templates,
                          configuration_template_id=99999)

        # request all
        self.assertListEqual(prov_defaults['configuration_templates'],
                             api.get_configuration_templates()['data'])

        # request particulars
        for x in range(len(prov_defaults['configuration_templates'])):
            self.assertListEqual([prov_defaults['configuration_templates'][x]],
                                 api.get_configuration_templates(configuration_template_id=x+1)['data'])

    def test_jurisdictions(self):
        test_cg = {
            'id': 1,
            'name': 'test_control_group',
            'created_on': None,
            'active': False,
            'assets': None,
            'metadata': None,
            'configuration': prov_defaults['configuration_templates'][0]['configuration'],
            'jurisdiction_type_id': 1,
            'parent_id': None
        }
        test_tier = {
            'id': 2,
            'name': 'test_tier',
            'created_on': None,
            'active': False,
            'assets': None,
            'metadata': None,
            'configuration': prov_defaults['configuration_templates'][1]['configuration'],
            'jurisdiction_type_id': 2,
            'parent_id': 1
        }
        test_cluster = {
            'id': 3,
            'name': 'test_cluster',
            'created_on': None,
            'active': False,
            'assets': None,
            'metadata': None,
            'configuration': prov_defaults['configuration_templates'][2]['configuration'],
            'jurisdiction_type_id': 3,
            'parent_id': 2
        }
        test_jurisdictions = [test_cg, test_tier, test_cluster]

        cf_client = boto3.client('cloudformation', region_name=test_cg['configuration']['region'])

        def jurisdiction_active(jurisdiction_id):
            check_attempts = 0
            active = False
            while not active:
                j = api.get_jurisdictions(jurisdiction_id=jurisdiction_id)
                if not j['data'][0]['active']:
                    if check_attempts < 30:
                        time.sleep(30)
                        check_attempts += 1
                        continue
                    else:
                        return False
                else:
                    return True

        def stack_id_exists(stack_id):
            stacks = cf_client.list_stacks()
            stack_ids = []
            for s in stacks['StackSummaries']:
                stack_ids.append(s['StackId'])
            if stack_id in stack_ids:
                return True
            else:
                return False

        # create control group
        create_cg_resp = api.create_jurisdiction(
                            jurisdiction_name=test_cg['name'],
                            jurisdiction_type_id=test_cg['jurisdiction_type_id'],
                            configuration_template_id=prov_defaults['configuration_templates'][0]['id'])
        create_cg_resp['data']['created_on'] = None
        self.assertDictEqual(test_cg, create_cg_resp['data'])

        # create new tier
        create_tier_resp = api.create_jurisdiction(
                                jurisdiction_name=test_tier['name'],
                                jurisdiction_type_id=test_tier['jurisdiction_type_id'],
                                configuration_template_id=prov_defaults['configuration_templates'][1]['id'],
                                parent_id=test_tier['parent_id'])
        create_tier_resp['data']['created_on'] = None
        self.assertDictEqual(test_tier, create_tier_resp['data'])

        # create new cluster
        create_cluster_resp = api.create_jurisdiction(
                                jurisdiction_name=test_cluster['name'],
                                jurisdiction_type_id=test_cluster['jurisdiction_type_id'],
                                configuration_template_id=prov_defaults['configuration_templates'][2]['id'],
                                parent_id=test_cluster['parent_id'])
        create_cluster_resp['data']['created_on'] = None
        self.assertDictEqual(test_cluster, create_cluster_resp['data'])

        # request non-existent
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.get_jurisdictions,
                          jurisdiction_id=99999)

        # request all
        all_j = api.get_jurisdictions()
        for j in all_j['data']:
            j['created_on'] = None
        self.assertListEqual(test_jurisdictions, all_j['data'])

        # request particulars
        for test_j in test_jurisdictions:
            j = api.get_jurisdictions(jurisdiction_id=int(test_j['id']))
            j['data'][0]['created_on'] = None
            self.assertListEqual([test_j], j['data'])

        # edit non-existent
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.edit_jurisdiction,
                          jurisdiction_id=99999)

        # successful edits
        for test_j in test_jurisdictions:
            test_j['name'] += '_edit'
            j = api.edit_jurisdiction(jurisdiction_id=int(test_j['id']),
                                      **{'name': test_j['name']})
            j['data']['created_on'] = None
            self.assertDictEqual(test_j, j['data'])

        # provision tier without control group
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.provision_jurisdiction,
                          jurisdiction_id=2)

        # succuessful control group provision
        prov_cg = api.provision_jurisdiction(jurisdiction_id=1)
        self.assertTrue(isinstance(
            prov_cg['data']['assets']['cloudformation_stack']['stack_id'],
            str
        ))
        self.assertTrue(stack_id_exists(
            prov_cg['data']['assets']['cloudformation_stack']['stack_id']#,
        ))

        # ensure control group activates
        self.assertTrue(jurisdiction_active(prov_cg['data']['id']))

        # successful tier provision
        prov_tier = api.provision_jurisdiction(jurisdiction_id=2)
        self.assertTrue(isinstance(
            prov_tier['data']['assets']['cloudformation_stack']['stack_id'],
            str
        ))
        self.assertTrue(stack_id_exists(
            prov_tier['data']['assets']['cloudformation_stack']['stack_id']#,
        ))

        # ensure tier activates
        self.assertTrue(jurisdiction_active(prov_tier['data']['id']))

        # successful cluster provision
        prov_cluster = api.provision_jurisdiction(jurisdiction_id=3)
        self.assertTrue(isinstance(
            prov_cluster['data']['assets']['cloudformation_stack']['network']['stack_id'],
            str
        ))
        self.assertTrue(stack_id_exists(
            prov_cluster['data']['assets']['cloudformation_stack']['network']['stack_id']#,
        ))

        # ensure cluster activates
        self.assertTrue(jurisdiction_active(prov_cluster['data']['id']))

        # attempt to decommission tier with active cluster
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.decommission_jurisdiction,
                          jurisdiction_id=2)

        # attempt to decommission control group with active tier
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.decommission_jurisdiction,
                          jurisdiction_id=1)

        # successful cluster decommission
        decom_cluster = api.decommission_jurisdiction(jurisdiction_id=3)
        self.assertFalse(decom_cluster['data']['active'])
        cluster_delete_checks = 0
        cluster_deleted = False
        while not cluster_deleted:
            stacks = cf_client.list_stacks()
            for s in stacks['StackSummaries']:
                if s['StackId'] == prov_cluster['data']['assets']['cloudformation_stack']['network']['stack_id']:
                    if not s['StackStatus'] == 'DELETE_COMPLETE':
                        self.assertLess(cluster_delete_checks, 30)
                        time.sleep(30)
                        cluster_delete_checks += 1
                        continue
                    else:
                        cluster_deleted = True

        # successful tier decommisssion
        decom_tier = api.decommission_jurisdiction(jurisdiction_id=2)
        self.assertFalse(decom_tier['data']['active'])
        tier_delete_checks = 0
        tier_deleted = False
        while not tier_deleted:
            stacks = cf_client.list_stacks()
            for s in stacks['StackSummaries']:
                if s['StackId'] == prov_tier['data']['assets']['cloudformation_stack']['stack_id']:
                    if not s['StackStatus'] == 'DELETE_COMPLETE':
                        self.assertLess(tier_delete_checks, 30)
                        time.sleep(20)
                        tier_delete_checks += 1
                        continue
                    else:
                        tier_deleted = True

        # successful control group decommission
        decom_cg = api.decommission_jurisdiction(jurisdiction_id=1)
        self.assertFalse(decom_cg['data']['active'])

        # try to decommision inactive control group
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.decommission_jurisdiction,
                          jurisdiction_id=1)

        # try to decommission inactive tier
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.decommission_jurisdiction,
                          jurisdiction_id=2)

        # try to decommission inactive cluster
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.decommission_jurisdiction,
                          jurisdiction_id=1)

        # provision control group on unsupported platform
        bad_config = prov_defaults['configuration_templates'][0]['configuration']
        bad_config['platform'] = 'bare_metal'
        api.edit_jurisdiction(jurisdiction_id=1, **{'configuration': bad_config})
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.provision_jurisdiction,
                          jurisdiction_id=1)


if __name__ == '__main__':
    existing_db_name = os.environ.get('POSTGRES_DB')
    os.environ['POSTGRES_DB'] = os.environ.get('TEST_POSTGRES_DB')
    from provisioner import api
    from provisioner import db
    from provisioner import defaults
    from provisioner.defaults import PROVISIONER_DEFAULTS as prov_defaults
    unittest.main()

