import json
import os

from rest_framework import status
from django.test import TestCase
from rest_framework.test import APITestCase
from django.urls import reverse

from temba.externals.types import TYPES

action_file = os.path.join(os.path.dirname(__file__), "types/omie/actions.json")


class TestGetActions(TestCase):
    def setUp(self):
        self.file = open(action_file, encoding="utf-8")
        self.action = self.file.read()

    def test_get_actions_sucess(self):
        slug = "omie"
        self.types = TYPES.get(slug).get_actions()
        self.assertEqual(self.types, dict(json.loads(self.action)))


class TestGetExternalTypes(APITestCase):
    databases = "__all__"

    def setUp(self):
        self.file = open(action_file)
        self.action = self.file.read()

    def test_get_external_types_success(self):
        slug = "omie"
        response = self.client.get(reverse("actions", args=[slug]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, dict(json.loads(self.action)))

    def test_get_external_types_error(self):
        slug = "omiee"
        response = self.client.get(reverse("actions", args=[slug]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
