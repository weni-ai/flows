from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.urls import reverse

from temba.tests import MockResponse
from temba.tests.base import TembaTest
from temba.tickets.models import Ticketer
from temba.tickets.types.twilioflex2.views import ConnectView

from .type import TwilioFlex2Type


class TwilioFlex2TypeTest(TembaTest):
    def test_is_available_to(self):
        self.assertTrue(TwilioFlex2Type().is_available_to(self.admin))


class Twilioflex2Mixin(TembaTest):
    def setUp(self):
        super().setUp()
        self.connect_url = reverse("tickets.types.twilioflex2.connect")


class Twilioflex2ViewTest(Twilioflex2Mixin):
    def test_connect(self):
        self.client.force_login(self.admin)
        data = {
            "ticketer_name": "org support",
            "account_sid": "AC123456789",
            "auth_token": "123456789",
            "flex_instance_sid": "FX123456789",
            "flex_workspace_sid": "WS123456789",
            "flex_workflow_sid": "WW123456789",
            "conversation_service_sid": "IS123456789",
        }

        with patch("requests.get") as mock_get:
            mock_get.return_value = MockResponse(200, "{}")
            response = self.client.post(self.connect_url, data=data)
            self.assertEqual(response.status_code, 302)

            ticketer = Ticketer.objects.order_by("id").last()
            self.assertEqual(data["ticketer_name"], ticketer.name)

            self.assertRedirect(response, reverse("tickets.ticket_list"))

    def test_connection_failure(self):
        request = HttpRequest()

        form_data = {
            "ticketer_name": "Ticketer name",
            "account_sid": "valid SID",
            "auth_token": "Valid Token",
            "flex_instance_sid": "FXBAD",
            "flex_workspace_sid": "WSBAD",
            "flex_workflow_sid": "WWBAD",
            "conversation_service_sid": "ISBAD",
        }

        form = ConnectView.Form(data=form_data, request=request, ticketer_type="Ticketer Type")
        self.assertFalse(form.is_valid())

        with patch("temba.tickets.types.twilioflex2.views.requests.get") as mock_get:
            mock_get.side_effect = Exception("Error connecting to twilio APIs")

            with self.assertRaises(ValidationError) as cm:
                form.clean()

            expected_error_message = (
                "Unable to validate Twilio configuration. Please check your credentials and SIDs then try again."
            )
            self.assertIn(expected_error_message, str(cm.exception))
