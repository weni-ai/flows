from django.conf import settings
from django.urls import reverse

from temba.channels.models import Channel
from temba.tests.base import TembaTest


class EmailTypeTest(TembaTest):
    def test_claim(self):
        claim_url = reverse("channels.types.email.claim")

        self.login(self.admin)

        response = self.client.get(reverse("channels.channel_claim"))
        self.assertContains(response, claim_url)

        response = self.client.get(claim_url)
        self.assertEqual(200, response.status_code)

        response = self.client.post(
            claim_url,
            {
                "username": "email@gmail.com",
                "password": "*******",
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "imap_host": "imap.gmail.com",
                "imap_port": 993,
                "access_token": "token",
                "refresh_token": "refresh_token",
            },
            follow=True,
        )
        self.assertEqual(200, response.status_code)

        channel = Channel.objects.get(channel_type="EM")
        self.assertEqual("email@gmail.com", channel.name)
        self.assertEqual("email@gmail.com", channel.address)
        self.assertEqual(
            {
                "username": "email@gmail.com",
                "password": "*******",
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "imap_host": "imap.gmail.com",
                "imap_port": 993,
                "loc": "",
                "access_token": "token",
                "refresh_token": "refresh_token",
                "callback_domain": settings.HOSTNAME,
            },
            channel.config,
        )
