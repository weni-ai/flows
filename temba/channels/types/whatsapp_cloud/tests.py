import json
from unittest.mock import call, patch

from requests import RequestException

from django.test import override_settings
from django.urls import reverse

from temba.request_logs.models import HTTPLog
from temba.templates.models import TemplateTranslation
from temba.tests import MockResponse, TembaTest
from temba.wpp_products.models import Catalog, Product

from ...models import Channel
from .type import WhatsAppCloudType


class WhatsAppCloudTypeTest(TembaTest):
    @override_settings(
        WHATSAPP_APPLICATION_ID="WAC_APP_ID",
        WHATSAPP_APPLICATION_SECRET="WAC_APP_SECRET",
        WHATSAPP_FACEBOOK_BUSINESS_ID="WAC_BUSINESS_ID",
    )
    def test_claim(self):
        Channel.objects.all().delete()
        self.login(self.admin)

        # remove any existing channels
        self.org.channels.update(is_active=False)

        connect_whatsapp_cloud_url = reverse("orgs.org_whatsapp_cloud_connect")
        claim_whatsapp_cloud_url = reverse("channels.types.whatsapp_cloud.claim")

        # make sure plivo is on the claim page
        response = self.client.get(reverse("channels.channel_claim"))
        self.assertEqual(200, response.status_code)
        self.assertNotContains(response, claim_whatsapp_cloud_url)

        with patch("requests.get") as wa_cloud_get:
            wa_cloud_get.return_value = MockResponse(400, {})
            response = self.client.get(claim_whatsapp_cloud_url)

            self.assertEqual(response.status_code, 302)

            response = self.client.get(claim_whatsapp_cloud_url, follow=True)

            self.assertEqual(response.request["PATH_INFO"], connect_whatsapp_cloud_url)

        with patch("requests.get") as wa_cloud_get:
            wa_cloud_get.side_effect = [
                MockResponse(400, {}),
                # missing permissions
                MockResponse(
                    200,
                    json.dumps({"data": {"scopes": []}}),
                ),
                # success
                MockResponse(
                    200,
                    json.dumps(
                        {
                            "data": {
                                "scopes": [
                                    "business_management",
                                    "whatsapp_business_management",
                                    "whatsapp_business_messaging",
                                ]
                            }
                        }
                    ),
                ),
                MockResponse(
                    200,
                    json.dumps(
                        {
                            "data": {
                                "scopes": [
                                    "business_management",
                                    "whatsapp_business_management",
                                    "whatsapp_business_messaging",
                                ]
                            }
                        }
                    ),
                ),
                MockResponse(
                    200,
                    json.dumps(
                        {
                            "data": {
                                "scopes": [
                                    "business_management",
                                    "whatsapp_business_management",
                                    "whatsapp_business_messaging",
                                ]
                            }
                        }
                    ),
                ),
            ]
            response = self.client.get(connect_whatsapp_cloud_url)
            self.assertEqual(response.status_code, 200)

            # 400 status
            response = self.client.post(connect_whatsapp_cloud_url, dict(user_access_token="X" * 36), follow=True)
            self.assertEqual(
                response.context["form"].errors["__all__"][0], "Sorry account could not be connected. Please try again"
            )

            # missing permissions
            response = self.client.post(connect_whatsapp_cloud_url, dict(user_access_token="X" * 36), follow=True)
            self.assertEqual(
                response.context["form"].errors["__all__"][0], "Sorry account could not be connected. Please try again"
            )

            response = self.client.post(connect_whatsapp_cloud_url, dict(user_access_token="X" * 36))
            self.assertTrue(Channel.CONFIG_WHATSAPP_CLOUD_USER_TOKEN in self.client.session)
            self.assertEqual(response.url, claim_whatsapp_cloud_url)

            response = self.client.post(connect_whatsapp_cloud_url, dict(user_access_token="X" * 36), follow=True)
            self.assertEqual(response.status_code, 200)

        # make sure the token is set on the session
        session = self.client.session
        session[Channel.CONFIG_WHATSAPP_CLOUD_USER_TOKEN] = "user-token"
        session.save()

        self.assertTrue(Channel.CONFIG_WHATSAPP_CLOUD_USER_TOKEN in self.client.session)

        with patch("requests.get") as wa_cloud_get:
            with patch("requests.post") as wa_cloud_post:
                wa_cloud_get.side_effect = [
                    # pre-process missing permissions
                    MockResponse(
                        200,
                        json.dumps(
                            {
                                "data": {
                                    "scopes": [
                                        "business_management",
                                        "whatsapp_business_messaging",
                                    ]
                                }
                            }
                        ),
                    ),
                ]

                response = self.client.get(claim_whatsapp_cloud_url, follow=True)

                self.assertFalse(Channel.CONFIG_WHATSAPP_CLOUD_USER_TOKEN in self.client.session)

        # make sure the token is set on the session
        session = self.client.session
        session[Channel.CONFIG_WHATSAPP_CLOUD_USER_TOKEN] = "user-token"
        session.save()

        self.assertTrue(Channel.CONFIG_WHATSAPP_CLOUD_USER_TOKEN in self.client.session)

        with patch("requests.get") as wa_cloud_get:
            with patch("requests.post") as wa_cloud_post:
                wa_cloud_get.side_effect = [
                    # pre-process for get
                    MockResponse(
                        200,
                        json.dumps(
                            {
                                "data": {
                                    "scopes": [
                                        "business_management",
                                        "whatsapp_business_management",
                                        "whatsapp_business_messaging",
                                    ]
                                }
                            }
                        ),
                    ),
                    # getting target waba
                    MockResponse(
                        200,
                        json.dumps(
                            {
                                "data": {
                                    "granular_scopes": [
                                        {
                                            "scope": "business_management",
                                            "target_ids": [
                                                "2222222222222",
                                            ],
                                        },
                                        {
                                            "scope": "whatsapp_business_management",
                                            "target_ids": [
                                                "111111111111111",
                                            ],
                                        },
                                        {
                                            "scope": "whatsapp_business_messaging",
                                            "target_ids": [
                                                "111111111111111",
                                            ],
                                        },
                                    ]
                                }
                            }
                        ),
                    ),
                    # getting waba details
                    MockResponse(
                        200,
                        json.dumps(
                            {
                                "id": "111111111111111",
                                "currency": "USD",
                                "message_template_namespace": "namespace-uuid",
                                "on_behalf_of_business_info": {"id": "2222222222222"},
                            }
                        ),
                    ),
                    # getting waba phone numbers
                    MockResponse(
                        200,
                        json.dumps(
                            {
                                "data": [
                                    {"id": "123123123", "display_phone_number": "1234", "verified_name": "WABA name"}
                                ]
                            }
                        ),
                    ),
                    # pre-process for post
                    MockResponse(
                        200,
                        json.dumps(
                            {
                                "data": {
                                    "scopes": [
                                        "business_management",
                                        "whatsapp_business_management",
                                        "whatsapp_business_messaging",
                                    ]
                                }
                            }
                        ),
                    ),
                    # getting te credit line ID
                    MockResponse(200, json.dumps({"data": [{"id": "567567567"}]})),
                ]

                wa_cloud_post.return_value = MockResponse(200, json.dumps({"success": "true"}))

                response = self.client.get(claim_whatsapp_cloud_url, follow=True)

                self.assertEqual(len(response.context["phone_numbers"]), 1)
                self.assertEqual(response.context["phone_numbers"][0]["waba_id"], "111111111111111")
                self.assertEqual(response.context["phone_numbers"][0]["phone_number_id"], "123123123")
                self.assertEqual(response.context["phone_numbers"][0]["business_id"], "2222222222222")
                self.assertEqual(response.context["phone_numbers"][0]["currency"], "USD")
                self.assertEqual(response.context["phone_numbers"][0]["verified_name"], "WABA name")

                post_data = response.context["form"].initial
                post_data["number"] = "1234"
                post_data["verified_name"] = "WABA name"
                post_data["phone_number_id"] = "123123123"
                post_data["waba_id"] = "111111111111111"
                post_data["business_id"] = "2222222222222"
                post_data["currency"] = "USD"
                post_data["message_template_namespace"] = "namespace-uuid"

                response = self.client.post(claim_whatsapp_cloud_url, post_data, follow=True)
                self.assertEqual(200, response.status_code)

                self.assertFalse(Channel.CONFIG_WHATSAPP_CLOUD_USER_TOKEN in self.client.session)

                self.assertEqual(3, wa_cloud_post.call_count)

                channel = Channel.objects.get()

                self.assertEqual("WABA name", channel.name)
                self.assertEqual("123123123", channel.address)
                self.assertEqual("WAC", channel.channel_type)
                self.assertTrue(channel.get_type().has_attachment_support(channel))

                self.assertEqual("1234", channel.config["wa_number"])
                self.assertEqual("WABA name", channel.config["wa_verified_name"])
                self.assertEqual("111111111111111", channel.config["wa_waba_id"])
                self.assertEqual("USD", channel.config["wa_currency"])
                self.assertEqual("2222222222222", channel.config["wa_business_id"])
                self.assertEqual("namespace-uuid", channel.config["wa_message_template_namespace"])

    @override_settings(WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="WA_ADMIN_TOKEN")
    @patch("requests.get")
    def test_get_api_templates(self, mock_get):
        TemplateTranslation.objects.all().delete()
        Channel.objects.all().delete()

        channel = self.create_channel(
            "WAC",
            "WABA name",
            "123123123",
            config={
                "wa_waba_id": "111111111111111",
            },
        )

        mock_get.side_effect = [
            RequestException("Network is unreachable", response=MockResponse(100, "")),
            MockResponse(400, '{ "meta": { "success": false } }'),
            MockResponse(200, '{"data": ["foo", "bar"]}'),
            MockResponse(
                200,
                '{"data": ["foo"], "paging": {"cursors": {"after": "MjQZD"}, "next": "https://graph.facebook.com/v16.0/111111111111111/message_templates?after=MjQZD" } }',
            ),
            MockResponse(200, '{"data": ["bar"], "paging": {"cursors": {"after": "MjQZD"} } }'),
        ]

        # RequestException check HTTPLog
        templates_data, no_error = WhatsAppCloudType().get_api_templates(channel)
        self.assertEqual(1, HTTPLog.objects.filter(log_type=HTTPLog.WHATSAPP_TEMPLATES_SYNCED).count())
        self.assertFalse(no_error)
        self.assertEqual([], templates_data)

        # should be empty list with an error flag if fail with API
        templates_data, no_error = WhatsAppCloudType().get_api_templates(channel)
        self.assertFalse(no_error)
        self.assertEqual([], templates_data)

        # success no error and list
        templates_data, no_error = WhatsAppCloudType().get_api_templates(channel)
        self.assertTrue(no_error)
        self.assertEqual(["foo", "bar"], templates_data)

        mock_get.assert_called_with(
            "https://graph.facebook.com/v16.0/111111111111111/message_templates",
            params={"limit": 255},
            headers={"Authorization": "Bearer WA_ADMIN_TOKEN"},
        )

        # success no error and pagination
        templates_data, no_error = WhatsAppCloudType().get_api_templates(channel)
        self.assertTrue(no_error)
        self.assertEqual(["foo", "bar"], templates_data)

        mock_get.assert_has_calls(
            [
                call(
                    "https://graph.facebook.com/v16.0/111111111111111/message_templates",
                    params={"limit": 255},
                    headers={"Authorization": "Bearer WA_ADMIN_TOKEN"},
                ),
                call(
                    "https://graph.facebook.com/v16.0/111111111111111/message_templates?after=MjQZD",
                    params={"limit": 255},
                    headers={"Authorization": "Bearer WA_ADMIN_TOKEN"},
                ),
            ]
        )

    @override_settings(WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="WA_ADMIN_TOKEN")
    @patch("requests.get")
    def test_get_api_catalogs(self, mock_get):
        Catalog.objects.all().delete()
        Channel.objects.all().delete()

        channel = self.create_channel(
            "WAC",
            "WABA name",
            "123123123",
            config={
                "wa_waba_id": "111111111111111",
                "wa_business_id": "333333333333",
            },
        )

        mock_get.side_effect = [
            RequestException("Network is unreachable", response=MockResponse(100, "")),
            MockResponse(400, '{ "meta": { "success": false } }'),
            MockResponse(200, '{"data": ["foo", "bar"]}'),
            MockResponse(
                200,
                '{"data": ["foo"], "paging": {"cursors": {"after": "MjQZD"}, "next": "https://graph.facebook.com/v16.0/333333333333/owned_product_catalogs?after=MjQZD" } }',
            ),
            MockResponse(200, '{"data": ["bar"], "paging": {"cursors": {"after": "MjQZD"} } }'),
        ]

        # RequestException check HTTPLog
        categories_data, no_error = WhatsAppCloudType().get_api_catalogs(channel)

        self.assertEqual(1, HTTPLog.objects.filter(log_type=HTTPLog.WHATSAPP_CATALOGS_SYNCED).count())
        self.assertFalse(no_error)
        self.assertEqual([], categories_data)

        # should be empty list with an error flag if fail with API
        categories_data, no_error = WhatsAppCloudType().get_api_catalogs(channel)
        self.assertFalse(no_error)
        self.assertEqual([], categories_data)

        # success no error and list
        categories_data, no_error = WhatsAppCloudType().get_api_catalogs(channel)
        self.assertTrue(no_error)
        self.assertEqual(["foo", "bar"], categories_data)

        mock_get.assert_called_with(
            "https://graph.facebook.com/v16.0/333333333333/owned_product_catalogs",
            params={"limit": 255},
            headers={"Authorization": "Bearer WA_ADMIN_TOKEN"},
        )

        # success no error and pagination
        categories_data, no_error = WhatsAppCloudType().get_api_catalogs(channel)
        self.assertTrue(no_error)
        self.assertEqual(["foo", "bar"], categories_data)

        mock_get.assert_has_calls(
            [
                call(
                    "https://graph.facebook.com/v16.0/333333333333/owned_product_catalogs",
                    params={"limit": 255},
                    headers={"Authorization": "Bearer WA_ADMIN_TOKEN"},
                ),
                call(
                    "https://graph.facebook.com/v16.0/333333333333/owned_product_catalogs?after=MjQZD",
                    params={"limit": 255},
                    headers={"Authorization": "Bearer WA_ADMIN_TOKEN"},
                ),
            ]
        )

    @override_settings(WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="WA_ADMIN_TOKEN")
    @patch("requests.get")
    def test_get_api_produtcs(self, mock_get):
        Product.objects.all().delete()
        Catalog.objects.all().delete()
        Channel.objects.all().delete()

        channel = self.create_channel(
            "WAC",
            "WABA name",
            "123123123",
            config={
                "wa_waba_id": "111111111111111",
                "wa_business_id": "333333333333",
            },
        )

        catalog = Catalog(
            facebook_catalog_id="12345",
            name="Test Catalog",
            org=self.org,
            channel=self.channel,
        )

        mock_get.side_effect = [
            RequestException("Network is unreachable", response=MockResponse(100, "")),
            MockResponse(400, '{ "meta": { "success": false } }'),
            MockResponse(200, '{"data": ["foo", "bar"]}'),
            MockResponse(
                200,
                '{"data": ["foo"], "paging": {"cursors": {"after": "MjQZD"}, "next": "https://graph.facebook.com/v16.0/111111111111111/products?after=MjQZD" } }',
            ),
            MockResponse(200, '{"data": ["bar"], "paging": {"cursors": {"after": "MjQZD"} } }'),
        ]

        # RequestException check HTTPLog
        products_data, no_error = WhatsAppCloudType().get_api_products(channel, catalog)
        self.assertEqual(1, HTTPLog.objects.filter(log_type=HTTPLog.WHATSAPP_PRODUCTS_SYNCED).count())
        self.assertFalse(no_error)
        self.assertEqual([], products_data)

        # should be empty list with an error flag if fail with API
        products_data, no_error = WhatsAppCloudType().get_api_products(channel, catalog)
        self.assertFalse(no_error)
        self.assertEqual([], products_data)

        # success no error and list
        products_data, no_error = WhatsAppCloudType().get_api_products(channel, catalog)
        self.assertTrue(no_error)
        self.assertEqual(["foo", "bar"], products_data)

        mock_get.assert_called_with(
            "https://graph.facebook.com/v16.0/12345/products",
            params={"limit": 255},
            headers={"Authorization": "Bearer WA_ADMIN_TOKEN"},
        )

        # success no error and pagination
        products_data, no_error = WhatsAppCloudType().get_api_products(channel, catalog)
        self.assertTrue(no_error)
        self.assertEqual(["foo", "bar"], products_data)

        """mock_get.assert_has_calls(
            [
                call(
                    "https://graph.facebook.com/v16.0/12345/products",
                    params={"limit": 255},
                    headers={"Authorization": "Bearer WA_ADMIN_TOKEN"},
                ),
                call(
                    "https://graph.facebook.com/v16.0/12345/products?after=MjQZD",
                    params={"limit": 255},
                    headers={"Authorization": "Bearer WA_ADMIN_TOKEN"},
                ),
            ]
        )
"""
