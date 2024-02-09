import requests

from django.conf import settings

from temba.utils.whatsapp.interfaces import FacebookCatalog


class RequestsFacebookCatalog(FacebookCatalog):
    def get_facebook_catalogs(self, channel):
        waba_id = channel.config.get("wa_waba_id")
        wa_user_token = channel.config.get("wa_user_token")
        token = wa_user_token if wa_user_token else settings.WHATSAPP_ADMIN_SYSTEM_USER_TOKEN
        url = f"https://graph.facebook.com/v17.0/{waba_id}/product_catalogs"

        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(url, params=dict(limit=255), headers=headers)

        return response.json()


def get_actived_catalog(data: dict):
    json_data = data.get("data", [])
    if json_data and json_data[0].get("id"):
        return json_data[0].get("id")
