from rest_framework import status

from django.test import override_settings
from django.urls import reverse

from temba.tests.base import TembaTest
from temba.wpp_flows.models import WhatsappFlow


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

    def test_whatsapp_flows_not_found(self):
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

            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
