#!/usr/bin/env python
import os
import unittest
from subprocess import call

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


if __name__ == '__main__':
    existing_db_name = os.environ.get('SILENUS_PROVISIONER_DB_NAME')
    os.environ['SILENUS_PROVISIONER_DB_NAME'] = 'test_silenus_provisioner'
    import api  # importing here where the test databse name env var set
    unittest.main()

