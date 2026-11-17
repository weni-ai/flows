import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from . import constants, manifests
from .fake_kubernetes import FakeKubernetes
from .kubernetes_client import KubernetesTransientError
from .provisioning import SIPProvisioner, SIPProvisioningError
from .reconciliation import reconcile
from .tests_provisioning import ADDRESS, CHANNEL_ID, CHANNEL_UUID, NAME, OTHER_UUID, SECRET_NAME, SETTINGS


class StoredChannel(SimpleNamespace):
    """A channel stand-in that records what is saved."""

    def save(self, update_fields=None):
        self.saved = update_fields


def make_channel(channel_uuid=CHANNEL_UUID, channel_id=CHANNEL_ID, provisioned=True):
    config = {constants.CONFIG_SIP_RESOURCE_NAME: manifests.resource_name(channel_uuid)} if provisioned else {}
    return StoredChannel(uuid=channel_uuid, id=channel_id, address=ADDRESS, org_id=7, created_by_id=9, config=config)


@override_settings(**SETTINGS)
class ReconcileTest(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeKubernetes(SECRET_NAME)
        self.provisioner = SIPProvisioner(client=self.fake)

    def provision(self, channel_uuid=CHANNEL_UUID, channel_id=CHANNEL_ID):
        self.provisioner.provision(channel_uuid, channel_id, ADDRESS)

    def run_reconcile(self, channels, **kwargs):
        return reconcile(channels, provisioner=self.provisioner, **kwargs)

    def test_consistent_state_changes_nothing(self):
        self.provision()
        self.fake.age_all(3600)

        summary = self.run_reconcile([make_channel()])

        self.assertEqual({"deleted": 0, "recreated": 0, "errors": 0, "capped": False}, summary)
        self.assertEqual(set(constants.CUSTOM_RESOURCE_KINDS), set(self.fake.kinds_present()))

    def test_objects_of_an_inactive_channel_are_deleted(self):
        self.provision(OTHER_UUID, 99)
        self.fake.age_all(3600)

        summary = self.run_reconcile([])

        self.assertEqual(1, summary["deleted"])
        self.assertEqual([], self.fake.names(constants.KIND_SIP_USER))
        self.assertNotIn(manifests.resource_name(OTHER_UUID), self.fake.secret_keys())

    def test_recent_objects_are_left_alone_because_a_claim_may_still_be_running(self):
        self.provision(OTHER_UUID, 99)

        summary = self.run_reconcile([])

        self.assertEqual(0, summary["deleted"])
        self.assertEqual([manifests.resource_name(OTHER_UUID)], self.fake.names(constants.KIND_SIP_USER))

    def test_an_unreadable_timestamp_is_treated_as_recent(self):
        self.provision(OTHER_UUID, 99)
        for body in self.fake.resources[constants.KIND_SIP_USER].values():
            body["metadata"]["creationTimestamp"] = "yesterday"

        self.assertEqual(0, self.run_reconcile([])["deleted"])

    def test_objects_of_an_active_channel_that_is_not_marked_provisioned_are_kept(self):
        self.provision()
        self.fake.age_all(3600)

        summary = self.run_reconcile([make_channel(provisioned=False)])

        self.assertEqual(0, summary["deleted"])
        self.assertEqual([NAME], self.fake.names(constants.KIND_SIP_USER))

    def test_deletions_are_capped_per_run(self):
        total = constants.RECONCILE_MAX_DELETIONS_PER_RUN + 3
        for number in range(total):
            self.provision(uuid.uuid4(), 1000 + number)
        self.fake.age_all(3600)

        summary = self.run_reconcile([])

        self.assertTrue(summary["capped"])
        self.assertEqual(constants.RECONCILE_MAX_DELETIONS_PER_RUN, summary["deleted"])
        self.assertEqual(3, len(self.fake.names(constants.KIND_SIP_USER)))

    def test_a_listing_failure_stops_the_run_without_deleting(self):
        self.provision(OTHER_UUID, 99)
        self.fake.age_all(3600)
        self.fake.fail("list", KubernetesTransientError("down"))

        with self.assertRaises(SIPProvisioningError):
            self.run_reconcile([])

        self.assertEqual([manifests.resource_name(OTHER_UUID)], self.fake.names(constants.KIND_SIP_USER))

    def test_a_failure_on_one_channel_does_not_stop_the_others(self):
        self.provision(OTHER_UUID, 99)
        self.provision(uuid.uuid4(), 1)
        self.fake.age_all(3600)
        self.fake.fail("delete", KubernetesTransientError("down"), kind=constants.KIND_SIP_USER, times=1)

        summary = self.run_reconcile([])

        self.assertEqual(1, summary["errors"])
        self.assertEqual(1, summary["deleted"])
        self.assertEqual(1, len(self.fake.names(constants.KIND_SIP_USER)))  # only the one that failed is left

    def test_missing_sip_user_with_surviving_password_is_recreated_without_reset(self):
        self.provision()
        self.fake.age_all(3600)
        del self.fake.resources[constants.KIND_SIP_USER][NAME]
        password_before = self.fake.secret_data()[NAME]
        channel = make_channel()

        summary = self.run_reconcile([channel])

        self.assertEqual(1, summary["recreated"])
        self.assertEqual([NAME], self.fake.names(constants.KIND_SIP_USER))
        self.assertEqual(password_before, self.fake.secret_data()[NAME])  # the customer's password still works
        self.assertNotIn(constants.CONFIG_SIP_RESET_REQUIRED, channel.config)

    def test_cluster_wiped_recreates_everything_and_requires_a_reset(self):
        channel = make_channel()  # the database says provisioned, the cluster is empty

        summary = self.run_reconcile([channel])

        self.assertEqual(1, summary["recreated"])
        self.assertEqual([NAME], self.fake.names(constants.KIND_SIP_USER))
        self.assertTrue(channel.config[constants.CONFIG_SIP_RESET_REQUIRED])
        self.assertEqual(["config"], channel.saved)
        self.assertEqual(NAME, channel.config[constants.CONFIG_SIP_RESOURCE_NAME])

    def test_now_can_be_injected(self):
        self.provision(OTHER_UUID, 99)
        later = datetime.now(timezone.utc).replace(year=datetime.now().year + 1)

        self.assertEqual(1, self.run_reconcile([], now=later)["deleted"])

    def test_objects_without_a_timestamp_are_old_enough_to_delete(self):
        self.provision(OTHER_UUID, 99)
        for bodies in self.fake.resources.values():
            for body in bodies.values():
                body["metadata"].pop("creationTimestamp", None)

        self.assertEqual(1, self.run_reconcile([])["deleted"])

    def test_a_recreate_failure_is_counted_and_does_not_stop_the_run(self):
        channel = make_channel()
        self.fake.fail("create", KubernetesTransientError("down"), times=20)

        summary = self.run_reconcile([channel])

        self.assertEqual(1, summary["errors"])
        self.assertEqual(0, summary["recreated"])
        self.assertEqual([], self.fake.names(constants.KIND_SIP_USER))

    def test_celery_task_runs_reconciliation(self):
        from temba.channels.tasks import reconcile_tph_sip_task

        redis = MagicMock()
        redis.get.return_value = None
        redis.lock.return_value.__enter__.return_value = True
        redis.lock.return_value.__exit__.return_value = False

        with patch("temba.utils.celery.get_redis_connection", return_value=redis):
            with patch("temba.channels.types.telephony.reconciliation.run_reconciliation") as run:
                reconcile_tph_sip_task()

        run.assert_called_once_with()
