from django.db import IntegrityError, transaction
from django.utils import timezone

from temba.contacts.models import URN
from temba.tests import TembaTest
from temba.wa_conversation_handovers.models import WAConversationHandover


class WAConversationHandoverModelTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.channel = self.create_channel("WA", "WhatsApp", "1234567890")
        self.contact = self.create_contact("Ana", phone="+5511999999999")
        self.contact_urn = self.contact.get_urn(URN.TEL_SCHEME).identity
        self.occurred_on = timezone.now()

    def _create_handover(self, context_type=WAConversationHandover.CONTEXT_TYPE_SUMMARY, **overrides):
        defaults = {
            "org": self.org,
            "channel": self.channel,
            "contact": self.contact,
            "contact_urn": self.contact_urn,
            "context_type": context_type,
            "context_text": "Hello from summary"
            if context_type == WAConversationHandover.CONTEXT_TYPE_SUMMARY
            else "[user] Hi\n[business] Hello",
            "context_payload": {"summary": {"text": "Hello from summary"}},
            "occurred_on": self.occurred_on,
        }
        defaults.update(overrides)
        return WAConversationHandover.objects.create(**defaults)

    def test_create_history_and_summary(self):
        summary = self._create_handover(context_type=WAConversationHandover.CONTEXT_TYPE_SUMMARY)
        other_contact = self.create_contact("Bob", phone="+5511888888888")
        history = self._create_handover(
            context_type=WAConversationHandover.CONTEXT_TYPE_HISTORY,
            context_text="[user] Hi\n[business] Hello",
            context_payload={"history": {"items": []}},
            contact=other_contact,
            contact_urn=other_contact.get_urn(URN.TEL_SCHEME).identity,
        )

        self.assertEqual(summary.context_type, WAConversationHandover.CONTEXT_TYPE_SUMMARY)
        self.assertEqual(history.context_type, WAConversationHandover.CONTEXT_TYPE_HISTORY)
        self.assertIsNone(summary.consumed_on)
        self.assertIsNone(history.consumed_on)

    def test_invalid_context_type_rejected(self):
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                WAConversationHandover.objects.create(
                    org=self.org,
                    channel=self.channel,
                    contact=self.contact,
                    contact_urn=self.contact_urn,
                    context_type="standby",
                    context_text="not allowed",
                    occurred_on=self.occurred_on,
                )

    def test_second_pending_on_same_channel_contact_rejected(self):
        self._create_handover()

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                self._create_handover(context_text="another pending")

    def test_consumed_on_allows_new_pending(self):
        first = self._create_handover()
        first.consumed_on = timezone.now()
        first.consumed_msg_id = 42
        first.save(update_fields=["consumed_on", "consumed_msg_id"])

        second = self._create_handover(context_text="new pending after consume")
        self.assertIsNone(second.consumed_on)
        self.assertEqual(
            WAConversationHandover.objects.filter(
                channel=self.channel, contact=self.contact, consumed_on__isnull=True
            ).count(),
            1,
        )

    def test_related_names(self):
        handover = self._create_handover()

        self.assertIn(handover, self.org.wa_conversation_handovers.all())
        self.assertIn(handover, self.contact.wa_conversation_handovers.all())
        self.assertIn(handover, self.channel.wa_conversation_handovers.all())
