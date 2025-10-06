import logging

import requests
from weni.internal.clients.base import BaseInternalClient

from django.conf import settings

from temba.templates.models import Template

logger = logging.getLogger(__name__)

CATEGORY_TO_BILLING_FIELD = {
    "MARKETING": "marketing",
    "UTILITY": "utility",
    "AUTHENTICATION": "authentication",
    "SERVICE": "service",
}


class BillingInternalClient(BaseInternalClient):
    def __init__(self, base_url=None, authenticator=None):
        base_url = base_url or getattr(settings, "BILLING_BASE_URL", None)
        super().__init__(base_url=base_url, authenticator=authenticator)

    def get_pricing(self, project=None):
        params = {}
        if project:
            params["project"] = project
        response = requests.get(
            self.get_url("/api/v1/meta-pricing/"), headers=self.authenticator.headers, params=params, timeout=10
        )
        response.raise_for_status()
        return response.json()


def get_billing_pricing(project: str = None):
    """
    Lightweight service to fetch pricing data directly from Billing.
    Acts as a thin proxy with no additional transformation to avoid duplication.
    """
    client = BillingInternalClient()
    return client.get_pricing(project=project)


def get_template_price_and_currency_from_api(template_id=None):
    """
    Search for the template price and currency in the external pricing API.
    Returns (template_price, currency). If it fails, returns (0, 'BRL').
    If template_id is provided, uses its category to select the correct price field.
    """
    try:
        client = BillingInternalClient()
        template_price = 0
        if template_id:
            try:
                template = Template.objects.get(pk=template_id)
                project_uuid = template.org.proj_uuid
                data = client.get_pricing(project=project_uuid)
                currency = data.get("currency", "BRL")
                category = template.category
                if category not in CATEGORY_TO_BILLING_FIELD:
                    logger.warning(f"Category {category} not mapped to billing. Using 'marketing' as fallback.")
                billing_field = CATEGORY_TO_BILLING_FIELD.get(category, "marketing")
                template_price = float(data.get("rates", {}).get(billing_field, 0))
            except Template.DoesNotExist:
                template_price = float(data.get("marketing", 0))
        else:
            template_price = float(data.get("marketing", 0))
        return template_price, currency
    except Exception:
        return 0, "BRL"
