from temba.tests.base import TembaTest
from temba.triggers.models import Trigger
from temba.triggers.usecases import create_catchall_trigger


class CreateCatchallTriggerTestCase(TembaTest):
    def test_create_without_groups_defaults_to_empty(self):
        flow = self.create_flow()

        trigger = create_catchall_trigger(org=self.org, user=self.admin, flow=flow)

        self.assertIsInstance(trigger, Trigger)
        self.assertEqual(trigger.org, self.org)
        self.assertEqual(trigger.flow, flow)
        self.assertEqual(trigger.trigger_type, Trigger.TYPE_CATCH_ALL)
        self.assertEqual(trigger.groups.count(), 0)

    def test_create_with_groups_assigns_groups(self):
        flow = self.create_flow()
        group1 = self.create_group("Group 1", contacts=[])
        group2 = self.create_group("Group 2", contacts=[])

        trigger = create_catchall_trigger(org=self.org, user=self.admin, flow=flow, groups=[group1, group2])

        self.assertIsInstance(trigger, Trigger)
        self.assertEqual(trigger.org, self.org)
        self.assertEqual(trigger.flow, flow)
        self.assertEqual(trigger.trigger_type, Trigger.TYPE_CATCH_ALL)
        self.assertEqual({group1, group2}, set(trigger.groups.all()))
