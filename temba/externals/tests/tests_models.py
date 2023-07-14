import json
from unittest import mock
from unittest.mock import MagicMock, patch

from rest_framework import status
from rest_framework.test import APITestCase

from django.contrib.auth.models import User
from django.template import Engine
from django.test import TestCase
from django.urls import reverse

from temba.externals.models import ExternalService, ExternalServiceType
from temba.externals.types import TYPES
from temba.externals.types.omie.type import OmieType
from temba.orgs.models import Org

action_file = "temba/externals/types/omie/actions.json"


class TestGetActions(TestCase):
    def setUp(self):
        self.file = open(action_file, encoding="utf-8")
        self.action = self.file.read()
        self.user = User.objects.create_user(username="super", email="super@user.com", password="super")

    def test_get_actions_success(self):
        slug = "omie"
        self.types = TYPES.get(slug).get_actions()
        self.assertEqual(self.types, json.loads(self.action))

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
        self.assertEqual(response.data, json.loads(self.action))

    def test_get_external_types_error(self):
        slug = "omiee"
        response = self.client.get(reverse("actions", args=[slug]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ExternalServiceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="super", email="super@user.com", password="super")
        self.org = Org.objects.create(
            name="Temba", timezone="Africa/Kigali", created_by=self.user, modified_by=self.user
        )
        self.external_service = ExternalService.create(
            external_service_type="omie", name="Test Service", config={}, org=self.org, user=self.user
        )

    def test_get_type_from_code(self):
        type_code = "omie"
        type_instance = ExternalService.get_type_from_code(type_code)
        self.assertEqual(type_instance.slug, type_code)

    def test_release_method(self):
        self.external_service.release(user=self.user)
        self.assertFalse(self.external_service.is_active)

    def test_str_method(self):
        expected_str = f"ExternalService[uuid={self.external_service.uuid}, name={self.external_service.name}]"
        self.assertEqual(str(self.external_service), expected_str)

    def test_get_types(self):
        mock_omie_type = MagicMock()
        mock_omie_type.code = "omie"

        with patch("temba.externals.types.omie.type.OmieType", return_value=mock_omie_type):
            types = ExternalService.get_types()

        self.assertTrue(any(t.slug == "omie" for t in types))


class ExternalServiceTypeTestCase(TestCase):
    def setUp(self):
        self.type_class = ExternalServiceType
        self.type_class.serializer_class = None
        self.service_type = self.type_class()

    def test_is_available_to(self):
        user = mock.Mock()
        result = self.service_type.is_available_to(user)
        self.assertTrue(result)

    def test_get_connect_blurb(self):
        connect_blurb = "Sample connect blurb"
        self.service_type.connect_blurb = connect_blurb

        with mock.patch.object(Engine, "get_default") as mock_get_default:
            mock_engine = mock.Mock()
            mock_get_default.return_value = mock_engine

            expected_result = "Formatted connect blurb"
            mock_engine.from_string.return_value = expected_result

            self.service_type.get_connect_blurb()

    def test_get_actions_exception(self):
        expected_exception = Exception("Test exception")

        with mock.patch("builtins.open", mock.mock_open()) as mock_open:
            mock_open.side_effect = expected_exception

            self.service_type.get_actions()
