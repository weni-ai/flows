import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse

from temba.api.v2.internals.channels.usecases import GetElevenLabsApiKeyUseCase
from temba.tests import TembaTest

from ...models import Channel
from . import constants, manifests, provisioning
from .fake_kubernetes import FakeKubernetes
from .kubernetes_client import KubernetesForbidden
from .reconciliation import run_reconciliation
from .tests_provisioning import SECRET_NAME, SETTINGS

TEST_ELEVENLABS_API_KEY = "test-el-api-key"
TEST_ELEVENLABS_VOICE_ID = "test-el-voice-id"


class TelephonyPSTNTypeTest(TembaTest):
    def _claim_url(self):
        return reverse("channels.types.telephony.claim")

    def _post_claim(self, post_data):
        return self.client.post(self._claim_url(), post_data)

    @override_settings(WENI_VOICE_TOKEN=TEST_ELEVENLABS_API_KEY, WENI_ELEVENLABS_VOICE_ID=TEST_ELEVENLABS_VOICE_ID)
    def test_claim(self):
        Channel.objects.all().delete()
        self.login(self.admin)

        response = self.client.get(reverse("channels.channel_claim"))
        self.assertContains(response, self._claim_url())

        post_data = {
            "name": "Support Line",
            "country": "US",
            "phone_number": "+12065551212",
        }

        # US1: valid claim creates TPH channel with tel scheme and E.164 DID as address
        response = self._post_claim(post_data)
        self.assertEqual(302, response.status_code)

        channel = Channel.objects.get(name="Support Line")

        self.assertEqual("TPH", channel.channel_type)
        self.assertEqual("+12065551212", channel.address)
        self.assertEqual("US", channel.country)
        self.assertEqual(["tel"], channel.schemes)
        self.assertFalse(channel.config.get("base_url"))
        self.assertFalse(channel.config.get("auth_token"))
        self.assertEqual(
            {
                "enabled": True,
                "elevenLabs": {
                    "apiKey": TEST_ELEVENLABS_API_KEY,
                    "voiceId": TEST_ELEVENLABS_VOICE_ID,
                },
            },
            channel.config.get("voice_mode"),
        )
        self.assertEqual(TEST_ELEVENLABS_API_KEY, GetElevenLabsApiKeyUseCase().execute(str(channel.uuid)))

        read_url = reverse("channels.channel_read", args=[channel.uuid])
        self.assertRedirect(response, read_url)

        # US3: configuration shows Courier receive URL for gateway setup
        config_url = reverse("channels.channel_configuration", args=[channel.uuid])
        response = self.client.get(config_url)
        self.assertEqual(200, response.status_code)
        self.assertContains(response, reverse("courier.tph"))

    def test_claim_rejects_invalid_dids(self):
        Channel.objects.all().delete()
        self.login(self.admin)

        post_data = {
            "name": "Support Line",
            "country": "US",
            "phone_number": "+12065551212",
        }

        # FR-005: invalid DIDs must be rejected before channel creation
        # 404-123-4567 is possible in NANP but not a valid DID (is_valid_number)
        response = self._post_claim({**post_data, "phone_number": "404-123-4567"})
        self.assertFormError(response, "form", "phone_number", "Invalid phone number")
        self.assertFalse(Channel.objects.exists())

        # too short to be a possible number (URN.validate)
        response = self._post_claim({**post_data, "phone_number": "123"})
        self.assertFormError(response, "form", "phone_number", "Invalid phone number")
        self.assertFalse(Channel.objects.exists())

        # unknown country code: normalize keeps digits, parse without region fails
        response = self._post_claim({**post_data, "phone_number": "+9991234567"})
        self.assertFormError(response, "form", "phone_number", "Invalid phone number")
        self.assertFalse(Channel.objects.exists())

    def test_claim_normalizes_national_format_number(self):
        Channel.objects.all().delete()
        self.login(self.admin)

        post_data = {
            "name": "Support Line",
            "country": "US",
            "phone_number": "206-555-1212",
        }

        response = self._post_claim(post_data)
        self.assertEqual(302, response.status_code)

        channel = Channel.objects.get(name="Support Line")
        self.assertEqual("+12065551212", channel.address)

    @override_settings(WENI_VOICE_TOKEN="", WENI_ELEVENLABS_VOICE_ID="")
    def test_claim_persists_empty_elevenlabs_credentials(self):
        Channel.objects.all().delete()
        self.login(self.admin)

        response = self._post_claim(
            {
                "name": "Support Line",
                "country": "US",
                "phone_number": "+12065551212",
            }
        )
        self.assertEqual(302, response.status_code)

        channel = Channel.objects.get(name="Support Line")
        self.assertEqual(
            {
                "enabled": True,
                "elevenLabs": {"apiKey": "", "voiceId": ""},
            },
            channel.config.get("voice_mode"),
        )


@override_settings(WENI_VOICE_TOKEN=TEST_ELEVENLABS_API_KEY, WENI_ELEVENLABS_VOICE_ID=TEST_ELEVENLABS_VOICE_ID)
class TelephonySIPProvisioningTest(TembaTest):
    """Claim, release, reconciliation and the management command against an in-memory cluster (spec 019)."""

    POST_DATA = {"name": "Support Line", "country": "US", "phone_number": "+12065551212"}

    def setUp(self):
        super().setUp()
        Channel.objects.all().delete()
        self.fake = FakeKubernetes(SECRET_NAME)

        patcher = patch.object(provisioning, "build_client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def claim(self):
        self.login(self.admin)
        return self.client.post(reverse("channels.types.telephony.claim"), self.POST_DATA)

    def create_provisioned_channel(self):
        with override_settings(**SETTINGS):
            self.assertEqual(302, self.claim().status_code)
        return Channel.objects.get(name="Support Line")

    @override_settings(**SETTINGS)
    def test_claim_provisions_the_channel(self):
        response = self.claim()

        self.assertEqual(302, response.status_code)
        channel = Channel.objects.get(name="Support Line", is_active=True)
        name = manifests.resource_name(channel.uuid)

        self.assertEqual(name, channel.config[constants.CONFIG_SIP_RESOURCE_NAME])
        self.assertEqual(name, channel.config[constants.CONFIG_SIP_USERNAME])
        for kind in constants.CUSTOM_RESOURCE_KINDS:
            self.assertEqual([name], self.fake.names(kind))

        # SEC-01: the password is in the cluster only, the channel config holds metadata and nothing secret
        self.assertEqual([name], self.fake.secret_keys())
        self.assertNotIn("password", json.dumps(channel.config).lower())

    @override_settings(**SETTINGS)
    def test_claim_failure_leaves_no_channel_and_no_cluster_objects(self):
        self.fake.fail("create", KubernetesForbidden("denied", status=403, reason="Forbidden"), kind="SIPUser")

        response = self.claim()

        self.assertEqual(200, response.status_code)  # the form is shown again
        self.assertContains(response, "could not set up the SIP connection")
        self.assertNotContains(response, "denied")
        self.assertEqual(0, Channel.objects.filter(name="Support Line").count())
        self.assertEqual([], self.fake.kinds_present())
        self.assertEqual([], self.fake.secret_keys())

    @override_settings(**{**SETTINGS, "TPH_SIP_PROVISIONING_ENABLED": False})
    def test_claim_with_the_flag_off_never_touches_the_cluster(self):
        response = self.claim()

        self.assertEqual(302, response.status_code)
        channel = Channel.objects.get(name="Support Line")
        self.assertNotIn(constants.CONFIG_SIP_RESOURCE_NAME, channel.config)
        self.assertEqual([], self.fake.calls)

    def test_release_revokes_even_when_the_flag_is_now_off(self):
        channel = self.create_provisioned_channel()
        self.assertNotEqual([], self.fake.kinds_present())

        with override_settings(**{**SETTINGS, "TPH_SIP_PROVISIONING_ENABLED": False}):
            channel.release(self.admin)

        self.assertEqual([], self.fake.kinds_present())
        self.assertEqual([], self.fake.secret_keys())

    @override_settings(**SETTINGS)
    def test_release_completes_when_the_cluster_fails_and_the_reconciliation_cleans_up(self):
        channel = self.create_provisioned_channel()
        self.fake.fail("delete", KubernetesForbidden("denied", status=403, reason="Forbidden"), times=10)

        channel.release(self.admin)

        channel.refresh_from_db()
        self.assertFalse(channel.is_active)
        self.assertNotEqual([], self.fake.kinds_present())  # something was left behind

        self.fake.age_all(3600)
        self.fake._failures.clear()
        summary = run_reconciliation()

        self.assertEqual(1, summary["deleted"])
        self.assertEqual([], self.fake.kinds_present())

    @override_settings(**{**SETTINGS, "TPH_SIP_PROVISIONING_ENABLED": False})
    def test_reconciliation_does_nothing_when_the_flag_is_off(self):
        self.assertIsNone(run_reconciliation())
        self.assertEqual([], self.fake.calls)

    @override_settings(**SETTINGS)
    def test_reconciliation_recreates_a_missing_sip_user_of_an_active_channel(self):
        channel = self.create_provisioned_channel()
        self.fake.age_all(3600)
        del self.fake.resources[constants.KIND_SIP_USER][manifests.resource_name(channel.uuid)]

        summary = run_reconciliation()

        self.assertEqual(1, summary["recreated"])
        self.assertEqual([manifests.resource_name(channel.uuid)], self.fake.names(constants.KIND_SIP_USER))

    def test_command_refuses_to_run_with_the_flag_off(self):
        channel = self.create_provisioned_channel()

        with override_settings(**{**SETTINGS, "TPH_SIP_PROVISIONING_ENABLED": False}):
            with self.assertRaises(CommandError):
                call_command("provision_tph_sip", channel=str(channel.uuid), stdout=StringIO())

    @override_settings(**SETTINGS)
    def test_command_provisions_an_existing_channel_and_is_idempotent(self):
        with override_settings(**{**SETTINGS, "TPH_SIP_PROVISIONING_ENABLED": False}):
            self.claim()
        channel = Channel.objects.get(name="Support Line")
        self.assertNotIn(constants.CONFIG_SIP_RESOURCE_NAME, channel.config)

        call_command("provision_tph_sip", channel=str(channel.uuid), stdout=StringIO())
        call_command("provision_tph_sip", channel=str(channel.uuid), stdout=StringIO())

        channel.refresh_from_db()
        self.assertEqual(manifests.resource_name(channel.uuid), channel.config[constants.CONFIG_SIP_RESOURCE_NAME])
        self.assertEqual([manifests.resource_name(channel.uuid)], self.fake.names(constants.KIND_SIP_USER))

    @override_settings(**SETTINGS)
    def test_command_rejects_bad_input(self):
        with self.assertRaises(CommandError):
            call_command("provision_tph_sip", channel="not-a-uuid", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("provision_tph_sip", channel="00000000-0000-4000-8000-000000000000", stdout=StringIO())
