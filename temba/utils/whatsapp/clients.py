import requests

from django.conf import settings

from temba.utils.whatsapp.interfaces import FacebookCatalog


class RequestsFacebookCatalog(FacebookCatalog):
    def get_facebook_catalogs(self, waba_id):
        url = f"https://graph.facebook.com/v17.0/{waba_id}/product_catalogs"

        headers = {"Authorization": f"Bearer {settings.WHATSAPP_ADMIN_SYSTEM_USER_TOKEN}"}
        response = requests.get(url, params=dict(limit=255), headers=headers)

        return response.json()


def get_actived_catalog(data: dict):
    json_data = data.get("data", [])
    if json_data and json_data[0].get("id"):
        return json_data[0].get("id")
