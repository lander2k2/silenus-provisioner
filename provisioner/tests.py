#!/usr/bin/env python
import os
import time
import unittest
from subprocess import call

import boto3
import falcon

import defaults
from defaults import PROVISIONER_DEFAULTS as prov_defaults


class TestProvisioner(unittest.TestCase):

    def setUp(self):
        os.environ['SILENUS_PROVISIONER_DB_NAME'] = 'test_silenus_provisioner'
        api.db.create()
        defaults.load_defaults(api.db)

    def tearDown(self):
        api.db.engine.dispose()
        call(['dropdb', os.environ.get('SILENUS_PROVISIONER_DB_NAME')])
        os.environ['SILENUS_PROVISIONER_DB_NAME'] = existing_db_name

    def test_jurisdiction_types(self):
        # request non-existent
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.get_jurisdiction_types,
                          jurisdiction_type_id=99999)

        # request all
        self.assertListEqual(prov_defaults['jurisdiction_types'],
                             api.get_jurisdiction_types())

        # request particulars
        for x in range(3):
            self.assertListEqual([prov_defaults['jurisdiction_types'][x]],
                                 api.get_jurisdiction_types(jurisdiction_type_id=x+1))

    def test_configuration_templates(self):
        # request non-existent
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.get_configuration_templates,
                          configuration_template_id=99999)

        # request all
        self.assertListEqual(prov_defaults['configuration_templates'],
                             api.get_configuration_templates())

        # request particulars
        for x in range(len(prov_defaults['configuration_templates'])):
            self.assertListEqual([prov_defaults['configuration_templates'][x]],
                                 api.get_configuration_templates(configuration_template_id=x+1))

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

        # create control group
        create_cg_resp = api.create_jurisdiction(
                                jurisdiction_name=test_cg['name'],
                                jurisdiction_type_id=test_cg['jurisdiction_type_id'],
                                configuration_template_id=prov_defaults['configuration_templates'][0]['id'])
        create_cg_resp['created_on'] = None
        self.assertDictEqual(test_cg, create_cg_resp)

        # create new tier
        create_tier_resp = api.create_jurisdiction(
                                jurisdiction_name=test_tier['name'],
                                jurisdiction_type_id=test_tier['jurisdiction_type_id'],
                                configuration_template_id=prov_defaults['configuration_templates'][1]['id'],
                                parent_id=test_tier['parent_id'])
        create_tier_resp['created_on'] = None
        self.assertDictEqual(test_tier, create_tier_resp)

        # create new cluster
        create_cluster_resp = api.create_jurisdiction(
                                jurisdiction_name=test_cluster['name'],
                                jurisdiction_type_id=test_cluster['jurisdiction_type_id'],
                                configuration_template_id=prov_defaults['configuration_templates'][2]['id'],
                                parent_id=test_cluster['parent_id'])
        create_cluster_resp['created_on'] = None
        self.assertDictEqual(test_cluster, create_cluster_resp)

        # request non-existent
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.get_jurisdictions,
                          jurisdiction_id=99999)

        # request all
        all_j = api.get_jurisdictions()
        for j in all_j:
            j['created_on'] = None
        self.assertListEqual(test_jurisdictions, all_j)

        # request particulars
        for test_j in test_jurisdictions:
            j = api.get_jurisdictions(jurisdiction_id=int(test_j['id']))
            j[0]['created_on'] = None
            self.assertListEqual([test_j], j)

        # edit non-existent
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.edit_jurisdiction,
                          jurisdiction_id=99999)

        # successful edits
        for test_j in test_jurisdictions:
            test_j['name'] += '_edit'
            j = api.edit_jurisdiction(jurisdiction_id=int(test_j['id']),
                                      **{'name': test_j['name']})
            j['created_on'] = None
            self.assertDictEqual(test_j, j)

        # provision tier without control group
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.provision_jurisdiction,
                          jurisdiction_id=2)

        # succuessful control group provision
        prov_cg = api.provision_jurisdiction(jurisdiction_id=1)
        self.assertTrue(prov_cg['active'])
        bucket_name = prov_cg['assets']['s3_bucket']
        s3_client = boto3.client('s3', region_name=prov_cg['configuration']['region'])
        buckets = s3_client.list_buckets()
        bucket_names = []
        for b in buckets['Buckets']:
            bucket_names.append(b['Name'])
        self.assertIn(bucket_name, bucket_names)

        # successful tier provision
        prov_tier = api.provision_jurisdiction(jurisdiction_id=2)
        self.assertTrue(isinstance(prov_tier['assets']['cloudformation_stack'], str))
        cf_client = boto3.client('cloudformation', region_name=prov_cg['configuration']['region'])
        stacks = cf_client.list_stacks()
        stack_ids = []
        for s in stacks['StackSummaries']:
            stack_ids.append(s['StackId'])
        self.assertIn(prov_tier['assets']['cloudformation_stack'], stack_ids)

        # activate tier
        tier_activate_attempts = 0
        tier_active = False
        while not tier_active:
            t = api.activate_jurisdiction(jurisdiction_id=2)
            if not t['active']:
                self.assertLess(tier_activate_attempts, 30)
                time.sleep(20)
                tier_activate_attempts += 1
                continue
            else:
                tier_active = True

        # attempt to decommission control group with active tier
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.decommission_jurisdiction,
                          jurisdiction_id=1)

        # successful decommisssion tier
        decom_tier = api.decommission_jurisdiction(jurisdiction_id=2)
        self.assertFalse(decom_tier['active'])
        tier_delete_checks = 0
        tier_deleted = False
        while not tier_deleted:
            stacks = cf_client.list_stacks()
            for s in stacks['StackSummaries']:
                if s['StackId'] == prov_tier['assets']['cloudformation_stack']:
                    if not s['StackStatus'] == 'DELETE_COMPLETE':
                        self.assertLess(tier_delete_checks, 30)
                        time.sleep(20)
                        tier_delete_checks += 1
                        continue
                    else:
                        tier_deleted = True

        # successful control group decommission
        decom_cg = api.decommission_jurisdiction(jurisdiction_id=1)
        self.assertFalse(decom_cg['active'])
        s3_client = boto3.client('s3', region_name=prov_cg['configuration']['region'])
        buckets = s3_client.list_buckets()
        bucket_names = []
        for b in buckets['Buckets']:
            bucket_names.append(b['Name'])
        self.assertNotIn(bucket_name, bucket_names)

        # try to decommision inactive control group
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.decommission_jurisdiction,
                          jurisdiction_id=1)

        # provision congrol group on unsupported platform
        bad_config = prov_defaults['configuration_templates'][0]['configuration']
        bad_config['platform'] = 'bare_metal'
        api.edit_jurisdiction(jurisdiction_id=1, **{'configuration': bad_config})
        self.assertRaises(falcon.errors.HTTPBadRequest,
                          api.provision_jurisdiction,
                          jurisdiction_id=1)


if __name__ == '__main__':
    existing_db_name = os.environ.get('SILENUS_PROVISIONER_DB_NAME')
    os.environ['SILENUS_PROVISIONER_DB_NAME'] = 'test_silenus_provisioner'
    import api  # importing here where the test databse name env var set
    unittest.main()

