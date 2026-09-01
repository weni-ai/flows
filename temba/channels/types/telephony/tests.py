from unittest.mock import patch

from django.urls import reverse

from temba.tests import TembaTest

from ...models import Channel
from .type import CONFIG_AUTH_TOKEN, CONFIG_BASE_URL


class TelephonyPSTNTypeTest(TembaTest):
    def _claim_url(self):
        return reverse("channels.types.telephony.claim")

    def _post_claim(self, post_data):
        with patch("socket.gethostbyname", return_value="8.8.8.8"):
            return self.client.post(self._claim_url(), post_data)

    def test_claim(self):
        Channel.objects.all().delete()
        self.login(self.admin)

        response = self.client.get(reverse("channels.channel_claim"))
        self.assertContains(response, self._claim_url())

        post_data = {
            "name": "Support Line",
            "country": "US",
            "phone_number": "+12065551212",
            "base_url": "https://google.com",
            "auth_token": "secret-token",
        }

        # FR-005: invalid DIDs must be rejected before channel creation
        response = self._post_claim({**post_data, "phone_number": "404-123-4567"})
        self.assertFormError(response, "form", "phone_number", "Invalid phone number")
        self.assertFalse(Channel.objects.exists())

        # US1: valid claim creates TPH channel with tel scheme and E.164 DID as address
        response = self._post_claim(post_data)
        self.assertEqual(302, response.status_code)

        channel = Channel.objects.get(name="Support Line")

        self.assertEqual("TPH", channel.channel_type)
        self.assertEqual("+12065551212", channel.address)
        self.assertEqual("US", channel.country)
        self.assertEqual(["tel"], channel.schemes)
        self.assertEqual("https://google.com", channel.config[CONFIG_BASE_URL])
        self.assertEqual("secret-token", channel.config[CONFIG_AUTH_TOKEN])

        read_url = reverse("channels.channel_read", args=[channel.uuid])
        self.assertRedirect(response, read_url)

        # US3: configuration shows Courier receive URL for gateway setup
        config_url = reverse("channels.channel_configuration", args=[channel.uuid])
        response = self.client.get(config_url)
        self.assertEqual(200, response.status_code)
        self.assertContains(response, reverse("courier.tph"))

    def test_claim_normalizes_national_format_number(self):
        Channel.objects.all().delete()
        self.login(self.admin)

        post_data = {
            "name": "Support Line",
            "country": "US",
            "phone_number": "206-555-1212",
            "base_url": "https://google.com",
        }

        response = self._post_claim(post_data)
        self.assertEqual(302, response.status_code)

        channel = Channel.objects.get(name="Support Line")
        self.assertEqual("+12065551212", channel.address)
