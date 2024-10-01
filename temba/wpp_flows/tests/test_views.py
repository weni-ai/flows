from unittest import TestCase
from unittest.mock import MagicMock, patch

import requests
from rest_framework import status
from rest_framework.response import Response

from django.test import override_settings
from django.urls import reverse

from temba.tests.base import TembaTest
from temba.wpp_flows.models import WhatsappFlow
from temba.wpp_flows.tasks import create_single_whatsapp_flow, get_whatsapp_flow_by_id, update_whatsapp_flow_by_id


class TestWhatsappFlowsIntegration(TembaTest):
    def setUp(self):
        super().setUp()

        WhatsappFlow.objects.create(
            facebook_flow_id="123456",
            category=["OTHER"],
            status="DRAFT",
            name="Flow name",
            validation_errors=[],
            org=self.org,
            channel=self.channel,
            is_active=True,
            screens={},
            variables=[],
        )

    def test_whatsapp_flows_create_success(self):
        with override_settings(COURIER_FIXED_ACCESS_TOKEN="12345"):
            url = reverse("whatsapp_flows-list")
            fake_token = "12345"
            url_with_token = f"{url}?token={fake_token}"

            data = {
                "entry": [
                    {
                        "id": "123456",
                        "time": 1684969340,
                        "changes": [
                            {
                                "value": {
                                    "event": "FLOW_STATUS_CHANGE",
                                    "message": "Flow name",
                                    "flow_id": "123456",
                                    "old_status": "DRAFT",
                                    "new_status": "PUBLISHED",
                                },
                                "field": "flows",
                            }
                        ],
                    }
                ],
                "object": "whatsapp_business_account",
            }

            response = self.client.post(url_with_token, data, content_type="application/json")

            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_whatsapp_flows_create_failure(self):
        with override_settings(COURIER_FIXED_ACCESS_TOKEN="12345"):
            url = reverse("whatsapp_flows-list")
            fake_token = "12345"
            url_with_token = f"{url}?token={fake_token}"

            data = {
                "entry": [
                    {
                        "id": "123456",
                        "time": 1684969340,
                        "changes": [
                            {
                                "value": {
                                    "event": "FLOW_STATUS_CHANGE",
                                    "message": "Flow 1",
                                    "flow_id": "6627390910605886",
                                    "old_status": "DRAFT",
                                    "new_status": "PUBLISHEDD",
                                },
                                "field": "flows",
                            }
                        ],
                    }
                ],
                "object": "whatsapp_business_account",
            }

            response = self.client.post(url_with_token, data, content_type="application/json")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_whatsapp_flows_create_failure_no_token(self):
        with override_settings(COURIER_FIXED_ACCESS_TOKEN="12345"):
            url = reverse("whatsapp_flows-list")

            data = {
                "entry": [
                    {
                        "id": "123456",
                        "time": 1684969340,
                        "changes": [
                            {
                                "value": {
                                    "event": "FLOW_STATUS_CHANGE",
                                    "message": "Flow 1",
                                    "flow_id": "6627390910605886",
                                    "old_status": "DRAFT",
                                    "new_status": "PUBLISHEDD",
                                },
                                "field": "flows",
                            }
                        ],
                    }
                ],
                "object": "whatsapp_business_account",
            }

            response = self.client.post(url, data, content_type="application/json")

            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_whatsapp_flows_create_failure_wrong_token(self):
        with override_settings(COURIER_FIXED_ACCESS_TOKEN="12345"):
            url = reverse("whatsapp_flows-list")
            fake_token = "123456"
            url_with_token = f"{url}?token={fake_token}"

            data = {
                "entry": [
                    {
                        "id": "123456",
                        "time": 1684969340,
                        "changes": [
                            {
                                "value": {
                                    "event": "FLOW_STATUS_CHANGE",
                                    "message": "Flow 1",
                                    "flow_id": "6627390910605886",
                                    "old_status": "DRAFT",
                                    "new_status": "PUBLISHEDD",
                                },
                                "field": "flows",
                            }
                        ],
                    }
                ],
                "object": "whatsapp_business_account",
            }

            response = self.client.post(url_with_token, data, content_type="application/json")

            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_whatsapp_flows_create_no_entry(self):
        with override_settings(COURIER_FIXED_ACCESS_TOKEN="12345"):
            url = reverse("whatsapp_flows-list")
            fake_token = "12345"
            url_with_token = f"{url}?token={fake_token}"

            data = {
                "object": "whatsapp_business_account",
            }

            response = self.client.post(url_with_token, data, content_type="application/json")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_whatsapp_flows_no_id(self):
        with override_settings(COURIER_FIXED_ACCESS_TOKEN="12345"):
            url = reverse("whatsapp_flows-list")
            fake_token = "12345"
            url_with_token = f"{url}?token={fake_token}"

            data = {
                "entry": [
                    {
                        "time": 1684969340,
                        "changes": [
                            {
                                "value": {
                                    "event": "FLOW_STATUS_CHANGE",
                                    "message": "Flow 1",
                                    "flow_id": None,
                                    "old_status": "DRAFT",
                                    "new_status": "PUBLISHEDD",
                                },
                                "field": "flows",
                            }
                        ],
                    }
                ],
                "object": "whatsapp_business_account",
            }

            response = self.client.post(url_with_token, data, content_type="application/json")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_whatsapp_flows_error_webhook_type(self):
        with override_settings(COURIER_FIXED_ACCESS_TOKEN="12345"):
            url = reverse("whatsapp_flows-list")
            fake_token = "12345"
            url_with_token = f"{url}?token={fake_token}"

            data = {
                "entry": [
                    {
                        "time": 1684969340,
                        "changes": [
                            {
                                "value": {
                                    "event": "ANOTHER EVENT",
                                    "message": "Flow 1",
                                    "flow_id": "123",
                                    "old_status": "DRAFT",
                                    "new_status": "PUBLISHED",
                                },
                                "field": "flows",
                            }
                        ],
                    }
                ],
                "object": "whatsapp_business_account",
            }

            response = self.client.post(url_with_token, data, content_type="application/json")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("temba.wpp_flows.views.WhatsappFlow.update_status")
    @patch("temba.wpp_flows.views.update_whatsapp_flow_by_id")
    def test_whatsapp_flows_not_found(self, mock_update_flow, mock_update_status):
        mock_update_status.side_effect = WhatsappFlow.DoesNotExist
        mock_update_flow.return_value = None

        with override_settings(COURIER_FIXED_ACCESS_TOKEN="12345"):
            url = reverse("whatsapp_flows-list")
            fake_token = "12345"
            url_with_token = f"{url}?token={fake_token}"

            data = {
                "entry": [
                    {
                        "id": "00000000",
                        "time": 1684969340,
                        "changes": [
                            {
                                "value": {
                                    "event": "FLOW_STATUS_CHANGE",
                                    "message": "Flow 1",
                                    "flow_id": "000000000",
                                    "old_status": "DRAFT",
                                    "new_status": "PUBLISHED",
                                },
                                "field": "flows",
                            }
                        ],
                    }
                ],
                "object": "whatsapp_business_account",
            }

            response = self.client.post(url_with_token, data, content_type="application/json")

            mock_update_flow.assert_called_once_with("000000000")

            self.assertIsInstance(response, Response)
            self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestGetWhatsappFlowById(TembaTest):
    @patch("temba.wpp_flows.tasks.requests.get")
    def test_get_whatsapp_flow_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "123",
            "name": "Test Flow",
            "categories": ["category1"],
            "status": "active",
            "validation_errors": [],
            "whatsapp_business_account": {"id": "waba_123"},
        }
        mock_get.return_value = mock_response

        flow = get_whatsapp_flow_by_id("123")

        mock_get.assert_called_once()
        self.assertEqual(flow["id"], "123")
        self.assertEqual(flow["name"], "Test Flow")

    @patch("temba.wpp_flows.tasks.requests.get")
    def test_get_whatsapp_flow_failure(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        flow = get_whatsapp_flow_by_id("123")

        mock_get.assert_called_once()
        self.assertEqual(flow, [])


class TestUpdateWhatsappFlowById(TestCase):
    @patch("temba.wpp_flows.tasks.get_whatsapp_flow_by_id")
    @patch("temba.wpp_flows.tasks.Channel.objects.filter")
    @patch("temba.wpp_flows.tasks.create_single_whatsapp_flow")
    def test_update_whatsapp_flow_success(self, mock_create_flow, mock_filter, mock_get_flow):
        mock_get_flow.return_value = {
            "id": "123",
            "name": "Test Flow",
            "categories": ["category1"],
            "status": "active",
            "validation_errors": [],
            "whatsapp_business_account": {"id": "waba_123"},
        }

        mock_channel = MagicMock()
        mock_channel.config = {"wa_waba_id": "waba_123"}
        mock_filter.return_value = [mock_channel]

        update_whatsapp_flow_by_id("123")

        mock_get_flow.assert_called_once_with("123")
        mock_filter.assert_called_once_with(is_active=True, channel_type__in=["WA", "WAC"])
        mock_create_flow.assert_called_once_with(mock_get_flow.return_value, mock_channel)

    @patch("temba.wpp_flows.tasks.requests.get")
    def test_get_whatsapp_flow_by_id_request_exception(self, mock_get):
        mock_get.side_effect = requests.RequestException("Error")

        result = get_whatsapp_flow_by_id("12345")

        self.assertEqual(result, [])


class TestCreateSingleWhatsappFlow(TestCase):
    @patch("temba.wpp_flows.tasks.get_assets_data")
    @patch("temba.wpp_flows.tasks.extract_data_keys")
    @patch("temba.wpp_flows.tasks.WhatsappFlow.objects.create")
    def test_create_single_whatsapp_flow(self, mock_create, mock_extract_data, mock_get_assets):
        mock_get_assets.return_value = {"screens": "mocked_screens"}
        mock_extract_data.return_value = {"variables": "mocked_variables"}

        mock_flow = {
            "id": "123",
            "name": "Test Flow",
            "categories": ["category1"],
            "status": "active",
            "validation_errors": [],
            "whatsapp_business_account": {"id": "waba_123"},
        }
        mock_channel = MagicMock()
        mock_channel.org = "Test Org"

        create_single_whatsapp_flow(mock_flow, mock_channel)

        mock_create.assert_called_once_with(
            facebook_flow_id="123",
            category=["category1"],
            status="active",
            name="Test Flow",
            validation_errors=[],
            screens={"screens": "mocked_screens"},
            variables={"variables": "mocked_variables"},
            org="Test Org",
            channel=mock_channel,
            is_active=True,
        )
