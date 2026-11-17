import base64
import json
import logging
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from rest_framework.test import APIRequestFactory

from django.test import SimpleTestCase, override_settings

from temba.api.v2.internals.channels import usecases
from temba.api.v2.internals.channels.views import (
    ChannelSIPConnectionView,
    ChannelSIPCredentialsView,
    InternalChannelView,
)
from temba.channels.models import Channel
from temba.channels.types.telephony import constants, manifests, provisioning
from temba.channels.types.telephony.fake_kubernetes import FakeKubernetes
from temba.channels.types.telephony.kubernetes_client import KubernetesTransientError
from temba.channels.types.telephony.provisioning import SIPProvisioner
from temba.channels.types.telephony.tests_provisioning import SECRET_NAME, SETTINGS, FakeRedis, RecordingHandler
from temba.tests import TembaTest

CONNECTION_URL = "/api/v2/internals/channel_sip_connection"
CREDENTIALS_URL = "/api/v2/internals/channel_sip_credentials"
NOT_FOUND = {"error": "Channel not found"}


@override_settings(**SETTINGS)
class SIPEndpointsTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid.uuid4()
        self.org.save(update_fields=["proj_uuid"])
        self.org2.proj_uuid = uuid.uuid4()
        self.org2.save(update_fields=["proj_uuid"])

        # authentication and permissions are covered by InternalChannelView, whose classes these views share
        for view in ("ChannelSIPConnectionView", "ChannelSIPCredentialsView"):
            for attribute in ("authentication_classes", "permission_classes"):
                patcher = patch(f"temba.api.v2.internals.channels.views.{view}.{attribute}", [])
                patcher.start()
                self.addCleanup(patcher.stop)

        self.fake = FakeKubernetes(SECRET_NAME)
        patcher = patch.object(provisioning, "build_client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.channel = self.create_provisioned_channel()

        self.handler = RecordingHandler()
        logging.getLogger().addHandler(self.handler)
        self.addCleanup(logging.getLogger().removeHandler, self.handler)

    def create_provisioned_channel(self, org=None):
        channel = self.create_channel("TPH", "Line", "+12065551212", org=org or self.org)
        metadata = SIPProvisioner(client=self.fake).provision(channel.uuid, channel.id, channel.address)
        channel.config = {**metadata, "voice_mode": {"enabled": True}}
        channel.save(update_fields=["config"])
        return channel

    def get(self, channel_uuid=None, project_uuid=None):
        params = {
            "channel_uuid": channel_uuid or self.channel.uuid,
            "project_uuid": project_uuid or self.org.proj_uuid,
        }
        return self.client.get(CONNECTION_URL, params)

    def post(self, channel_uuid=None, project_uuid=None):
        return self.client.post(
            CREDENTIALS_URL,
            {
                "channel_uuid": str(channel_uuid or self.channel.uuid),
                "project_uuid": str(project_uuid or self.org.proj_uuid),
            },
            content_type="application/json",
        )

    # connection -----------------------------------------------------------------------------------------------

    def test_connection_data(self):
        self.fake.set_sip_user_phase(manifests.resource_name(self.channel.uuid), "Ready")

        response = self.get()

        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("ready", data["status"])
        self.assertEqual("voip.stg.cloud.weni.ai", data["domain"])
        self.assertEqual({"protocol": "tls", "port": 5061}, data["transports"][0])
        self.assertEqual(3, len(data["transports"]))  # the malformed entry is skipped
        self.assertEqual(manifests.resource_name(self.channel.uuid), data["username"])
        self.assertEqual("12065551212", data["did"])
        self.assertEqual(["203.0.113.10"], data["signaling_ips"])
        self.assertEqual({"ips": [], "rtp_port_range": "10000-10035"}, data["media"])
        self.assertEqual(["PCMA", "PCMU"], data["codecs"])
        self.assertEqual("rfc4733", data["dtmf_mode"])
        self.assertFalse(data["credentials_reset_required"])
        self.assertNotIn("password", data)

    def test_connection_status_is_pending_until_the_operator_reports(self):
        self.assertEqual("pending", self.get().json()["status"])

    def test_connection_reports_when_a_reset_is_required(self):
        self.channel.config = {**self.channel.config, constants.CONFIG_SIP_RESET_REQUIRED: True}
        self.channel.save(update_fields=["config"])

        self.assertTrue(self.get().json()["credentials_reset_required"])

    # credentials ----------------------------------------------------------------------------------------------

    def test_issue_credentials(self):
        name = manifests.resource_name(self.channel.uuid)

        response = self.post()

        self.assertEqual(200, response.status_code)
        data = response.json()
        password = data["password"]
        self.assertEqual(32, len(password))
        self.assertEqual("no-store", response["Cache-Control"])
        self.assertEqual("no-cache", response["Pragma"])
        self.assertEqual(name, data["username"])

        # the password is in the cluster Secret and nowhere else
        self.assertEqual(base64.b64encode(password.encode()).decode(), self.fake.secret_data()[name])
        self.channel.refresh_from_db()
        self.assertNotIn(password, str(self.channel.config))
        self.assertNotIn(password, "".join(self.handler.text))

    def test_issuing_again_replaces_the_password_and_clears_the_reset_flag(self):
        self.channel.config = {**self.channel.config, constants.CONFIG_SIP_RESET_REQUIRED: True}
        self.channel.save(update_fields=["config"])

        first = self.post().json()
        second = self.post().json()

        self.assertNotEqual(first["password"], second["password"])
        self.assertFalse(second["credentials_reset_required"])
        self.channel.refresh_from_db()
        self.assertNotIn(constants.CONFIG_SIP_RESET_REQUIRED, self.channel.config)

    @override_settings(TPH_SIP_ISSUE_MAX_PER_WINDOW=2)
    def test_issuing_is_rate_limited(self):
        self.assertEqual(200, self.post().status_code)
        self.assertEqual(200, self.post().status_code)

        response = self.post()

        self.assertEqual(429, response.status_code)
        self.assertEqual({"error": "Too many password requests"}, response.json())
        self.assertGreater(int(response["Retry-After"]), 0)
        self.assertNotIn("password", response.json())

    # not found and not available --------------------------------------------------------------------------------

    def assert_not_found_everywhere(self, **kwargs):
        for method in (self.get, self.post):
            response = method(**kwargs)
            self.assertEqual(404, response.status_code)
            self.assertEqual(NOT_FOUND, response.json())

    def test_channel_of_another_project_is_indistinguishable_from_a_missing_one(self):
        before = len(self.fake.calls)

        self.assert_not_found_everywhere(project_uuid=self.org2.proj_uuid)
        self.assert_not_found_everywhere(channel_uuid=uuid.uuid4())
        self.assert_not_found_everywhere(project_uuid=uuid.uuid4())

        self.assertEqual(before, len(self.fake.calls))  # the cluster was never asked

    def test_inactive_and_non_tph_channels_are_not_found(self):
        telegram = self.create_channel("TG", "Telegram", "tg-1")
        self.assert_not_found_everywhere(channel_uuid=telegram.uuid)

        Channel.objects.filter(id=self.channel.id).update(is_active=False)
        self.assert_not_found_everywhere()

    def test_channel_without_provisioning_is_a_conflict(self):
        legacy = self.create_channel("TPH", "Legacy", "+12065550000")

        for method in (self.get, self.post):
            response = method(channel_uuid=legacy.uuid)
            self.assertEqual(409, response.status_code)
            self.assertEqual({"error": "SIP provisioning not available for this channel"}, response.json())

    def test_invalid_identifiers_are_rejected(self):
        for params in (
            {},
            {"channel_uuid": "nope", "project_uuid": str(self.org.proj_uuid)},
            {"channel_uuid": str(self.channel.uuid)},
        ):
            with self.subTest(params=params):
                self.assertEqual(400, self.client.get(CONNECTION_URL, params).status_code)
                self.assertEqual(
                    400, self.client.post(CREDENTIALS_URL, params, content_type="application/json").status_code
                )

    # cluster failures -------------------------------------------------------------------------------------------

    def test_cluster_failure_gives_a_generic_503(self):
        self.fake.fail("patch_secret", KubernetesTransientError("internal detail 10.0.0.7"), times=10)

        response = self.post()

        self.assertEqual(503, response.status_code)
        self.assertEqual({"error": "Service unavailable"}, response.json())
        self.assertNotIn("10.0.0.7", response.content.decode())

    def test_unreadable_sip_user_shows_as_an_error_status_instead_of_failing(self):
        self.fake.fail("get", KubernetesTransientError("down"), kind="SIPUser", times=10)

        self.assertEqual("error", self.get().json()["status"])


class SIPEndpointsAuthenticationTest(SimpleTestCase):
    """
    Instantiating ``InternalOIDCAuthentication`` requires OIDC settings that the test suite does not have, so a live
    unauthenticated request cannot be made here. The contract is that these views share ``InternalChannelView``'s
    authentication and permission classes; that view already covers the unauthenticated path.
    """

    def test_views_use_the_same_auth_as_internal_channel_view(self):
        for view in (ChannelSIPConnectionView, ChannelSIPCredentialsView):
            with self.subTest(view=view.__name__):
                self.assertEqual(InternalChannelView.authentication_classes, view.authentication_classes)
                self.assertEqual(InternalChannelView.permission_classes, view.permission_classes)


class SIPViewMappingTest(SimpleTestCase):
    """The HTTP layer alone, with the use cases replaced. It needs no database, so it runs anywhere."""

    CHANNEL = "3f2c9a7e-5b4d-41a0-a1b2-c3d4e5f60718"
    PROJECT = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    PARAMS = {"channel_uuid": CHANNEL, "project_uuid": PROJECT}

    def setUp(self):
        super().setUp()
        for view in ("ChannelSIPConnectionView", "ChannelSIPCredentialsView"):
            for attribute in ("authentication_classes", "permission_classes"):
                patcher = patch(f"temba.api.v2.internals.channels.views.{view}.{attribute}", [])
                patcher.start()
                self.addCleanup(patcher.stop)

    @staticmethod
    def render(response):
        response.render()
        response.json = lambda: json.loads(response.content)
        return response

    def call(self, view, request, usecase, side_effect, return_value):
        with patch.object(usecase, "execute", side_effect=side_effect, return_value=return_value) as execute:
            response = self.render(view.as_view()(request))
        return response, execute

    def get(self, side_effect=None, return_value=None, params=None):
        request = APIRequestFactory().get(CONNECTION_URL, self.PARAMS if params is None else params)
        return self.call(
            ChannelSIPConnectionView, request, usecases.GetSIPConnectionUseCase, side_effect, return_value
        )

    def post(self, side_effect=None, return_value=None):
        request = APIRequestFactory().post(CREDENTIALS_URL, self.PARAMS, format="json")
        return self.call(
            ChannelSIPCredentialsView, request, usecases.IssueSIPCredentialsUseCase, side_effect, return_value
        )

    def test_success_and_headers(self):
        response, execute = self.get(return_value={"status": "ready"})
        self.assertEqual(200, response.status_code)
        self.assertNotIn("no-store", response.get("Cache-Control", ""))
        execute.assert_called_once_with(self.CHANNEL, self.PROJECT)

        response, execute = self.post(return_value={"status": "ready", "password": "secret-value"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("no-store", response["Cache-Control"])
        self.assertEqual("no-cache", response["Pragma"])
        self.assertEqual(self.CHANNEL, execute.call_args.args[0])

    def test_domain_errors_map_to_the_contract(self):
        cases = [
            (usecases.SIPChannelNotFoundError(), 404, {"error": "Channel not found"}),
            (
                usecases.SIPNotProvisionedError(),
                409,
                {"error": "SIP provisioning not available for this channel"},
            ),
            (provisioning.SIPRateLimitError(120), 429, {"error": "Too many password requests"}),
        ]
        for error, expected_status, expected_body in cases:
            for call in (self.get, self.post):
                with self.subTest(error=type(error).__name__, call=call.__name__):
                    response, _ = call(side_effect=error)
                    self.assertEqual(expected_status, response.status_code)
                    self.assertEqual(expected_body, response.json())

        response, _ = self.post(side_effect=provisioning.SIPRateLimitError(120))
        self.assertEqual("120", response["Retry-After"])

    def test_cluster_failure_is_a_generic_503_that_is_reported_without_leaking(self):
        error = provisioning.SIPProvisioningError(provisioning.ERROR_UNAVAILABLE)
        error.__cause__ = KubernetesTransientError("internal detail 10.0.0.7")

        with patch.object(provisioning, "report") as report:
            response, _ = self.post(side_effect=error)

        self.assertEqual(503, response.status_code)
        self.assertEqual({"error": "Service unavailable"}, response.json())
        self.assertNotIn("10.0.0.7", response.content.decode())
        self.assertEqual("sip_endpoint", report.call_args.kwargs["event"])

    def test_malformed_identifiers_never_reach_the_use_case(self):
        for params in ({}, {"channel_uuid": "nope", "project_uuid": self.PROJECT}, {"channel_uuid": self.CHANNEL}):
            with self.subTest(params=params):
                response, execute = self.get(params=params)
                self.assertEqual(400, response.status_code)
                execute.assert_not_called()


@override_settings(**SETTINGS)
class SIPUseCaseTest(SimpleTestCase):
    """Use case logic without a database: only the channel lookup is replaced."""

    def setUp(self):
        super().setUp()
        self.fake = FakeKubernetes(SECRET_NAME)
        self.channel = SimpleNamespace(
            uuid=uuid.UUID("3f2c9a7e-5b4d-41a0-a1b2-c3d4e5f60718"),
            id=42,
            address="+5511912345678",
            org_id=7,
            config={},
            saved=[],
        )
        self.channel.save = lambda update_fields=None: self.channel.saved.append(update_fields)
        metadata = SIPProvisioner(client=self.fake).provision(self.channel.uuid, self.channel.id, self.channel.address)
        self.channel.config = {**metadata, constants.CONFIG_SIP_RESET_REQUIRED: True}

        self.redis = FakeRedis()
        patcher = patch.object(usecases, "Channel")
        self.channel_model = patcher.start()
        self.addCleanup(patcher.stop)
        self.set_found(self.channel)

        patcher = patch.object(provisioning, "get_redis_connection", return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.handler = RecordingHandler()
        logging.getLogger().addHandler(self.handler)
        self.addCleanup(logging.getLogger().removeHandler, self.handler)

        self.provisioner = SIPProvisioner(client=self.fake)

    def set_found(self, channel):
        chain = self.channel_model.objects.filter.return_value.select_related.return_value
        chain.first.return_value = channel

    def issue(self):
        return usecases.IssueSIPCredentialsUseCase(self.provisioner).execute(
            str(self.channel.uuid), "project", actor_id=5
        )

    def test_lookup_filters_on_everything_that_scopes_the_channel(self):
        usecases.GetSIPConnectionUseCase(self.provisioner).execute(str(self.channel.uuid), "project")

        self.channel_model.objects.filter.assert_called_once_with(
            uuid=str(self.channel.uuid), org__proj_uuid="project", is_active=True, channel_type="TPH"
        )

    def test_missing_channel_and_missing_provisioning(self):
        self.set_found(None)
        with self.assertRaises(usecases.SIPChannelNotFoundError):
            usecases.GetSIPConnectionUseCase(self.provisioner).execute("x", "y")

        self.set_found(SimpleNamespace(config={}, uuid=self.channel.uuid))
        with self.assertRaises(usecases.SIPNotProvisionedError):
            self.issue()
        self.assertEqual({}, self.redis.counters)  # nothing was issued, so nothing was counted

    def test_issue_returns_the_password_once_and_clears_the_reset_flag(self):
        data = self.issue()

        self.assertEqual(32, len(data["password"]))
        self.assertFalse(data["credentials_reset_required"])
        self.assertNotIn(constants.CONFIG_SIP_RESET_REQUIRED, self.channel.config)
        self.assertEqual([["config"]], self.channel.saved)
        self.assertNotIn(data["password"], "".join(self.handler.text))
        self.assertNotIn(data["password"], str(self.channel.config))

    def test_issue_without_a_pending_reset_does_not_write_the_channel(self):
        self.channel.config.pop(constants.CONFIG_SIP_RESET_REQUIRED)

        self.issue()

        self.assertEqual([], self.channel.saved)

    @override_settings(TPH_SIP_ISSUE_MAX_PER_WINDOW=1)
    def test_the_limit_is_checked_before_a_password_is_generated(self):
        self.issue()
        keys_before = dict(self.fake.secret_data())

        with self.assertRaises(provisioning.SIPRateLimitError):
            self.issue()

        self.assertEqual(keys_before, self.fake.secret_data())  # the second password was never written
