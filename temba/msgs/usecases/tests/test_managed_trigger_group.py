from temba.contacts.models import ContactGroup
from temba.flows.models import Flow
from temba.msgs.models import ManagedTriggerGroup
from temba.msgs.usecases.managed_trigger_group import (
    ContactResolutionError,
    GroupQuotaExceeded,
    managed_trigger_group_display_name,
    prepare_trigger_group_for_broadcast,
    resolve_contacts_for_urns,
    resolve_or_create_managed_trigger_group,
)
from temba.orgs.models import Org
from temba.tests.base import TembaTest
from temba.tests.mailroom import mock_mailroom
from temba.triggers.models import Trigger


class ManagedTriggerGroupUseCaseTest(TembaTest):
    def test_display_name_truncates_and_stays_valid(self):
        flow = self.create_flow(name="x" * 80)
        name = managed_trigger_group_display_name(flow)
        self.assertTrue(ContactGroup.is_valid_name(name))
        self.assertLessEqual(len(name), ContactGroup.MAX_NAME_LEN)
        self.assertTrue(name.startswith("Trigger · "))

    def test_display_name_uses_flow_name(self):
        flow = self.create_flow(name="Billing replies")
        self.assertEqual(managed_trigger_group_display_name(flow), "Trigger · Billing replies")

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
    def test_contact_create_failure_raises_resolution_error(self, mocks):
        mocks.error("boom")
        with self.assertRaises(ContactResolutionError):
            resolve_contacts_for_urns(self.org, self.admin, ["whatsapp:5511777777777"])
