import base64
import logging
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from . import constants, manifests, provisioning
from .connection import build_connection_data, parse_transports
from .fake_kubernetes import FakeKubernetes
from .kubernetes_client import (
    KubernetesClient,
    KubernetesConfigurationError,
    KubernetesForbidden,
    KubernetesNotFound,
    KubernetesTransientError,
)
from .provisioning import SIPProvisioner, SIPProvisioningError, SIPRateLimitError

SECRET_NAME = "voice-mode-tph-credentials"
CHANNEL_UUID = uuid.UUID("3f2c9a7e-5b4d-41a0-a1b2-c3d4e5f60718")
OTHER_UUID = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
NAME = "tph-3f2c9a7e5b4d41a0a1b2c3d4e5f60718"
ADDRESS = "+5511912345678"
CHANNEL_ID = 42

SETTINGS = dict(
    TPH_SIP_PROVISIONING_ENABLED=True,
    TPH_SIP_K8S_NAMESPACE="kubevoip",
    TPH_SIP_GATEWAY_NAME="voice-mode",
    TPH_SIP_ASTERISK_POOL="voice-mode",
    TPH_SIP_ASTERISK_EXTENSION="100",
    TPH_SIP_CREDENTIALS_SECRET=SECRET_NAME,
    TPH_SIP_EXTENSION_PREFIX="9",
    TPH_SIP_ISSUE_MAX_PER_WINDOW=5,
    TPH_SIP_DOMAIN="voip.stg.cloud.weni.ai",
    TPH_SIP_TRANSPORTS=["tls:5061", "udp:5060", "bogus", "tcp:5060"],
    TPH_SIP_SIGNALING_IPS=["203.0.113.10"],
    TPH_SIP_MEDIA_IPS=[],
    TPH_SIP_RTP_PORT_RANGE="10000-10035",
    TPH_SIP_CODECS=["PCMA", "PCMU"],
    TPH_SIP_DTMF_MODE="rfc4733",
)


class RecordingHandler(logging.Handler):
    """Captures everything logged, so tests can prove a password never reaches a log (SEC-05, T034)."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.text = []

    def emit(self, record):
        self.text.append(record.getMessage() + " " + repr(record.__dict__))


class FakeRedis:
    def __init__(self):
        self.counters = {}
        self.ttls = {}

    def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def expire(self, key, seconds):
        self.ttls[key] = seconds

    def ttl(self, key):
        return self.ttls.get(key, -1)


def make_channel(**config):
    return SimpleNamespace(
        uuid=CHANNEL_UUID,
        id=CHANNEL_ID,
        address=ADDRESS,
        org_id=7,
        created_by_id=9,
        config=dict(config),
        saved_fields=None,
        save=lambda update_fields=None: None,
    )


@override_settings(**SETTINGS)
class ManifestsTest(SimpleTestCase):
    def test_names_and_helpers(self):
        self.assertEqual(NAME, manifests.resource_name(CHANNEL_UUID))
        self.assertLessEqual(len(NAME), 40)  # authUsername limit in the CRD
        self.assertEqual("5511912345678", manifests.normalize_did_for_route(ADDRESS))
        self.assertEqual("900000000042", manifests.sip_extension(CHANNEL_ID))
        self.assertEqual("weni.ai/managed-by=flows", manifests.label_selector())
        self.assertEqual(
            f"weni.ai/managed-by=flows,weni.ai/channel-uuid={CHANNEL_UUID}", manifests.label_selector(CHANNEL_UUID)
        )
        with self.assertRaises(ValueError):
            manifests.normalize_did_for_route("no digits")

    def test_isolation_invariants(self):
        built = dict(manifests.build_custom_resources(CHANNEL_UUID, CHANNEL_ID, ADDRESS))

        scope, policy, route, user = (
            built[constants.KIND_CALL_SCOPE],
            built[constants.KIND_DIAL_POLICY],
            built[constants.KIND_CALL_ROUTE],
            built[constants.KIND_SIP_USER],
        )

        # 1, 2: own scope, and the policy lists exactly that one
        self.assertEqual({"name": NAME}, route["spec"]["scopeRef"])
        self.assertEqual([{"name": NAME}], policy["spec"]["scopes"])
        self.assertNotIn("voice-mode-internal", str(built))
        # 3: the route matches the DID only, no wildcard, and reaches only the Asterisk pool
        called = route["spec"]["match"]["calledNumber"]
        self.assertEqual("5511912345678", called)
        self.assertTrue(called.isdigit())
        self.assertEqual({"asteriskPoolRef": "voice-mode", "extension": "100"}, route["spec"]["target"])
        # 4, 5: the SIP user uses its own policy and the credential Secret with its own key
        self.assertEqual({"name": NAME}, user["spec"]["dialPolicyRef"])
        self.assertEqual({"name": SECRET_NAME, "key": NAME}, user["spec"]["passwordSecretRef"])
        self.assertEqual(NAME, user["spec"]["authUsername"])
        self.assertEqual("900000000042", user["spec"]["extension"])
        self.assertEqual("5511912345678", user["spec"]["callerId"])
        self.assertEqual({"name": "voice-mode"}, scope["spec"]["gatewayRef"])

    def test_only_the_two_flows_labels(self):
        for kind, body in manifests.build_custom_resources(CHANNEL_UUID, CHANNEL_ID, ADDRESS):
            with self.subTest(kind=kind):
                self.assertEqual(NAME, body["metadata"]["name"])
                self.assertEqual("kubevoip", body["metadata"]["namespace"])
                self.assertEqual(
                    {"weni.ai/managed-by": "flows", "weni.ai/channel-uuid": str(CHANNEL_UUID)},
                    body["metadata"]["labels"],
                )
                self.assertNotIn("annotations", body["metadata"])


@override_settings(**SETTINGS)
class SIPProvisionerTest(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeKubernetes(SECRET_NAME)
        self.provisioner = SIPProvisioner(client=self.fake)

        self.handler = RecordingHandler()
        logging.getLogger().addHandler(self.handler)
        self.addCleanup(logging.getLogger().removeHandler, self.handler)

    def _provision(self, channel_uuid=CHANNEL_UUID):
        return self.provisioner.provision(channel_uuid, CHANNEL_ID, ADDRESS)

    def test_provision_creates_the_five_objects(self):
        metadata = self._provision()

        self.assertEqual({"sip_resource_name": NAME, "sip_username": NAME, "sip_extension": "900000000042"}, metadata)
        for kind in constants.CUSTOM_RESOURCE_KINDS:
            self.assertEqual([NAME], self.fake.names(kind))
        self.assertIn(NAME, self.fake.secrets[SECRET_NAME])
        # creation order: password entry, scope, policy, route, SIP user
        created = [call[1] for call in self.fake.calls_of("create")]
        self.assertEqual(list(constants.CUSTOM_RESOURCE_KINDS), created)

    def test_provision_is_idempotent_and_keeps_an_existing_password(self):
        self._provision()
        self.fake.secrets[SECRET_NAME][NAME] = "already-issued"

        self._provision()

        self.assertEqual("already-issued", self.fake.secrets[SECRET_NAME][NAME])
        self.assertEqual(1, len(self.fake.names(constants.KIND_SIP_USER)))

    def test_object_of_another_channel_is_a_conflict_and_rolls_back(self):
        # the name is taken by an object that carries another channel's label
        taken = manifests.build_dial_policy(CHANNEL_UUID)
        taken["metadata"]["labels"][constants.CHANNEL_UUID_LABEL] = str(OTHER_UUID)
        self.fake.create_resource(constants.KIND_DIAL_POLICY, taken)

        with self.assertRaises(SIPProvisioningError) as ctx:
            self._provision()

        self.assertEqual(provisioning.ERROR_CONFLICT, ctx.exception.code)
        self.assertEqual([], self.fake.names(constants.KIND_CALL_SCOPE))
        self.assertNotIn(NAME, self.fake.secrets[SECRET_NAME])
        # the other channel's object is not ours to delete
        self.assertEqual([NAME], self.fake.names(constants.KIND_DIAL_POLICY))

    def test_failure_on_the_last_object_removes_what_was_created(self):
        self.fake.fail("create", KubernetesForbidden("denied", status=403), kind=constants.KIND_SIP_USER)

        with self.assertRaises(SIPProvisioningError) as ctx:
            self._provision()

        self.assertEqual(provisioning.ERROR_FORBIDDEN, ctx.exception.code)
        for kind in constants.CUSTOM_RESOURCE_KINDS:
            self.assertEqual([], self.fake.names(kind))
        self.assertEqual({}, self.fake.secrets[SECRET_NAME])
        # forbidden is a defect, not retried by the provisioner: one create attempt for the SIP user
        self.assertEqual(1, len([c for c in self.fake.calls_of("create") if c[1] == constants.KIND_SIP_USER]))

    def test_transient_failure_maps_to_unavailable(self):
        self.fake.fail("create", KubernetesTransientError("down"), kind=constants.KIND_CALL_ROUTE)

        with self.assertRaises(SIPProvisioningError) as ctx:
            self._provision()

        self.assertEqual(provisioning.ERROR_UNAVAILABLE, ctx.exception.code)
        self.assertEqual("SIP provisioning failed", str(ctx.exception))
        self.assertEqual([], self.fake.names(constants.KIND_CALL_SCOPE))

    def test_missing_credential_secret_is_misconfiguration(self):
        del self.fake.secrets[SECRET_NAME]

        with self.assertRaises(SIPProvisioningError) as ctx:
            self._provision()

        self.assertEqual(provisioning.ERROR_MISCONFIGURED, ctx.exception.code)

    def test_failed_rerun_does_not_erase_a_password_it_did_not_create(self):
        self._provision()
        self.fake.secrets[SECRET_NAME][NAME] = "already-issued"
        self.fake.resources[constants.KIND_SIP_USER].clear()
        self.fake.fail("create", KubernetesTransientError("down"), kind=constants.KIND_SIP_USER)

        with self.assertRaises(SIPProvisioningError):
            self._provision()

        self.assertEqual("already-issued", self.fake.secrets[SECRET_NAME][NAME])

    def test_deprovision_removes_everything_in_reverse_order(self):
        self._provision()

        self.provisioner.deprovision(CHANNEL_UUID)

        for kind in constants.CUSTOM_RESOURCE_KINDS:
            self.assertEqual([], self.fake.names(kind))
        self.assertEqual({}, self.fake.secrets[SECRET_NAME])
        deleted = [call[1] for call in self.fake.calls_of("delete")]
        self.assertEqual(list(reversed(constants.CUSTOM_RESOURCE_KINDS)), deleted)

    def test_deprovision_treats_missing_objects_as_deleted(self):
        self.provisioner.deprovision(CHANNEL_UUID)  # nothing exists

    def test_deprovision_attempts_every_step_then_reports_the_failure(self):
        self._provision()
        self.fake.fail("delete", KubernetesTransientError("down"), kind=constants.KIND_SIP_USER, times=1)

        with self.assertRaises(SIPProvisioningError):
            self.provisioner.deprovision(CHANNEL_UUID)

        self.assertEqual([NAME], self.fake.names(constants.KIND_SIP_USER))
        for kind in (constants.KIND_CALL_ROUTE, constants.KIND_DIAL_POLICY, constants.KIND_CALL_SCOPE):
            self.assertEqual([], self.fake.names(kind))
        self.assertEqual({}, self.fake.secrets[SECRET_NAME])

    def test_issue_password_replaces_the_stored_one_and_is_never_logged(self):
        self._provision()
        first = self.provisioner.issue_password(CHANNEL_UUID)
        stored_first = self.fake.secrets[SECRET_NAME][NAME]
        second = self.provisioner.issue_password(CHANNEL_UUID)

        self.assertGreaterEqual(len(first), 32)
        self.assertNotEqual(first, second)
        self.assertEqual(base64.b64encode(first.encode()).decode(), stored_first)
        self.assertEqual(base64.b64encode(second.encode()).decode(), self.fake.secrets[SECRET_NAME][NAME])
        self.assertEqual(2, len([c for c in self.fake.calls_of("patch_secret")[1:]]))

        logged = "\n".join(self.handler.text)
        self.assertNotIn(first, logged)
        self.assertNotIn(second, logged)

    def test_issue_password_failure_changes_nothing(self):
        self._provision()
        before = dict(self.fake.secrets[SECRET_NAME])
        self.fake.fail("patch_secret", KubernetesTransientError("down"))

        with self.assertRaises(SIPProvisioningError) as ctx:
            self.provisioner.issue_password(CHANNEL_UUID)

        self.assertEqual(provisioning.ERROR_UNAVAILABLE, ctx.exception.code)
        self.assertEqual(before, self.fake.secrets[SECRET_NAME])

    def test_read_status_maps_the_phase(self):
        self._provision()
        cases = [
            (None, "pending"),
            ("Pending", "pending"),
            ("Ready", "ready"),
            ("Failed", "error"),
            ("weird", "pending"),
        ]
        for phase, expected in cases:
            with self.subTest(phase=phase):
                if phase is None:
                    self.fake.resources[constants.KIND_SIP_USER][NAME].pop("status", None)
                else:
                    self.fake.set_sip_user_phase(NAME, phase)
                self.assertEqual(expected, self.provisioner.read_status(CHANNEL_UUID))

    def test_read_status_is_error_when_the_sip_user_cannot_be_read(self):
        self.assertEqual("error", self.provisioner.read_status(CHANNEL_UUID))  # missing
        self._provision()
        self.fake.fail("get", KubernetesTransientError("down"), kind=constants.KIND_SIP_USER)
        self.assertEqual("error", self.provisioner.read_status(CHANNEL_UUID))

    def test_list_managed_groups_objects_by_channel_and_ignores_unlabeled_ones(self):
        self._provision()
        self._provision(OTHER_UUID)
        stranger = manifests.build_call_scope(CHANNEL_UUID)
        stranger["metadata"]["name"] = "voice-mode-internal"
        stranger["metadata"]["labels"] = {"team": "cloud"}
        self.fake.create_resource(constants.KIND_CALL_SCOPE, stranger)
        # listed because it has the Flows label, then skipped because it has no channel uuid
        unlabeled = manifests.build_call_scope(CHANNEL_UUID)
        unlabeled["metadata"]["name"] = "tph-unlabeled"
        unlabeled["metadata"]["labels"] = {constants.MANAGED_BY_LABEL: constants.MANAGED_BY_VALUE}
        self.fake.create_resource(constants.KIND_CALL_SCOPE, unlabeled)

        found = self.provisioner.list_managed()

        self.assertEqual({str(CHANNEL_UUID), str(OTHER_UUID)}, set(found))
        self.assertEqual(set(constants.CUSTOM_RESOURCE_KINDS), set(found[str(CHANNEL_UUID)]["kinds"]))
        self.assertEqual(self.fake.now.strftime("%Y-%m-%dT%H:%M:%SZ"), found[str(CHANNEL_UUID)]["newest"])
        self.assertNotIn("voice-mode-internal", str(found))
        self.assertNotIn("tph-unlabeled", str(found))

    def test_rollback_tolerates_objects_that_are_already_gone_or_cannot_be_deleted(self):
        self.fake.fail("create", KubernetesForbidden("denied", status=403), kind=constants.KIND_SIP_USER)
        self.fake.fail("delete", KubernetesNotFound("gone", status=404), times=2)
        self.fake.fail("delete", KubernetesTransientError("down"), times=2)

        with self.assertRaises(SIPProvisioningError):
            self._provision()

        # the password entry is rolled back even when some deletes fail
        self.assertNotIn(NAME, self.fake.secret_keys())

    def test_has_password_entry_treats_a_missing_secret_as_no_and_surfaces_other_errors(self):
        del self.fake.secrets[SECRET_NAME]
        self.assertFalse(self.provisioner.has_password_entry(NAME))

        self.fake.secrets[SECRET_NAME] = {}
        self.fake.fail("get_secret", KubernetesTransientError("down"))
        with self.assertRaises(SIPProvisioningError) as ctx:
            self.provisioner.has_password_entry(NAME)
        self.assertEqual(provisioning.ERROR_UNAVAILABLE, ctx.exception.code)

    def test_build_client_uses_the_configured_namespace(self):
        client = provisioning.build_client()
        self.assertIsInstance(client, KubernetesClient)
        self.assertEqual("kubevoip", client.namespace)

    def test_configuration_errors_are_misconfigured(self):
        self.assertEqual(provisioning.ERROR_MISCONFIGURED, provisioning._code_for(KubernetesConfigurationError("x")))

    def test_patching_a_secret_that_does_not_exist_is_not_found(self):
        with self.assertRaises(KubernetesNotFound):
            self.fake.patch_secret_data("missing", {NAME: "x"})


@override_settings(**SETTINGS)
class ChannelProvisioningTest(SimpleTestCase):
    """The channel-level helpers, with a channel stand-in so they run without a database."""

    def setUp(self):
        super().setUp()
        self.fake = FakeKubernetes(SECRET_NAME)
        self.provisioner = SIPProvisioner(client=self.fake)

    def test_provision_channel_writes_only_non_sensitive_metadata(self):
        channel = make_channel(voice_mode={"enabled": True}, sip_credentials_reset_required=True)
        saved = []
        channel.save = lambda update_fields=None: saved.append(update_fields)

        provisioning.provision_channel(channel, provisioner=self.provisioner)

        self.assertEqual(
            {
                "voice_mode": {"enabled": True},
                "sip_resource_name": NAME,
                "sip_username": NAME,
                "sip_extension": "900000000042",
            },
            channel.config,
        )
        self.assertEqual([["config"]], saved)
        self.assertTrue(provisioning.channel_is_provisioned(channel))

    def test_provision_channel_failure_leaves_config_untouched(self):
        channel = make_channel()
        self.fake.fail("create", KubernetesTransientError("down"), kind=constants.KIND_CALL_ROUTE)

        with self.assertRaises(SIPProvisioningError):
            provisioning.provision_channel(channel, provisioner=self.provisioner)

        self.assertEqual({}, channel.config)

    def test_deprovision_channel_skips_channels_that_were_never_provisioned(self):
        self.assertTrue(provisioning.deprovision_channel(make_channel(), provisioner=self.provisioner))
        self.assertEqual([], self.fake.calls)

    def test_deprovision_channel_swallows_cluster_failures(self):
        channel = make_channel(sip_resource_name=NAME)
        self.fake.fail("delete", KubernetesTransientError("down"), kind=constants.KIND_SIP_USER)

        self.assertFalse(provisioning.deprovision_channel(channel, provisioner=self.provisioner))

    def test_deprovision_channel_does_not_depend_on_the_flag(self):
        channel = make_channel(sip_resource_name=NAME)

        with override_settings(TPH_SIP_PROVISIONING_ENABLED=False):
            self.assertTrue(provisioning.deprovision_channel(channel, provisioner=self.provisioner))

        self.assertTrue(self.fake.calls_of("delete"))

    def test_default_provisioner_uses_the_cluster_client(self):
        with patch.object(provisioning, "build_client", return_value=self.fake):
            provisioning.provision_channel(make_channel())

        self.assertEqual([NAME], self.fake.names(constants.KIND_SIP_USER))


@override_settings(**SETTINGS)
class ConnectionDataTest(SimpleTestCase):
    def test_connection_data_has_the_contract_fields_and_no_password(self):
        channel = make_channel(sip_username=NAME, sip_credentials_reset_required=True)

        data = build_connection_data(channel, "ready")

        self.assertEqual(
            {
                "status": "ready",
                "domain": "voip.stg.cloud.weni.ai",
                "transports": [
                    {"protocol": "tls", "port": 5061},
                    {"protocol": "udp", "port": 5060},
                    {"protocol": "tcp", "port": 5060},
                ],
                "username": NAME,
                "did": "5511912345678",
                "signaling_ips": ["203.0.113.10"],
                "media": {"ips": [], "rtp_port_range": "10000-10035"},
                "codecs": ["PCMA", "PCMU"],
                "dtmf_mode": "rfc4733",
                "credentials_reset_required": True,
            },
            data,
        )
        self.assertNotIn("password", data)

    def test_parse_transports_skips_malformed_entries(self):
        self.assertEqual([{"protocol": "udp", "port": 5060}], parse_transports(["udp:5060", "x", ":5061", "tls:abc"]))


@override_settings(**SETTINGS)
class IssueRateLimitTest(SimpleTestCase):
    def test_limit_applies_per_channel_and_window(self):
        redis = FakeRedis()

        for _ in range(5):
            provisioning.check_issue_rate(CHANNEL_UUID, redis=redis)
        self.assertEqual(constants.SIP_CREDENTIALS_WINDOW_SECS, redis.ttls[f"tph-sip-credentials:{CHANNEL_UUID}"])

        with self.assertRaises(SIPRateLimitError) as ctx:
            provisioning.check_issue_rate(CHANNEL_UUID, redis=redis)
        self.assertEqual(constants.SIP_CREDENTIALS_WINDOW_SECS, ctx.exception.retry_after)

        # another channel has its own counter
        provisioning.check_issue_rate(OTHER_UUID, redis=redis)

    def test_a_missing_ttl_uses_the_full_window(self):
        redis = FakeRedis()
        redis.counters[constants.SIP_CREDENTIALS_RATE_KEY % CHANNEL_UUID] = 5

        with self.assertRaises(SIPRateLimitError) as ctx:
            provisioning.check_issue_rate(CHANNEL_UUID, redis=redis)

        self.assertEqual(constants.SIP_CREDENTIALS_WINDOW_SECS, ctx.exception.retry_after)
