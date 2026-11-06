import base64
import hashlib
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connections
from django.test import override_settings
from django.urls import reverse

from temba.channels.models import Channel
from temba.channels.types.email import outlook
from temba.orgs.models import Org
from temba.tests.base import TembaNonAtomicTest, TembaTest

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

microsoft_app = override_settings(APP_MICROSOFT_CLIENT_ID="app-id", APP_MICROSOFT_CLIENT_SECRET="app-secret")


class _JsonResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def _access_token(mailbox=None, claim="upn", audience=outlook.OUTLOOK_AUDIENCE):
    payload = {
        "aud": audience,
        "iss": "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0",
        "exp": int(time.time()) + 3600,
    }
    if claim and mailbox:
        payload[claim] = mailbox
    return jwt.encode(payload, _PRIVATE_KEY, algorithm="RS256")


def _patch_jwks():
    client = MagicMock()
    client.get_signing_key_from_jwt.return_value = SimpleNamespace(key=_PUBLIC_KEY)
    return patch("temba.channels.types.email.outlook.jwt.PyJWKClient", return_value=client)


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

    def test_outlook_attempt_is_one_time(self):
        with patch("temba.channels.types.email.outlook.cache.set", wraps=cache.set) as cache_set:
            state = outlook.put_attempt(self.org.id, self.admin.id, "a@b.com", "verifier")

        self.assertEqual(outlook.CONSENT_ATTEMPT_TTL_SECONDS, cache_set.call_args[0][2])
        self.assertTrue(cache_set.call_args[0][0].startswith("outlook-email-consent:"))
        self.assertEqual("a@b.com", outlook.pop_attempt(state)["username"])
        self.assertIsNone(outlook.pop_attempt(state))

    def test_outlook_hidden_without_client_id(self):
        self.login(self.admin)
        claim_url = reverse("channels.types.email.claim")
        start_url = reverse("channels.types.email.outlook_start")

        response = self.client.get(claim_url)
        self.assertNotContains(response, start_url)

        response = self.client.post(start_url, {"username": "user@outlook.com"})
        self.assertRedirect(response, claim_url)
        self.assertFalse(Channel.objects.filter(channel_type="EM").exists())

    @microsoft_app
    def test_outlook_mailbox_label_focuses_the_field(self):
        self.login(self.admin)
        response = self.client.get(reverse("channels.types.email.claim"))
        html = response.content.decode()
        self.assertRegex(html, r"<label[^>]*for=['\"]outlook-mailbox['\"]")
        self.assertRegex(html, r"<input[^>]*name=['\"]username['\"][^>]*id=['\"]outlook-mailbox['\"]")

    @microsoft_app
    def test_outlook_rejects_blank_or_non_email(self):
        self.login(self.admin)
        start_url = reverse("channels.types.email.outlook_start")
        for value in ("", "   ", "not-an-email"):
            with patch("temba.channels.types.email.outlook.cache.set") as cache_set:
                response = self.client.post(start_url, {"username": value}, follow=True)
            self.assertEqual(0, cache_set.call_count)
            self.assertNotContains(response, "login.microsoftonline.com")
            self.assertContains(response, "Enter the mailbox address.")
        self.assertFalse(Channel.objects.filter(channel_type="EM").exists())

    @microsoft_app
    def test_outlook_consent_creates_channel_for_work_and_outlook_com(self):
        self.login(self.admin)
        cases = (
            (" User@Contoso.com ", "user@contoso.com", "upn", "refresh-work"),
            ("user@outlook.com", "user@outlook.com", "preferred_username", "refresh-outlook"),
        )
        for typed, address, claim, refresh in cases:
            self._assert_connected(typed, address, claim, refresh)

        self.assertEqual(2, Channel.objects.filter(channel_type="EM").count())

    @microsoft_app
    def test_outlook_rejects_a_different_mailbox(self):
        self.login(self.admin)
        query = self._start("user@contoso.com")
        token = _access_token("other@contoso.com")
        with self.assertLogs("temba.channels.types.email.outlook", level="INFO") as logs:
            response, posted = self._finish(query, token, refresh="refresh-other", follow=True)

        self.assertContains(response, "An alias cannot be connected.")
        self.assertNotContains(response, token)
        self.assertNotContains(response, "refresh-other")
        joined = "\n".join(logs.output)
        self.assertIn("error=mailbox_mismatch", joined)
        self.assertNotIn("user@contoso.com", joined)
        self.assertNotIn("other@contoso.com", joined)
        self.assertNotIn("auth-code", joined)
        self.assertEqual(1, posted.call_count)
        self.assertFalse(Channel.objects.filter(channel_type="EM").exists())

    @microsoft_app
    def test_outlook_rejects_a_non_outlook_audience(self):
        self.login(self.admin)
        query = self._start("user@contoso.com")
        token = _access_token("user@contoso.com", audience="https://graph.microsoft.com")
        response, posted = self._finish(query, token, follow=True)
        self.assertContains(response, "Microsoft did not complete the sign-in.")
        self.assertEqual(1, posted.call_count)
        self.assertFalse(Channel.objects.filter(channel_type="EM").exists())

    @microsoft_app
    def test_outlook_access_denied(self):
        self.login(self.admin)
        query = self._start("user@contoso.com")
        with self.assertLogs("temba.channels.types.email.outlook", level="INFO") as logs:
            response = self.client.get(
                reverse("channels.types.email.outlook_callback"),
                {"error": "access_denied", "state": query["state"][0]},
                follow=True,
            )
        self.assertContains(response, "Sign in was not completed. You can try again.")
        self.assertIn("error=access_denied", "\n".join(logs.output))
        self.assertIsNone(cache.get(outlook.attempt_key(query["state"][0])))
        self.assertFalse(Channel.objects.filter(channel_type="EM").exists())

    @microsoft_app
    def test_outlook_admin_consent(self):
        self.login(self.admin)
        cases = (
            {"error": "consent_required"},
            {
                "error": "interaction_required",
                "error_description": "AADSTS65001 user@contoso.com has not consented",
            },
        )
        for params in cases:
            query = self._start("user@contoso.com")
            params = dict(params, state=query["state"][0])
            with self.assertLogs("temba.channels.types.email.outlook", level="INFO") as logs:
                response = self.client.get(reverse("channels.types.email.outlook_callback"), params, follow=True)
            self.assertContains(response, "https://login.microsoftonline.com/common/adminconsent?client_id=app-id")
            self.assertContains(response, "administrator must approve this app")
            self.assertNotContains(response, "user@contoso.com")
            joined = "\n".join(logs.output)
            self.assertNotIn("user@contoso.com", joined)
            self.assertNotIn("AADSTS65001", joined)
        self.assertFalse(Channel.objects.filter(channel_type="EM").exists())

    @microsoft_app
    def test_outlook_shows_other_error_without_logging_description(self):
        self.login(self.admin)
        query = self._start("user@contoso.com")
        description = "mailbox user@contoso.com was rejected"
        with self.assertLogs("temba.channels.types.email.outlook", level="INFO") as logs:
            response = self.client.get(
                reverse("channels.types.email.outlook_callback"),
                {"error": "server_error", "error_description": description, "state": query["state"][0]},
                follow=True,
            )
        self.assertContains(response, description)
        self.assertNotContains(response, "adminconsent")
        joined = "\n".join(logs.output)
        self.assertIn("error=server_error", joined)
        self.assertNotIn(description, joined)
        self.assertNotIn("user@contoso.com", joined)
        self.assertFalse(Channel.objects.filter(channel_type="EM").exists())

    @microsoft_app
    def test_outlook_unknown_state(self):
        self.login(self.admin)
        with self.assertLogs("temba.channels.types.email.outlook", level="INFO") as logs:
            response = self.client.get(
                reverse("channels.types.email.outlook_callback"),
                {"code": "auth-code-secret", "state": "missing-state"},
                follow=True,
            )
        self.assertContains(response, "Sign in again to connect the mailbox.")
        joined = "\n".join(logs.output)
        self.assertIn("error=state", joined)
        self.assertNotIn("auth-code-secret", joined)
        self.assertFalse(Channel.objects.filter(channel_type="EM").exists())

    @microsoft_app
    def test_outlook_user_or_org_mismatch(self):
        self.login(self.admin)
        for field, value in (("user_id", self.user.id), ("org_id", self.org2.id)):
            query = self._start("user@contoso.com")
            key = outlook.attempt_key(query["state"][0])
            payload = cache.get(key)
            payload[field] = value
            cache.set(key, payload, outlook.CONSENT_ATTEMPT_TTL_SECONDS)
            response = self.client.get(
                reverse("channels.types.email.outlook_callback"),
                {"code": "auth-code-secret", "state": query["state"][0]},
                follow=True,
            )
            self.assertContains(response, "Sign in again to connect the mailbox.")
            self.assertIsNone(cache.get(key))
        self.assertFalse(Channel.objects.filter(channel_type="EM").exists())

    @microsoft_app
    def test_outlook_viewer_cannot_consent(self):
        start_url = reverse("channels.types.email.outlook_start")
        self.login(self.user)
        response = self.client.post(start_url, {"username": "user@outlook.com"})
        self.assertLoginRedirect(response)

        self.login(self.admin)
        query = self._start("user@outlook.com")
        key = outlook.attempt_key(query["state"][0])
        payload = cache.get(key)
        payload["user_id"] = self.user.id
        cache.set(key, payload, outlook.CONSENT_ATTEMPT_TTL_SECONDS)

        self.login(self.user)
        response = self.client.get(
            reverse("channels.types.email.outlook_callback"),
            {"code": "auth-code", "state": query["state"][0]},
        )
        self.assertLoginRedirect(response)
        self.assertFalse(Channel.objects.filter(channel_type="EM").exists())

    @microsoft_app
    def test_outlook_duplicate_address(self):
        self.login(self.admin)
        self._assert_connected("user@outlook.com", "user@outlook.com", "upn", "refresh-first")
        original = Channel.objects.get(channel_type="EM")

        query = self._start("user@outlook.com")
        response, posted = self._finish(
            query, _access_token("user@outlook.com"), refresh="refresh-second", follow=True
        )
        self.assertContains(response, "This mailbox is already connected.")
        self.assertEqual(1, posted.call_count)
        self.assertEqual(1, Channel.objects.filter(channel_type="EM").count())
        original.refresh_from_db()
        self.assertEqual("refresh-first", original.config["refresh_token"])

        self.client.post(
            reverse("channels.types.email.claim"),
            {
                "username": "email@gmail.com",
                "password": "*******",
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "imap_host": "imap.gmail.com",
                "imap_port": 993,
            },
            follow=True,
        )
        query = self._start("email@gmail.com")
        response, posted = self._finish(
            query, _access_token("email@gmail.com"), refresh="refresh-generic", follow=True
        )
        self.assertContains(response, "This mailbox is already connected.")
        generic = Channel.objects.get(channel_type="EM", address="email@gmail.com")
        self.assertEqual("*******", generic.config["password"])
        self.assertNotIn("oauth_provider", generic.config)
        self.assertEqual(2, Channel.objects.filter(channel_type="EM").count())

    @microsoft_app
    def test_outlook_token_failure_reports_opaque_ids_only(self):
        self.login(self.admin)
        self.org.proj_uuid = "11111111-1111-1111-1111-111111111111"
        self.org.save(update_fields=("proj_uuid",))
        query = self._start("user@contoso.com")
        description = "user@contoso.com invalid_grant detail"
        scope = MagicMock()
        scope.__enter__.return_value = scope
        with patch("temba.channels.types.email.outlook.sentry_sdk.push_scope", return_value=scope), patch(
            "temba.channels.types.email.outlook.sentry_sdk.capture_message"
        ) as captured, self.assertLogs(
            "temba.channels.types.email.outlook", level="INFO"
        ) as logs, _patch_jwks(), patch(
            "temba.channels.types.email.outlook.requests.post",
            return_value=_JsonResponse(400, {"error": "invalid_grant", "error_description": description}),
        ) as posted:
            response = self.client.get(
                reverse("channels.types.email.outlook_callback"),
                {"code": "auth-code-secret", "state": query["state"][0]},
                follow=True,
                HTTP_X_REQUEST_ID="corr-1",
            )

        self.assertContains(response, "Microsoft did not complete the sign-in.")
        self.assertNotContains(response, description)
        self.assertEqual(1, posted.call_count)
        self.assertEqual(outlook.MICROSOFT_HTTP_TIMEOUT_SECONDS, posted.call_args.kwargs["timeout"])
        joined = "\n".join(logs.output)
        self.assertIn("error=invalid_grant", joined)
        self.assertNotIn(description, joined)
        self.assertNotIn("auth-code-secret", joined)
        self.assertNotIn("app-secret", joined)
        tags = {call.args[0]: call.args[1] for call in scope.set_tag.call_args_list}
        self.assertEqual(str(self.org.proj_uuid), tags["account_id"])
        self.assertEqual("corr-1", tags["correlation_id"])
        self.assertEqual(self.org.id, tags["org_id"])
        self.assertNotIn(description, str(tags))
        self.assertNotIn("auth-code-secret", str(captured.call_args))
        self.assertNotIn("app-secret", str(captured.call_args))
        self.assertFalse(Channel.objects.filter(channel_type="EM").exists())

    @microsoft_app
    def test_outlook_replaces_tokens_when_reconnect_is_needed(self):
        self.login(self.admin)
        channel = Channel.create(
            self.org,
            self.admin,
            None,
            "EM",
            name="user@outlook.com",
            address="user@outlook.com",
            config={
                "username": "user@outlook.com",
                "password": "",
                "smtp_host": outlook.SMTP_HOST,
                "smtp_port": outlook.SMTP_PORT,
                "imap_host": outlook.IMAP_HOST,
                "imap_port": outlook.IMAP_PORT,
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "oauth_provider": "microsoft",
                "oauth_status": "needs_reconnect",
                "callback_domain": settings.HOSTNAME,
            },
        )
        query = self._start("user@outlook.com")
        token = _access_token("user@outlook.com")
        response, posted = self._finish(query, token, refresh="new-refresh")
        channel.refresh_from_db()
        self.assertRedirect(response, reverse("channels.channel_read", args=[channel.uuid]))
        self.assertEqual(1, posted.call_count)
        self.assertEqual(1, Channel.objects.filter(channel_type="EM").count())
        self.assertEqual(token, channel.config["access_token"])
        self.assertEqual("new-refresh", channel.config["refresh_token"])
        self.assertEqual("active", channel.config["oauth_status"])
        read = self.client.get(reverse("channels.channel_read", args=[channel.uuid]))
        self.assertNotContains(read, token)
        self.assertNotContains(read, "new-refresh")
        self.assertNotContains(read, "old-access")

    def test_outlook_release_clears_tokens(self):
        channel = Channel.create(
            self.org,
            self.admin,
            None,
            "EM",
            name="user@outlook.com",
            address="user@outlook.com",
            config={
                "username": "user@outlook.com",
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "oauth_provider": "microsoft",
            },
        )
        channel.release(self.admin)
        channel.refresh_from_db()
        self.assertFalse(channel.is_active)
        self.assertNotIn("access_token", channel.config)
        self.assertNotIn("refresh_token", channel.config)

    def test_outlook_reconnect_notice(self):
        self.login(self.admin)
        channel = Channel.create(
            self.org,
            self.admin,
            None,
            "EM",
            name="user@outlook.com",
            address="user@outlook.com",
            config={
                "username": "user@outlook.com",
                "access_token": "secret-access",
                "refresh_token": "secret-refresh",
                "oauth_provider": "microsoft",
                "oauth_status": "needs_reconnect",
            },
        )
        response = self.client.get(reverse("channels.channel_read", args=[channel.uuid]))
        self.assertContains(response, "This mailbox needs to be connected again.")
        self.assertContains(response, reverse("channels.types.email.claim"))
        self.assertNotContains(response, "secret-access")
        self.assertNotContains(response, "secret-refresh")

    def _assert_connected(self, typed, address, claim, refresh):
        response = self.client.get(reverse("channels.types.email.claim"))
        html = response.content.decode()
        action = reverse("channels.types.email.outlook_start")
        form_at = html.find(action)
        form_start = html.rfind("<form", 0, form_at)
        form_end = html.find("</form>", form_at)
        self.assertGreater(form_start, -1)
        self.assertGreater(form_end, form_at)
        window = html[form_start:form_end]
        self.assertIn("target='_top'", window)
        for banned in (
            "password",
            "smtp_host",
            "smtp_port",
            "imap_host",
            "imap_port",
            "access_token",
            "refresh_token",
        ):
            self.assertNotIn(banned, window)

        query = self._start(typed)
        self.assertEqual(query["prompt"][0], "select_account")
        self.assertEqual(query["code_challenge_method"][0], "S256")
        self.assertEqual(query["client_id"][0], "app-id")
        self.assertEqual(
            "offline_access https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send",
            query["scope"][0],
        )
        self.assertNotIn("client_secret", query)
        attempt = cache.get(outlook.attempt_key(query["state"][0]))
        self.assertEqual(address, attempt["username"])
        digest = hashlib.sha256(attempt["code_verifier"].encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        self.assertEqual(expected, query["code_challenge"][0])

        token = _access_token(address, claim=claim)
        response, posted = self._finish(query, token, refresh=refresh)
        channel = Channel.objects.get(channel_type="EM", address=address)
        self.assertRedirect(response, reverse("channels.channel_read", args=[channel.uuid]))
        self.assertEqual(1, posted.call_count)
        self.assertEqual(outlook.TOKEN_URL, posted.call_args.args[0])
        self.assertEqual(outlook.MICROSOFT_HTTP_TIMEOUT_SECONDS, posted.call_args.kwargs["timeout"])
        body = posted.call_args.kwargs["data"]
        self.assertEqual("app-secret", body["client_secret"])
        self.assertEqual("auth-code", body["code"])
        self.assertEqual(query["redirect_uri"][0], body["redirect_uri"])
        self.assertEqual(attempt["code_verifier"], body["code_verifier"])
        self.assertEqual("authorization_code", body["grant_type"])
        self.assertIsNone(cache.get(outlook.attempt_key(query["state"][0])))

        self.assertEqual(address, channel.name)
        config = channel.config
        self.assertEqual(
            {
                "username": address,
                "password": "",
                "smtp_host": "smtp.office365.com",
                "smtp_port": 587,
                "imap_host": "outlook.office365.com",
                "imap_port": 993,
                "access_token": token,
                "refresh_token": refresh,
                "oauth_provider": "microsoft",
                "oauth_status": "active",
                "callback_domain": settings.HOSTNAME,
            },
            config,
        )
        read = self.client.get(reverse("channels.channel_read", args=[channel.uuid]))
        self.assertNotContains(read, token)
        self.assertNotContains(read, refresh)

        again = self.client.get(
            reverse("channels.types.email.outlook_callback"),
            {"code": "auth-code", "state": query["state"][0]},
            follow=True,
        )
        self.assertContains(again, "Sign in again to connect the mailbox.")
        self.assertEqual(1, Channel.objects.filter(channel_type="EM", address=address).count())

    def _start(self, address):
        response = self.client.post(reverse("channels.types.email.outlook_start"), {"username": address})
        self.assertEqual(302, response.status_code)
        location = response["Location"]
        self.assertTrue(location.startswith(f"{outlook.AUTHORIZE_URL}?"))
        return parse_qs(urlparse(location).query)

    def _finish(self, query, token, refresh="refresh-token", status=200, payload=None, follow=False):
        body = payload if payload is not None else {"access_token": token, "refresh_token": refresh}
        with _patch_jwks(), patch(
            "temba.channels.types.email.outlook.requests.post", return_value=_JsonResponse(status, body)
        ) as posted:
            response = self.client.get(
                reverse("channels.types.email.outlook_callback"),
                {"code": "auth-code", "state": query["state"][0]},
                follow=follow,
            )
        return response, posted


class OutlookConsentRaceTest(TembaNonAtomicTest):
    def setUp(self):
        super().setUp()
        self.setUpOrgs()

    @microsoft_app
    def test_two_concurrent_completions_create_one_channel(self):
        address = "shared@outlook.com"
        org_id = self.org.id
        user_id = self.admin.id
        states = [outlook.put_attempt(org_id, user_id, address, f"verifier-{index}") for index in (0, 1)]
        tokens = {f"code-{index}": _access_token(address) for index in (0, 1)}

        def post(url, data=None, timeout=None):
            self.assertEqual(outlook.TOKEN_URL, url)
            self.assertEqual(outlook.MICROSOFT_HTTP_TIMEOUT_SECONDS, timeout)
            code = data["code"]
            return _JsonResponse(200, {"access_token": tokens[code], "refresh_token": f"refresh-{code}"})

        results = [None, None]
        barrier = threading.Barrier(2)

        def worker(index, state):
            connections.close_all()
            try:
                barrier.wait(timeout=5)
                org = Org.objects.get(id=org_id)
                user = User.objects.get(id=user_id)
                results[index] = outlook.complete(
                    org,
                    user,
                    f"code-{index}",
                    state,
                    "https://example.com/channels/types/email/outlook/callback",
                )
            except Exception as exc:  # pragma: no cover - asserted below
                results[index] = exc
            finally:
                connections.close_all()

        with _patch_jwks(), patch("temba.channels.types.email.outlook.requests.post", side_effect=post):
            threads = [threading.Thread(target=worker, args=(index, state)) for index, state in enumerate(states)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
                self.assertFalse(thread.is_alive())

        channels = list(Channel.objects.filter(channel_type="EM", address=address))
        self.assertEqual(1, len(channels))
        successes = [item for item in results if isinstance(item, Channel)]
        failures = [item for item in results if isinstance(item, outlook.ConsentError)]
        self.assertEqual(1, len(successes))
        self.assertEqual(1, len(failures))
        self.assertEqual("already_connected", failures[0].code)
