import json
import os

from rest_framework import status
from rest_framework.test import APITestCase

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from temba.externals.types import TYPES
from temba.externals.types.omie.type import OmieType

action_file = os.path.join(os.path.dirname(__file__), "types/omie/actions.json")


class TestGetActions(TestCase):
    def setUp(self):
        self.file = open(action_file, encoding="utf-8")
        self.action = self.file.read()
        self.user = User.objects.create_user(username="super", email="super@user.com", password="super")

    def test_get_actions_sucess(self):
        slug = "omie"
        self.types = TYPES.get(slug).get_actions()
        self.assertEqual(self.types, dict(json.loads(self.action)))

    def test_is_available_to(self):
        omie_type = OmieType()
        user = self.user

        result = omie_type.is_available_to(user)

        self.assertTrue(result)


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
