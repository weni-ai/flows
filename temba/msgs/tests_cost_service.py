from unittest.mock import MagicMock, patch
from uuid import uuid4

from temba.msgs.cost_service import (
    BillingInternalClient,
    get_billing_pricing,
    get_template_price_and_currency_from_api,
)
from temba.templates.models import Template
from temba.tests.base import TembaTest


class BillingInternalClientTest(TembaTest):
    def setUp(self):
        super().setUp()

        # authenticator stub with headers expected by get_pricing
        self.authenticator = type("Auth", (), {"headers": {"Authorization": "Token abc"}})()
        self.client = BillingInternalClient(base_url="https://billing.example", authenticator=self.authenticator)

    def test_get_pricing_without_project(self):
        with patch.object(self.client, "get_url", return_value="https://billing.example/api/v1/meta-pricing/"):
            with patch("temba.msgs.cost_service.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.json.return_value = {"currency": "USD"}
                mock_get.return_value = mock_response

                result = self.client.get_pricing()

                mock_get.assert_called_once_with(
                    "https://billing.example/api/v1/meta-pricing/",
                    headers=self.authenticator.headers,
                    params={},
                    timeout=10,
                )
                mock_response.raise_for_status.assert_called_once()
                self.assertEqual(result, {"currency": "USD"})

    def test_get_pricing_with_project(self):
        with patch.object(self.client, "get_url", return_value="https://billing.example/api/v1/meta-pricing/"):
            with patch("temba.msgs.cost_service.requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.json.return_value = {"currency": "USD"}
                mock_get.return_value = mock_response

                project = "abcd-123"
                self.client.get_pricing(project=project)

                # verify params and headers forwarded
                called_kwargs = mock_get.call_args.kwargs
                self.assertEqual(called_kwargs["params"], {"project": project})
                self.assertEqual(called_kwargs["headers"], self.authenticator.headers)


class GetTemplatePriceFromApiTest(TembaTest):
    def setUp(self):
        super().setUp()
        # Ensure org has proj_uuid used by the pricing API
        self.org.proj_uuid = uuid4()
        self.org.save(update_fields=("proj_uuid",))

    def test_happy_path_uses_category_mapped_rate(self):
        template = Template.objects.create(org=self.org, name="T1", category="UTILITY")

        with patch("temba.msgs.cost_service.BillingInternalClient") as MockClient:
            instance = MockClient.return_value
            instance.get_pricing.return_value = {
                "currency": "USD",
                "rates": {"utility": 1.23, "marketing": 2.00},
            }

            price, currency = get_template_price_and_currency_from_api(template_id=template.id)

            self.assertEqual(price, 1.23)
            self.assertEqual(currency, "USD")

    def test_category_not_mapped_falls_back_to_marketing(self):
        template = Template.objects.create(org=self.org, name="T2", category="TRANSACTIONAL")

        with patch("temba.msgs.cost_service.BillingInternalClient") as MockClient, self.assertLogs(
            "temba.msgs.cost_service", level="WARNING"
        ) as cm:
            instance = MockClient.return_value
            instance.get_pricing.return_value = {"currency": "EUR", "rates": {"marketing": 0.78}}

            price, currency = get_template_price_and_currency_from_api(template_id=template.id)

            self.assertEqual(price, 0.78)
            self.assertEqual(currency, "EUR")
            self.assertTrue(any("not mapped" in msg for msg in cm.output))

    def test_error_returns_defaults(self):
        # Non-existent template id should trigger default fallback (0, 'BRL')
        with patch("temba.msgs.cost_service.BillingInternalClient") as MockClient:
            instance = MockClient.return_value
            instance.get_pricing.return_value = {"currency": "USD", "rates": {"marketing": 2.00}}

            self.assertEqual(get_template_price_and_currency_from_api(template_id=999999), (0, "BRL"))

    def test_no_template_id_returns_defaults_due_to_missing_data(self):
        # Current implementation references `data` when template_id is None, which falls back
        # to the default (0, 'BRL') via the broad exception handler.
        with patch("temba.msgs.cost_service.BillingInternalClient") as MockClient:
            instance = MockClient.return_value
            instance.get_pricing.return_value = {
                "currency": "COP",
                "rates": {"marketing": 3.14},
                "marketing": 3.14,  # defensive, in case code path reads flat key
            }

            self.assertEqual(get_template_price_and_currency_from_api(), (0, "BRL"))


class GetBillingPricingTest(TembaTest):
    def test_delegates_to_client_with_project(self):
        with patch("temba.msgs.cost_service.BillingInternalClient") as MockClient:
            instance = MockClient.return_value
            instance.get_pricing.return_value = {"currency": "USD"}

            result = get_billing_pricing(project="proj-123")

            self.assertEqual(result, {"currency": "USD"})
            instance.get_pricing.assert_called_once_with(project="proj-123")
