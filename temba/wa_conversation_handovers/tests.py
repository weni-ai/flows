from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from temba.contacts.models import URN
from temba.tests import TembaTest
from temba.wa_conversation_handovers import tasks
from temba.wa_conversation_handovers.models import WAConversationHandover
from temba.wa_conversation_handovers.tasks import trim_wa_conversation_handovers_task


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


class TrimWAConversationHandoversTaskTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.channel = self.create_channel("WA", "WhatsApp", "1234567890")
        self.num_contacts = 0

    def _create_handover(self, created_on, consumed_on=None, contact=None, text="[user] Hi", occurred_on=None):
        if contact is None:
            self.num_contacts += 1
            contact = self.create_contact(f"Contact {self.num_contacts}", phone=f"+55119000000{self.num_contacts:02d}")

        return WAConversationHandover.objects.create(
            org=self.org,
            channel=self.channel,
            contact=contact,
            contact_urn=contact.get_urn(URN.TEL_SCHEME).identity,
            context_type=WAConversationHandover.CONTEXT_TYPE_HISTORY,
            context_text=text,
            occurred_on=occurred_on or created_on,
            created_on=created_on,
            consumed_on=consumed_on,
            consumed_msg_id=42 if consumed_on else None,
        )

    def _remaining_ids(self):
        return set(WAConversationHandover.objects.values_list("id", flat=True))

    def _trim(self):
        with self.assertLogs("temba.wa_conversation_handovers.tasks", level="INFO") as logs:
            trim_wa_conversation_handovers_task()

        self.assertEqual(1, len(logs.output))
        return logs.output[0]

    def test_trim_mixed_rows(self):
        now = timezone.now()
        consumed_recent = self._create_handover(now - timedelta(hours=2), consumed_on=now - timedelta(minutes=1))
        consumed_old = self._create_handover(now - timedelta(days=4), consumed_on=now - timedelta(days=3))
        expired = self._create_handover(now - timedelta(hours=25))
        valid = self._create_handover(now - timedelta(hours=1))
        old_event = self._create_handover(now, occurred_on=now - timedelta(days=3))

        # written two days ago, then appended to by Courier, which resets created_on
        appended = self._create_handover(now - timedelta(days=2))
        WAConversationHandover.objects.filter(id=appended.id).update(
            context_text="[user] Hi\n[business] Hello", created_on=timezone.now()
        )

        next_pending = self._create_handover(
            now - timedelta(minutes=30), contact=consumed_recent.contact, text="[user] Again"
        )

        log = self._trim()

        self.assertEqual({valid.id, old_event.id, appended.id, next_pending.id}, self._remaining_ids())

        appended.refresh_from_db()
        self.assertEqual("[user] Hi\n[business] Hello", appended.context_text)

        kept = WAConversationHandover.objects.get(id=next_pending.id)
        self.assertEqual("[user] Again", kept.context_text)
        self.assertEqual(next_pending.created_on, kept.created_on)
        self.assertIsNone(kept.consumed_on)

        self.assertIn("Deleted 3 wa conversation handovers", log)
        for handover in (consumed_recent, consumed_old, expired):
            self.assertNotIn(handover.contact_urn, log)
            self.assertNotIn(handover.context_text, log)

    def test_trim_retention_boundary(self):
        now = timezone.now()
        self._create_handover(now - timedelta(hours=24))
        inside = self._create_handover(now - timedelta(hours=23, minutes=59))

        with patch("django.utils.timezone.now", return_value=now):
            trim_wa_conversation_handovers_task()

        self.assertEqual({inside.id}, self._remaining_ids())

    @patch.object(tasks, "TRIM_BATCH_SIZE", 2)
    def test_trim_in_batches(self):
        now = timezone.now()
        for _ in range(5):
            self._create_handover(now - timedelta(days=2))
        valid = self._create_handover(now - timedelta(hours=1))

        with CaptureQueriesContext(connection) as queries:
            trim_wa_conversation_handovers_task()

        deletes = [q["sql"] for q in queries.captured_queries if q["sql"].startswith("DELETE")]
        self.assertEqual(3, len(deletes))
        for sql in deletes:
            self.assertIn('"consumed_on" IS NOT NULL', sql)
            self.assertIn('"created_on" <=', sql)

        self.assertEqual({valid.id}, self._remaining_ids())

    def test_trim_keeps_row_written_after_selection(self):
        now = timezone.now()
        refreshed = self._create_handover(now - timedelta(days=2), text="[user] Old")
        expired = self._create_handover(now - timedelta(days=2))

        select_trim_ids = tasks._select_trim_ids
        selections = []

        def select_then_courier_writes(trim_before, limit):
            ids = select_trim_ids(trim_before, limit)
            selections.append(ids)
            WAConversationHandover.objects.filter(id=refreshed.id).update(
                context_text="[user] Old\n[user] New", created_on=timezone.now()
            )
            return ids

        with patch.object(tasks, "_select_trim_ids", side_effect=select_then_courier_writes):
            log = self._trim()

        self.assertEqual({refreshed.id, expired.id}, set(selections[0]))
        self.assertEqual({refreshed.id}, self._remaining_ids())

        refreshed.refresh_from_db()
        self.assertEqual("[user] Old\n[user] New", refreshed.context_text)
        self.assertIn("Deleted 1 wa conversation handovers", log)

    def test_trim_with_nothing_eligible(self):
        self.assertIn("Deleted 0 wa conversation handovers", self._trim())

        valid = self._create_handover(timezone.now() - timedelta(hours=1))

        self.assertIn("Deleted 0 wa conversation handovers", self._trim())
        self.assertEqual({valid.id}, self._remaining_ids())

    def test_schedule_and_retention(self):
        self.assertEqual("trim_wa_conversation_handovers_task", trim_wa_conversation_handovers_task.name)
        self.assertEqual(
            {"task": "trim_wa_conversation_handovers_task", "schedule": timedelta(minutes=15)},
            settings.CELERY_BEAT_SCHEDULE["trim-wa-conversation-handovers"],
        )
        self.assertEqual(timedelta(hours=24), settings.RETENTION_PERIODS["wa_conversation_handover"])
