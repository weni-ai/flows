from unittest.mock import patch
from uuid import uuid4

from django.urls import reverse

from temba.tests.base import TembaTest


class BillingPricingEndpointTest(TembaTest):
    def setUp(self):
        super().setUp()
        # Ensure org has a project UUID for lookup
        self.org.proj_uuid = uuid4()
        self.org.save()

    @patch("temba.api.v2.billing.views.BillingPricingEndpoint.authentication_classes", [])
    @patch("temba.api.v2.billing.views.BillingPricingEndpoint.permission_classes", [])
    @patch("temba.api.v2.billing.views.get_billing_pricing")
    def test_success_with_explicit_project_param(self, mock_get_pricing, *mocks):
        mock_get_pricing.return_value = {"currency": "USD", "rates": {"marketing": 0.05}}

        url = reverse("api.v2.billing_pricing")
        response = self.client.get(url, {"project_uuid": str(self.org.proj_uuid)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"currency": "USD", "rates": {"marketing": 0.05}})
        mock_get_pricing.assert_called_once_with(project=str(self.org.proj_uuid))

    @patch("temba.api.v2.billing.views.BillingPricingEndpoint.authentication_classes", [])
    @patch("temba.api.v2.billing.views.BillingPricingEndpoint.permission_classes", [])
    @patch("temba.api.v2.billing.views.get_billing_pricing")
    def test_success_with_project_from_query(self, mock_get_pricing, *mocks):
        mock_get_pricing.return_value = {"currency": "BRL", "rates": {"marketing": 0.12}}

        url = reverse("api.v2.billing_pricing")
        response = self.client.get(url, {"project_uuid": str(self.org.proj_uuid)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"currency": "BRL", "rates": {"marketing": 0.12}})
        mock_get_pricing.assert_called_once_with(project=str(self.org.proj_uuid))

    @patch("temba.api.v2.billing.views.BillingPricingEndpoint.authentication_classes", [])
    @patch("temba.api.v2.billing.views.BillingPricingEndpoint.permission_classes", [])
    @patch("temba.api.v2.billing.views.get_billing_pricing")
    def test_upstream_error_returns_502(self, mock_get_pricing, *mocks):
        from requests import RequestException

        mock_get_pricing.side_effect = RequestException("boom")

        url = reverse("api.v2.billing_pricing")
        response = self.client.get(url, {"project_uuid": str(self.org.proj_uuid)})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {})

    @patch("temba.api.v2.billing.views.BillingPricingEndpoint.authentication_classes", [])
    @patch("temba.api.v2.billing.views.BillingPricingEndpoint.permission_classes", [])
    @patch("temba.api.v2.billing.views.get_billing_pricing")
    def test_missing_project_param_returns_400(self, mock_get_pricing, *mocks):
        url = reverse("api.v2.billing_pricing")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        mock_get_pricing.assert_not_called()

    @patch("temba.api.v2.billing.views.BillingPricingEndpoint.authentication_classes", [])
    @patch("temba.api.v2.billing.views.BillingPricingEndpoint.permission_classes", [])
    @patch("temba.api.v2.billing.views.get_billing_pricing")
    def test_unknown_project_returns_404(self, mock_get_pricing, *mocks):
        unknown_proj = str(uuid4())

        url = reverse("api.v2.billing_pricing")
        response = self.client.get(url, {"project_uuid": unknown_proj})

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())
        mock_get_pricing.assert_not_called()
