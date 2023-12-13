from unittest import mock
from unittest.mock import patch
from uuid import uuid4

from django.forms import ValidationError
from django.http import HttpRequest
from django.test import RequestFactory
from django.urls import reverse

from temba.tests import MockResponse, TembaTest
from temba.tickets.models import Ticketer
from temba.tickets.types.wenichats.views import ConnectView
from temba.utils import json

from .type import WeniChatsType


class WeniChatsTypeTest(TembaTest):
    def test_is_available_to(self):
        self.assertTrue(WeniChatsType().is_available_to(self.admin))


class WeniChatsMixin(TembaTest):
    def setUp(self):
        super().setUp()
        self.connect_url = reverse("tickets.types.wenichats.connect")


class WeniChatsViewTest(WeniChatsMixin):
    @patch("requests.get")
    def test_connect(self, mock_get):
        self.client.force_login(self.admin)

        data = {
            "sector_uuid": "d3cae43d-cf25-4892-bfa6-0f24a856cfb8",
            "project_auth": "bb0682cd-5ed6-4c3d-851f-b2f0c1952f81",
        }

        mock_get.return_value = MockResponse(
            200,
            json.dumps(
                {
                    "count": 3,
                    "next": "",
                    "previous": "",
                    "results": [
                        {"uuid": "21aecf8c-0c73-4059-ba82-4343e0cc627c", "name": "Fluxos"},
                        {"uuid": "4f88b656-194d-4a83-a166-5d84ba825b8d", "name": "Inteligencia"},
                        {"uuid": "d3cae43d-cf25-4892-bfa6-0f24a856cfb8", "name": "Contas"},
                    ],
                }
            ),
        )

        response = self.client.post(self.connect_url, data=data)
        self.assertEqual(response.status_code, 302)

        ticketer = Ticketer.objects.order_by("id").last()
        self.assertEqual("Contas", ticketer.name)

        self.assertRedirect(response, reverse("tickets.ticket_list"))

    @patch("requests.get")
    def test_invalid_sector_uuid(self, mock_get):
        request = HttpRequest()
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "results": [
                {"uuid": "valid_uuid", "name": "Valid Sector"},
            ]
        }

        form_data = {
            "project_auth": "my_project_auth",
            "sector_uuid": "",
        }
        form = ConnectView.Form(data=form_data, request=request, ticketer_type="Ticketer Type")

        self.assertFalse(form.is_valid())

        with self.assertRaisesMessage(ValidationError, "Invalid sector UUID"):
            form.clean()

    @patch("temba.tickets.views.Ticketer.objects.filter")
    def test_existing_ticketer_same_workspace(self, mock_filter):
        mock_existing = Ticketer()
        mock_existing.org_id = 1
        mock_filter.return_value = mock_existing

        form_data = {
            "sector_uuid": "d3cae43d-cf25-4892-bfa6-0f24a856cfb8",
            "project_auth": "bb0682cd-5ed6-4c3d-851f-b2f0c1952f81",
        }
        request = mock.Mock()
        request.user.get_org.return_value.id = 1
        form = ConnectView.Form(data=form_data, request=request, ticketer_type="Ticketer Type")

        self.assertFalse(form.is_valid())

        with self.assertRaisesMessage(
            ValidationError, "A Weni Chats ticketer for this sector already exists in this workspace."
        ):
            form.clean()

    @patch("temba.tickets.types.wenichats.views.Ticketer.objects.filter")
    def test_existing_ticketer_another_workspace(self, mock_filter):
        mock_filter.return_value.exists.return_value = True

        request = RequestFactory().get("/")
        request.user = self.admin

        form_data = {
            "sector_uuid": uuid4(),
            "project_auth": uuid4(),
        }
        form = ConnectView.Form(data=form_data, request=request, ticketer_type="Ticketer Type")
        self.assertFalse(form.is_valid())

        with self.assertRaises(ValidationError) as context:
            form.clean()

        expected_message = "A Weni Chats ticketer for this sector already exists in another workspace."
        self.assertIn(expected_message, str(context.exception))

    @patch("requests.get")
    def test_unsuccessful_ticketer_creation(self, mock_get):
        self.client.force_login(self.admin)
        mock_get.return_value.status_code = 500
        form_data = {
            "project_auth": uuid4(),
            "sector_uuid": uuid4(),
        }

        with self.assertRaises(Exception) as context:
            self.client.post(self.connect_url, data=form_data)

        expected_message = "This ticketer integration with Weni Chats couldn't be created, check if all fields is correct and try again."
        self.assertEqual(expected_message, str(context.exception))

    @patch("requests.get")
    def test_unsuccessful_ticketer_creation_sector_not_exists(self, mock_get):
        self.client.force_login(self.admin)
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"results": []}
        form_data = {
            "project_auth": uuid4(),
            "sector_uuid": uuid4(),
        }

        with self.assertRaises(Exception) as context:
            self.client.post(self.connect_url, data=form_data)

        expected_message = (
            "This ticketer integration with Weni Chats couldn't be created, the defined sector not exists."
        )
        self.assertEqual(expected_message, str(context.exception))
