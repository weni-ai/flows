from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.db.utils import IntegrityError
from django.test import override_settings

from temba.contacts.models import ContactGroup
from temba.flows.models import Flow
from temba.msgs.models import ManagedTriggerGroup
from temba.msgs.usecases.managed_trigger_group import (
    ContactResolutionError,
    GroupQuotaExceeded,
    _create_contact_in_thread,
    assign_exclusive_membership,
    managed_trigger_group_display_name,
    prepare_trigger_group_for_broadcast,
    resolve_contacts_for_urns,
    resolve_or_create_managed_trigger_group,
)
from temba.orgs.models import Org
from temba.tests.base import TembaTest
from temba.tests.mailroom import mock_mailroom
from temba.triggers.models import Trigger


class ImmediateExecutor:
    """Runs ThreadPoolExecutor.submit in the calling thread so tests can cover the concurrent path."""

    def __init__(self, max_workers=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future


class ManagedTriggerGroupUseCaseTest(TembaTest):
    def test_display_name_truncates_and_stays_valid(self):
        # Flow.name is varchar(64); truncation must still work for longer product names.
        flow = SimpleNamespace(name="x" * 80)
        name = managed_trigger_group_display_name(flow)
        self.assertTrue(ContactGroup.is_valid_name(name))
        self.assertLessEqual(len(name), ContactGroup.MAX_NAME_LEN)
        self.assertTrue(name.startswith("Trigger · "))

    def test_display_name_uses_flow_name(self):
        flow = self.create_flow(name="Billing replies")
        self.assertEqual(managed_trigger_group_display_name(flow), "Trigger · Billing replies")

    def test_display_name_fallback_when_limit_shorter_than_prefix(self):
        with patch.object(ContactGroup, "MAX_NAME_LEN", 5):
            with patch.object(ContactGroup, "clean_name", side_effect=lambda name: name):
                self.assertEqual(
                    managed_trigger_group_display_name(SimpleNamespace(name="Billing")), "Broadcast trigger"
                )

    def test_display_name_uses_flow_fallback_when_empty(self):
        self.assertEqual(managed_trigger_group_display_name(SimpleNamespace(name=None)), "Trigger · flow")
        self.assertEqual(managed_trigger_group_display_name(SimpleNamespace(name="")), "Trigger · flow")

    def test_display_name_fallback_when_cleaned_name_is_invalid(self):
        with patch.object(ContactGroup, "is_valid_name", return_value=False):
            self.assertEqual(managed_trigger_group_display_name(SimpleNamespace(name="Billing")), "Broadcast trigger")

    @mock_mailroom
    def test_resolve_creates_group_and_catchall_once(self, mocks):
        flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)

        group1 = resolve_or_create_managed_trigger_group(self.org, self.admin, flow)
        group2 = resolve_or_create_managed_trigger_group(self.org, self.admin, flow)

        self.assertEqual(group1.id, group2.id)
        self.assertEqual(ManagedTriggerGroup.objects.filter(org=self.org, flow=flow).count(), 1)
        self.assertEqual(
            Trigger.objects.filter(
                org=self.org, flow=flow, trigger_type=Trigger.TYPE_CATCH_ALL, is_archived=False, groups=group1
            ).count(),
            1,
        )

    @mock_mailroom
    def test_quota_blocks_new_group_but_not_reuse(self, mocks):
        flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
        group = resolve_or_create_managed_trigger_group(self.org, self.admin, flow)

        self.org.limits = {Org.LIMIT_GROUPS: ContactGroup.user_groups.filter(org=self.org).count()}
        self.org.save(update_fields=("limits",))

        reused = resolve_or_create_managed_trigger_group(self.org, self.admin, flow)
        self.assertEqual(group.id, reused.id)

        other = self.create_flow(name="Other", flow_type=Flow.TYPE_MESSAGE)
        with self.assertRaises(GroupQuotaExceeded):
            resolve_or_create_managed_trigger_group(self.org, self.admin, other)

    @mock_mailroom
    def test_recreates_inactive_group_and_restores_catchall(self, mocks):
        flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
        group = resolve_or_create_managed_trigger_group(self.org, self.admin, flow)
        trigger = Trigger.objects.get(flow=flow, trigger_type=Trigger.TYPE_CATCH_ALL, groups=group)
        trigger.archive(self.admin)
        group.release(self.admin)

        new_group = resolve_or_create_managed_trigger_group(self.org, self.admin, flow)
        self.assertNotEqual(group.id, new_group.id)
        self.assertTrue(new_group.is_active)
        self.assertEqual(
            Trigger.objects.filter(
                org=self.org, flow=flow, trigger_type=Trigger.TYPE_CATCH_ALL, is_archived=False, groups=new_group
            ).count(),
            1,
        )

    @mock_mailroom
    def test_restores_archived_catchall_on_same_group(self, mocks):
        flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
        group = resolve_or_create_managed_trigger_group(self.org, self.admin, flow)
        trigger = Trigger.objects.get(flow=flow, trigger_type=Trigger.TYPE_CATCH_ALL, groups=group)
        trigger.archive(self.admin)

        reused = resolve_or_create_managed_trigger_group(self.org, self.admin, flow)
        trigger.refresh_from_db()
        self.assertEqual(reused.id, group.id)
        self.assertFalse(trigger.is_archived)

    @mock_mailroom
    def test_create_race_reuses_winner_and_releases_loser_group(self, mocks):
        flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
        winner = resolve_or_create_managed_trigger_group(self.org, self.admin, flow)
        association = ManagedTriggerGroup.objects.select_related("group").get(org=self.org, flow=flow)

        qs = MagicMock()
        qs.filter.return_value.first.return_value = None
        qs.get.return_value = association

        with patch.object(ManagedTriggerGroup.objects, "select_related", return_value=qs):
            with patch.object(ManagedTriggerGroup.objects, "create", side_effect=IntegrityError("duplicate")):
                reused = resolve_or_create_managed_trigger_group(self.org, self.admin, flow)

        self.assertEqual(reused.id, winner.id)
        self.assertTrue(ContactGroup.user_groups.filter(org=self.org, id=winner.id).exists())

    @mock_mailroom
    def test_create_race_skips_release_when_winner_is_same_group(self, mocks):
        flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
        created_groups = []
        real_create_static = ContactGroup.create_static

        def capture_create(*args, **kwargs):
            group = real_create_static(*args, **kwargs)
            created_groups.append(group)
            return group

        qs = MagicMock()
        qs.filter.return_value.first.return_value = None

        def get_winner(**kwargs):
            group = created_groups[0]
            association = MagicMock()
            association.group_id = group.id
            association.group = group
            return association

        qs.get.side_effect = get_winner

        with patch.object(ContactGroup, "create_static", side_effect=capture_create):
            with patch.object(ManagedTriggerGroup.objects, "select_related", return_value=qs):
                with patch.object(ManagedTriggerGroup.objects, "create", side_effect=IntegrityError("duplicate")):
                    reused = resolve_or_create_managed_trigger_group(self.org, self.admin, flow)

        self.assertEqual(reused.id, created_groups[0].id)

    @mock_mailroom
    def test_resolve_contacts_empty_urns(self, mocks):
        self.assertEqual(resolve_contacts_for_urns(self.org, self.admin, []), [])
        self.assertEqual(resolve_contacts_for_urns(self.org, self.admin, None), [])

    @mock_mailroom
    def test_prepare_trigger_group_accepts_empty_urns_and_contacts(self, mocks):
        flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
        group = prepare_trigger_group_for_broadcast(self.org, self.admin, flow, None, None)
        self.assertTrue(group.is_active)
        self.assertEqual(group.contacts.count(), 0)

    @mock_mailroom
    def test_resolve_contacts_reuses_existing_and_creates_missing(self, mocks):
        existing = self.create_contact("Ana", urns=["whatsapp:5511999999999"])
        contacts = resolve_contacts_for_urns(
            self.org, self.admin, ["whatsapp:5511999999999", "whatsapp:5511888888888", "whatsapp:5511999999999"]
        )
        self.assertEqual(len(contacts), 2)
        self.assertIn(existing, contacts)
        created = [c for c in contacts if c.id != existing.id][0]
        self.assertEqual(created.get_urn("whatsapp").identity, "whatsapp:5511888888888")

    @mock_mailroom
    def test_exclusive_membership_moves_contact(self, mocks):
        flow_a = self.create_flow(name="A", flow_type=Flow.TYPE_MESSAGE)
        flow_b = self.create_flow(name="B", flow_type=Flow.TYPE_MESSAGE)
        contact = self.create_contact("C", urns=["whatsapp:5511999999999"])

        group_a = prepare_trigger_group_for_broadcast(self.org, self.admin, flow_a, [], [contact])
        self.assertTrue(group_a.contacts.filter(id=contact.id).exists())

        group_b = prepare_trigger_group_for_broadcast(self.org, self.admin, flow_b, [], [contact])
        self.assertTrue(group_b.contacts.filter(id=contact.id).exists())
        self.assertFalse(group_a.contacts.filter(id=contact.id).exists())

    @mock_mailroom
    def test_assign_exclusive_membership_noop_without_contacts(self, mocks):
        flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
        group = resolve_or_create_managed_trigger_group(self.org, self.admin, flow)
        assign_exclusive_membership(self.org, self.admin, [], group)
        self.assertEqual(group.contacts.count(), 0)

    @mock_mailroom
    def test_assign_exclusive_membership_ignores_inactive_other_groups(self, mocks):
        flow_a = self.create_flow(name="A", flow_type=Flow.TYPE_MESSAGE)
        flow_b = self.create_flow(name="B", flow_type=Flow.TYPE_MESSAGE)
        group_a = resolve_or_create_managed_trigger_group(self.org, self.admin, flow_a)
        group_b = resolve_or_create_managed_trigger_group(self.org, self.admin, flow_b)
        group_b.release(self.admin)
        contact = self.create_contact("C", urns=["whatsapp:5511999999999"])

        assign_exclusive_membership(self.org, self.admin, [contact], group_a)
        self.assertTrue(group_a.contacts.filter(id=contact.id).exists())

    @mock_mailroom
    def test_create_contact_in_thread_does_not_close_test_connection(self, mocks):
        # close_old_connections would drop the TestCase transaction connection.
        with patch("temba.msgs.usecases.managed_trigger_group.close_old_connections") as mock_close:
            contact = _create_contact_in_thread(self.org, self.admin, "whatsapp:5511333333333")
        self.assertEqual(mock_close.call_count, 2)
        self.assertEqual(contact.get_urn("whatsapp").identity, "whatsapp:5511333333333")

    @mock_mailroom
    @override_settings(WHATSAPP_BROADCAST_URN_RESOLVE_CONCURRENCY=2)
    def test_create_contacts_concurrent_path(self, mocks):
        contact_a = MagicMock()
        contact_b = MagicMock()
        with patch("temba.msgs.usecases.managed_trigger_group.connection") as mock_conn:
            mock_conn.in_atomic_block = False
            with patch("temba.msgs.usecases.managed_trigger_group.ThreadPoolExecutor", ImmediateExecutor):
                with patch(
                    "temba.msgs.usecases.managed_trigger_group._create_contact_in_thread",
                    side_effect=[contact_a, contact_b],
                ):
                    contacts = resolve_contacts_for_urns(
                        self.org, self.admin, ["whatsapp:5511111111111", "whatsapp:5511222222222"]
                    )
        self.assertEqual(len(contacts), 2)
        self.assertCountEqual(contacts, [contact_a, contact_b])

    @mock_mailroom
    @override_settings(WHATSAPP_BROADCAST_URN_RESOLVE_CONCURRENCY=2)
    def test_create_contacts_concurrent_path_reraises_resolution_error(self, mocks):
        with patch("temba.msgs.usecases.managed_trigger_group.connection") as mock_conn:
            mock_conn.in_atomic_block = False
            with patch("temba.msgs.usecases.managed_trigger_group.ThreadPoolExecutor", ImmediateExecutor):
                with patch(
                    "temba.msgs.usecases.managed_trigger_group._create_contact_in_thread",
                    side_effect=ContactResolutionError("whatsapp:5511111111111"),
                ):
                    with self.assertRaises(ContactResolutionError):
                        resolve_contacts_for_urns(
                            self.org, self.admin, ["whatsapp:5511111111111", "whatsapp:5511222222222"]
                        )

    @mock_mailroom
    def test_contact_create_failure_raises_resolution_error(self, mocks):
        mocks.error("boom")
        with self.assertRaises(ContactResolutionError):
            resolve_contacts_for_urns(self.org, self.admin, ["whatsapp:5511777777777"])
