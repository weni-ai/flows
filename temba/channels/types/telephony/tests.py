from django.urls import reverse

from temba.tests import TembaTest

from ...models import Channel
from .type import CONFIG_AUTH_TOKEN, CONFIG_BASE_URL


class TelephonyPSTNTypeTest(TembaTest):
    def test_claim(self):
        Channel.objects.all().delete()
        self.login(self.admin)

        url = reverse("channels.types.telephony.claim")

        response = self.client.get(reverse("channels.channel_claim"))
        self.assertContains(response, url)

        data = {
            "name": "Support Line",
            "country": "US",
            "phone_number": "+15551234567",
            "base_url": "https://gateway.example.com",
            "auth_token": "secret-token",
        }

        response = self.client.post(url, data, follow=True)

        channel = Channel.objects.get(name="Support Line")

        self.assertEqual("TPH", channel.channel_type)
        self.assertEqual("+15551234567", channel.address)
        self.assertEqual("US", channel.country)
        self.assertEqual(["tel"], channel.schemes)
        self.assertEqual("https://gateway.example.com", channel.config[CONFIG_BASE_URL])
        self.assertEqual("secret-token", channel.config[CONFIG_AUTH_TOKEN])

        config_url = reverse("channels.channel_configuration", args=[channel.uuid])
        self.assertRedirect(response, config_url)

        response = self.client.get(config_url)
        self.assertEqual(200, response.status_code)
        self.assertContains(response, reverse("courier.tph"))
