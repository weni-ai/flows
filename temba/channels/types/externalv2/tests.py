from django.urls import reverse

from temba.tests import TembaTest
from temba.utils import json

from ...models import Channel


class ExternalV2TypeTest(TembaTest):
    def setUp(self):
        super().setUp()
        Channel.objects.filter(channel_type="E2").delete()

    def test_claim_url_visible(self):
        url = reverse("channels.types.externalv2.claim")
        self.login(self.admin)
        response = self.client.get(reverse("channels.channel_claim"))
        self.assertContains(response, url)

    def test_claim_with_json_body_data(self):
        url = reverse("channels.types.externalv2.claim")
        self.login(self.admin)

        payload = {
            "user": self.admin.username,
            "org": str(self.org.uuid),
            "data": {
                "mo_response_content_type": "application/json",
                "mo_response": "",
                "mt_response_check": "",
                "send_url": "https://example.com/send_msg",
                "send_method": "POST",
                "send_template": {
                    "chat_id": "123",
                    "text": "5665",
                    "parse_mode": "Markdown",
                },
                "content_type": "application/x-www-form-urlencoded",
                "receive_template": {
                    "messages": [
                        {
                            "urn_path": "89898",
                            "text": "898989",
                            "contact_name": "89899",
                            "id": "1515",
                        }
                    ]
                },
                "send_authorization": "",
            },
            "channeltype_code": "E2",
        }

        response = self.client.post(url, data=json.dumps(payload), content_type="application/json", follow=True)

        channel = Channel.objects.filter(channel_type="E2").order_by("-id").first()
        self.assertIsNotNone(channel)
        self.assertRedirects(response, reverse("channels.channel_configuration", args=[channel.uuid]))
        self.assertEqual(channel.config, payload["data"])
        self.assertEqual(channel.schemes, ["ext"])

    def test_claim_with_form_encoded_data_json(self):
        url = reverse("channels.types.externalv2.claim")
        self.login(self.admin)

        data_obj = {
            "send_url": "https://example.com/send_msg",
            "send_method": "POST",
            "content_type": "application/json",
            "send_template": {"a": 1},
            "receive_template": {"messages": [{"id": "1", "text": "hi"}]},
        }

        form_payload = {
            "data": json.dumps(data_obj),
            "address": "",
            "name": "External API V2",
            "schemes": "ext",
        }

        response = self.client.post(url, data=form_payload, follow=True)

        channel = Channel.objects.filter(channel_type="E2").order_by("-id").first()
        self.assertIsNotNone(channel)
        self.assertRedirects(response, reverse("channels.channel_configuration", args=[channel.uuid]))
        self.assertEqual(channel.config, data_obj)

    def test_claim_with_explicit_config_field_precedence(self):
        url = reverse("channels.types.externalv2.claim")
        self.login(self.admin)

        explicit_config = {"keep": True, "nested": {"x": 1}}
        competing_data = {"keep": False, "other": 123}

        form_payload = {
            "config": json.dumps(explicit_config),
            "data": json.dumps(competing_data),
        }

        response = self.client.post(url, data=form_payload, follow=True)

        channel = Channel.objects.filter(channel_type="E2").order_by("-id").first()
        self.assertIsNotNone(channel)
        self.assertRedirects(response, reverse("channels.channel_configuration", args=[channel.uuid]))
        self.assertEqual(channel.config, explicit_config)
