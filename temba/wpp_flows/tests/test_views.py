from rest_framework import status

from django.urls import reverse

from temba.tests.base import TembaTest
from temba.wpp_flows.models import WhatsappFlow


class TestWhatsappFlowsIntegration(TembaTest):
    def setUp(self):
        super().setUp()

        self.whatsapp_flow = WhatsappFlow.objects.create(
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

        response = self.client.post(url, data, content_type="application/json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_whatsapp_flows_create_failure(self):
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

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, "An error occured")
