from django.urls import reverse

from temba.tests import TembaTest

from ...models import Ticketer
from .type import FreshchatType


class FreshchatTypeTest(TembaTest):
    def test_is_available_to(self):
        self.assertTrue(FreshchatType().is_available_to(self.admin))

    def test_connect(self):
        connect_url = reverse("tickets.types.freshchat.connect")

        response = self.client.get(connect_url)
        self.assertLoginRedirect(response)

        self.login(self.admin)

        response = self.client.get(connect_url)
        self.assertEqual(["oauth_token", "freshchat_domain", "loc"], list(response.context["form"].fields.keys()))

        # will fail as we don't have anything filled out
        response = self.client.post(connect_url, {})
        self.assertFormError(response, "form", None, ["OAuth Token is required", "Freshchat Domain is required"])

        # try with only oauth_token
        response = self.client.post(connect_url, {"oauth_token": "token123"})
        self.assertFormError(response, "form", None, ["Freshchat Domain is required"])

        # try with only freshchat_domain
        response = self.client.post(connect_url, {"freshchat_domain": "example.freshchat.com"})
        self.assertFormError(response, "form", None, ["OAuth Token is required"])

        # try with freshchat_domain already taken by this org
        Ticketer.create(
            self.org,
            self.admin,
            ticketer_type=FreshchatType.slug,
            name="Existing",
            config={"oauth_token": "token123", "freshchat_domain": "example.freshchat.com"},
        )
        response = self.client.post(
            connect_url, {"oauth_token": "token456", "freshchat_domain": "example.freshchat.com"}
        )
        self.assertFormError(
            response,
            "form",
            None,
            ["A Freshchat ticketer for this domain already exists in this workspace."],
        )

        # submitting with valid data should create ticketer and redirect
        response = self.client.post(connect_url, {"oauth_token": "token789", "freshchat_domain": "acme.freshchat.com"})

        ticketer = Ticketer.objects.filter(ticketer_type="freshchat", is_active=True).order_by("id").last()
        self.assertIsNotNone(ticketer)
        self.assertEqual("acme.freshchat.com", ticketer.name)
        self.assertEqual({"oauth_token": "token789", "freshchat_domain": "acme.freshchat.com"}, ticketer.config)
        self.assertRedirect(response, reverse("tickets.ticket_list"))

    def test_configure(self):
        ticketer = Ticketer.create(
            self.org,
            self.admin,
            ticketer_type=FreshchatType.slug,
            name="Example",
            config={"oauth_token": "token123", "freshchat_domain": "example.freshchat.com"},
        )

        configure_url = reverse("tickets.types.freshchat.configure", args=[ticketer.uuid])

        response = self.client.get(configure_url)
        self.assertLoginRedirect(response)

        self.login(self.admin)

        response = self.client.get(configure_url)
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "token123")
        self.assertContains(response, "example.freshchat.com")

        # Check if webhook_url is in context
        self.assertIn("webhook_url", response.context)
        webhook_url = response.context["webhook_url"]
        domain = self.org.get_brand_domain()
        expected_url = f"https://{domain}/mr/tickets/types/freshchat/webhook/{ticketer.uuid}"
        self.assertEqual(expected_url, webhook_url)
        self.assertContains(response, webhook_url)
