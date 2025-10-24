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
            "name": "Custom E2 Name",
            "schemes": ["ext"],
            "address": "",
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
        self.assertEqual(channel.name, "Custom E2 Name")

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
            "name": "E2 form name",
            "schemes": "ext",
        }

        response = self.client.post(url, data=form_payload, follow=True)

        channel = Channel.objects.filter(channel_type="E2").order_by("-id").first()
        self.assertIsNotNone(channel)
        self.assertRedirects(response, reverse("channels.channel_configuration", args=[channel.uuid]))
        self.assertEqual(channel.config, data_obj)
        self.assertEqual(channel.name, "E2 form name")

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

    def test_claim_with_form_bracket_notation_and_lists(self):
        url = reverse("channels.types.externalv2.claim")
        self.login(self.admin)

        # Simulate fields like receive_template[messages][0][id], etc.
        form_payload = {
            "receive_template[messages][0][id]": "1515",
            "receive_template[messages][0][text]": "hi",
            "receive_template[messages][0][urn_path]": "123",
            "send_template[chat_id]": "123",
            "send_template[text]": "5665",
            "send_template[parse_mode]": "Markdown",
            "send_method": "POST",
            "send_url": "https://example.com/send_msg",
            "content_type": "application/json",
            # multipart values (multi-select style)
            "extra_list": ["a", "b", ""],
        }

        response = self.client.post(url, data=form_payload, follow=True)

        channel = Channel.objects.filter(channel_type="E2").order_by("-id").first()
        self.assertIsNotNone(channel)
        self.assertRedirects(response, reverse("channels.channel_configuration", args=[channel.uuid]))
        # Validate nested reconstruction
        expected_receive = {
            "messages": [
                {"id": "1515", "text": "hi", "urn_path": "123"},
            ]
        }
        self.assertEqual(channel.config["receive_template"], expected_receive)
        self.assertEqual(channel.config["send_template"], {"chat_id": "123", "text": "5665", "parse_mode": "Markdown"})
        self.assertEqual(channel.config["extra_list"], ["a", "b"])  # empty value filtered out

    def test_claim_invalid_config_json(self):
        url = reverse("channels.types.externalv2.claim")
        self.login(self.admin)

        # Invalid JSON in config should show form error
        form_payload = {"config": "{invalid json]"}
        response = self.client.post(url, data=form_payload)
        self.assertContains(response, "Invalid JSON")

    def test_claim_config_json_must_be_object(self):
        url = reverse("channels.types.externalv2.claim")
        self.login(self.admin)

        # Valid JSON but not an object (list)
        form_payload = {"config": json.dumps([1, 2, 3])}
        response = self.client.post(url, data=form_payload)
        self.assertContains(response, "JSON must be an object")

        # Valid JSON but not an object (string)
        form_payload = {"config": json.dumps("hello")}
        response = self.client.post(url, data=form_payload)
        self.assertContains(response, "JSON must be an object")

    def test_claim_form_encoded_data_literal_eval_fallback(self):
        url = reverse("channels.types.externalv2.claim")
        self.login(self.admin)

        # Send data with single quotes (invalid JSON) but valid Python literal
        data_literal = "{'send_url': 'https://example.com/send', 'send_method': 'POST', 'nested': {'x': 1}}"
        form_payload = {
            "data": data_literal,
            "schemes": "ext",
            "address": "",
            "name": "External API V2",
        }

        response = self.client.post(url, data=form_payload, follow=True)

        channel = Channel.objects.filter(channel_type="E2").order_by("-id").first()
        self.assertIsNotNone(channel)
        self.assertRedirects(response, reverse("channels.channel_configuration", args=[channel.uuid]))
        self.assertEqual(
            channel.config,
            {"send_url": "https://example.com/send", "send_method": "POST", "nested": {"x": 1}},
        )
