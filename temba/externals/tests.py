import json

from rest_framework import status
from temba.externals.views import GetExternalTypes
from rest_framework.test import APITestCase


class TestGetExternalTypes(APITestCase):
    def setUp(self):

        with open("/temba/externals/types/omie/actions.json", encoding="utf-8") as actions:
                self.action = json.load(actions)

    def test_get_external_types_success(self):

        request = self.client.get('/externals/omie/actions')
        response = GetExternalTypes.as_view()(request, type='omie')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, self.action)


    def test_get_external_types_error(self):

        request = self.client.get('/externals/omiee/actions')
        response = GetExternalTypes.as_view()(request, type='omiee')

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data, Exception)
