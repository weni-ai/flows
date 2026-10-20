from unittest.mock import patch
from uuid import uuid4

from django.urls import reverse

from temba.tests import MockResponse
from temba.tests.base import TembaTest
from temba.tickets.models import Ticketer

from .type import GenericType


class GenericTypeTest(TembaTest):
    def test_is_available_to(self):
        self.assertTrue(GenericType().is_available_to(self.admin))


class GenericMixin(TembaTest):
    def setUp(self):
        super().setUp()
        self.connect_url = reverse("tickets.types.generic.connect")


class GenericViewTest(GenericMixin):
    def test_connect(self):
        self.client.force_login(self.admin)
        data = {
            "base_url": "https://generic.example.com",
            "api_token": "api-token-123",
            "webhook_secret": "webhook-secret-123",
            "project_uuid": str(uuid4()),
            "project_name": "org support",
            "route_open": "/tickets/open",
            "route_forward": "/tickets/forward",
            "route_close": "/tickets/close",
            "route_reopen": "/tickets/reopen",
            "route_history": "/tickets/history",
        }

        with patch("requests.get") as mock_get:
            mock_get.return_value = MockResponse(200, "{}")
            response = self.client.post(self.connect_url, data=data)
            self.assertEqual(response.status_code, 302)

            ticketer = Ticketer.objects.order_by("id").last()
            self.assertEqual(data["project_name"], ticketer.name)
            self.assertEqual(GenericType.slug, ticketer.ticketer_type)
            self.assertEqual(data["base_url"], ticketer.config[GenericType.CONFIG_BASE_URL])
            self.assertEqual(data["api_token"], ticketer.config[GenericType.CONFIG_API_TOKEN])
            self.assertEqual(data["webhook_secret"], ticketer.config[GenericType.CONFIG_WEBHOOK_SECRET])
            self.assertEqual(data["project_uuid"], ticketer.config[GenericType.CONFIG_PROJECT_UUID])
            self.assertEqual(data["project_name"], ticketer.config[GenericType.CONFIG_PROJECT_NAME])
            self.assertEqual(data["route_open"], ticketer.config[GenericType.CONFIG_ROUTE_OPEN])
            self.assertEqual(data["route_forward"], ticketer.config[GenericType.CONFIG_ROUTE_FORWARD])
            self.assertEqual(data["route_close"], ticketer.config[GenericType.CONFIG_ROUTE_CLOSE])
            self.assertEqual(data["route_reopen"], ticketer.config[GenericType.CONFIG_ROUTE_REOPEN])
            self.assertEqual(data["route_history"], ticketer.config[GenericType.CONFIG_ROUTE_HISTORY])

            self.assertRedirect(response, reverse("tickets.ticket_list"))

    def test_connect_invalid_base_url(self):
        self.client.force_login(self.admin)
        data = {
            "base_url": "not-a-valid-url",
            "api_token": "api-token-123",
            "webhook_secret": "webhook-secret-123",
            "project_uuid": str(uuid4()),
            "project_name": "org support",
            "route_open": "/tickets/open",
            "route_forward": "/tickets/forward",
            "route_close": "/tickets/close",
            "route_reopen": "/tickets/reopen",
            "route_history": "/tickets/history",
        }

        response = self.client.post(self.connect_url, data=data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, "form", "base_url", "Enter a valid URL.")

    def test_connect_invalid_project_uuid(self):
        self.client.force_login(self.admin)
        data = {
            "base_url": "https://generic.example.com",
            "api_token": "api-token-123",
            "webhook_secret": "webhook-secret-123",
            "project_uuid": "not-a-uuid",
            "project_name": "org support",
            "route_open": "/tickets/open",
            "route_forward": "/tickets/forward",
            "route_close": "/tickets/close",
            "route_reopen": "/tickets/reopen",
            "route_history": "/tickets/history",
        }

        response = self.client.post(self.connect_url, data=data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, "form", "project_uuid", "Enter a valid UUID.")

    def test_connect_missing_required_fields(self):
        self.client.force_login(self.admin)

        response = self.client.post(self.connect_url, data={})
        self.assertEqual(response.status_code, 200)

        for field in (
            "base_url",
            "api_token",
            "webhook_secret",
            "project_uuid",
            "project_name",
            "route_open",
            "route_forward",
            "route_close",
            "route_reopen",
            "route_history",
        ):
            self.assertFormError(response, "form", field, "This field is required.")
