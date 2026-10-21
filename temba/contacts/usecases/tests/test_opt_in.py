from unittest.mock import patch

import requests

from django.db import IntegrityError, transaction

from temba import mailroom
from temba.contacts.models import URN, Contact, ContactField, ContactGroup, ContactURN
from temba.contacts.usecases.opt_in import OptInUnavailable, create_opt_in_contact, ensure_audience, fill_identifier
from temba.mailroom.client import MailroomException
from temba.orgs.models import Org
from temba.tests import TembaTest
from temba.tests.mailroom import Mocks, TestClient


class OptInUseCaseTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.mailroom = patch("temba.mailroom.get_client", return_value=TestClient(Mocks()))
        self.queue = patch("temba.mailroom.queue._queue_batch_task")
        self.mailroom.start()
        self.queue.start()

    def tearDown(self):
        self.queue.stop()
        self.mailroom.stop()
        super().tearDown()

    def test_ensure_creates_then_reuses(self):
        first = ensure_audience(self.org, self.user)
        second = ensure_audience(self.org, self.user)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.group.id, second.group.id)
        self.assertEqual(first.group.name, "Opt-in")
        self.assertIsNone(first.group.query)
        self.assertEqual(first.group.get_member_count(), 0)

    def test_ensure_adopts_static_group(self):
        existing = self.create_group("Opt-in")
        result = ensure_audience(self.org, self.user)
        self.assertTrue(result.created)
        self.assertEqual(result.group.id, existing.id)

    def test_ensure_rejects_smart_group_name(self):
        self.create_group("Opt-in", query='name != ""')
        result = ensure_audience(self.org, self.user)
        self.assertEqual(result.error, "opt_in_name_taken")
        self.assertFalse(ContactGroup.all_groups.filter(org=self.org, is_opt_in=True).exists())

    def test_ensure_respects_group_limit(self):
        limits = dict(self.org.limits or {})
        limits[Org.LIMIT_GROUPS] = ContactGroup.user_groups.filter(org=self.org).count()
        self.org.limits = limits
        self.org.save(update_fields=["limits"])

        result = ensure_audience(self.org, self.user)
        self.assertEqual(result.error, "group_limit_reached")

    def test_ensure_repoints_inactive_group(self):
        first = ensure_audience(self.org, self.user)
        first.group.release(self.user)
        second = ensure_audience(self.org, self.user)
        self.assertTrue(second.created)
        self.assertNotEqual(second.group.id, first.group.id)
        self.assertTrue(second.group.is_active)

    def test_create_new_number(self):
        ensure_audience(self.org, self.user)
        client = mailroom.get_client()
        before = len(client.mocks.calls["contact_create"])
        result = create_opt_in_contact(self.org, self.user, "Maria", "5561912345678", "maria@example.com")
        self.assertEqual(len(client.mocks.calls["contact_create"]) - before, 1)
        self.assertEqual(result.outcome, "created")
        contact = result.contact
        self.assertEqual(contact.name, "Maria")
        self.assertTrue(contact.urns.filter(identity="whatsapp:5561912345678").exists())
        self.assertFalse(contact.urns.filter(scheme="weniwebchat").exists())
        self.assertTrue(contact.user_groups.filter(id=result.group.id).exists())
        email = ContactField.user_fields.get(org=self.org, key="email")
        self.assertEqual(contact.get_field_value(email), "maria@example.com")

    def test_same_number_on_another_org_is_created(self):
        ensure_audience(self.org, self.user)
        ensure_audience(self.org2, self.user)
        first = create_opt_in_contact(self.org, self.user, "Maria", "5561912345678", None)
        second = create_opt_in_contact(self.org2, self.user, "Maria", "5561912345678", None)
        self.assertEqual(first.outcome, "created")
        self.assertEqual(second.outcome, "created")
        self.assertNotEqual(first.contact.id, second.contact.id)

    def test_create_without_audience(self):
        result = create_opt_in_contact(self.org, self.user, "Maria", "5561912345678", None)
        self.assertEqual(result.outcome, "missing")

    def test_create_when_audience_group_is_inactive(self):
        result = ensure_audience(self.org, self.user)
        result.group.release(self.user)
        created = create_opt_in_contact(self.org, self.user, "Maria", "5561912345678", None)
        self.assertEqual(created.outcome, "missing")

    def test_duplicate_for_every_status(self):
        ensure_audience(self.org, self.user)
        urn = "whatsapp:5561912345678"
        contact = self.create_contact("Kept", urns=[urn])
        cases = [
            {},
            {"status": Contact.STATUS_BLOCKED},
            {"status": Contact.STATUS_STOPPED},
            {"status": Contact.STATUS_ARCHIVED},
            {"is_active": False},
        ]
        for updates in cases:
            contact.status = updates.get("status", Contact.STATUS_ACTIVE)
            contact.is_active = updates.get("is_active", True)
            contact.save(update_fields=["status", "is_active"])
            before = contact.modified_on
            result = create_opt_in_contact(self.org, self.user, "Other", "5561912345678", "other@example.com")
            contact.refresh_from_db()
            self.assertEqual(result.outcome, "duplicate")
            self.assertEqual(contact.name, "Kept")
            self.assertEqual(contact.modified_on, before)
            self.assertEqual(contact.urns.get().identity, urn)

    def test_brazilian_ninth_digit_is_duplicate(self):
        ensure_audience(self.org, self.user)
        self.create_contact("Kept", urns=["whatsapp:556181234567"])
        result = create_opt_in_contact(self.org, self.user, "Other", "5561981234567", None)
        self.assertEqual(result.outcome, "duplicate")
        self.assertEqual(Contact.objects.filter(org=self.org).count(), 1)

    def test_tel_and_bsuid_are_not_duplicates(self):
        ensure_audience(self.org, self.user)
        self.create_contact("Tel", urns=["tel:+5561911111111"])
        self.create_contact("Bsuid", urns=["whatsapp:BR.35029025746744354"])
        result = create_opt_in_contact(self.org, self.user, "New", "5561911111111", None)
        self.assertEqual(result.outcome, "created")

    def test_orphaned_urn_is_not_a_duplicate(self):
        ensure_audience(self.org, self.user)
        ContactURN.objects.create(
            org=self.org,
            contact=None,
            scheme=URN.WHATSAPP_SCHEME,
            path="5561922222222",
            identity="whatsapp:5561922222222",
            priority=ContactURN.PRIORITY_HIGHEST,
        )
        result = create_opt_in_contact(self.org, self.user, "New", "5561922222222", None)
        self.assertEqual(result.outcome, "created")

    def test_same_email_does_not_block_create(self):
        ensure_audience(self.org, self.user)
        create_opt_in_contact(self.org, self.user, "Maria", "5561912345678", "shared@example.com")
        result = create_opt_in_contact(self.org, self.user, "Joao", "5561933333333", "shared@example.com")
        self.assertEqual(result.outcome, "created")

    def test_field_limit_skips_email(self):
        ensure_audience(self.org, self.user)
        limits = dict(self.org.limits or {})
        limits[Org.LIMIT_FIELDS] = ContactField.user_fields.filter(org=self.org, is_active=True).count()
        self.org.limits = limits
        self.org.save(update_fields=["limits"])
        with self.assertLogs("temba.contacts.usecases.opt_in", level="WARNING") as logs:
            result = create_opt_in_contact(self.org, self.user, "Maria", "5561912345678", "maria@example.com")
        self.assertEqual(result.outcome, "created")
        self.assertFalse(ContactField.user_fields.filter(org=self.org, key="email").exists())
        self.assertIn(str(self.org.id), "\n".join(logs.output))
        self.assertNotIn("maria@example.com", "\n".join(logs.output))

    def test_urn_in_use_race_is_duplicate(self):
        ensure_audience(self.org, self.user)
        contact = self.create_contact("Kept", urns=["whatsapp:5561944444444"])
        client = mailroom.get_client()
        error = MailroomException("contact/create", None, {"error": "URNs in use by other contacts"})
        with patch("temba.contacts.usecases.opt_in._find_duplicate", side_effect=[None, contact]):
            with patch.object(client, "contact_create", side_effect=error):
                result = create_opt_in_contact(self.org, self.user, "Other", "5561944444444", None)
        self.assertEqual(result.outcome, "duplicate")
        self.assertEqual(ContactURN.objects.filter(org=self.org, identity="whatsapp:5561944444444").count(), 1)

    def test_mailroom_timeout_is_unavailable(self):
        ensure_audience(self.org, self.user)
        client = mailroom.get_client()
        with patch.object(client, "contact_create", side_effect=requests.Timeout()):
            with self.assertRaises(OptInUnavailable):
                create_opt_in_contact(self.org, self.user, "Maria", "5561955555555", None)

    def test_other_mailroom_error_is_unavailable(self):
        ensure_audience(self.org, self.user)
        client = mailroom.get_client()
        error = MailroomException("contact/create", None, {"error": "database down"})
        with patch.object(client, "contact_create", side_effect=error):
            with self.assertRaises(OptInUnavailable):
                create_opt_in_contact(self.org, self.user, "Maria", "5561966666666", None)

    def test_fill_identifier_only_when_empty_member(self):
        group = ensure_audience(self.org, self.user).group
        created = create_opt_in_contact(self.org, self.user, "Maria", "5561977777777", None)
        self.assertEqual(fill_identifier(self.org, self.user, created.contact, "maria@example.com"), "updated")
        self.assertEqual(fill_identifier(self.org, self.user, created.contact, "other@example.com"), "unchanged")
        email = ContactField.user_fields.get(org=self.org, key="email")
        created.contact.refresh_from_db()
        self.assertEqual(created.contact.get_field_value(email), "maria@example.com")

        outsider = self.create_contact("Out", urns=["whatsapp:5561988888888"])
        self.assertEqual(fill_identifier(self.org, self.user, outsider, "out@example.com"), "unchanged")
        self.assertFalse(outsider.user_groups.filter(id=group.id).exists())

    def test_second_active_opt_in_group_is_rejected(self):
        ensure_audience(self.org, self.user)
        other = self.create_group("Another")
        other.is_opt_in = True
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                other.save(update_fields=["is_opt_in"])

    def test_ensure_audience_returns_active_group_when_flag_conflicts(self):
        winner = ensure_audience(self.org, self.user).group
        other = self.create_group("Another")
        calls = {"count": 0}

        def active_audience(org):
            calls["count"] += 1
            if calls["count"] == 1:
                return None
            return ContactGroup.all_groups.get(id=winner.id, org=org)

        with patch("temba.contacts.usecases.opt_in._active_audience", side_effect=active_audience):
            with patch(
                "temba.contacts.usecases.opt_in.ContactGroup.user_groups.filter",
                return_value=ContactGroup.all_groups.filter(id=other.id),
            ):
                result = ensure_audience(self.org, self.user)

        other.refresh_from_db()
        self.assertFalse(result.created)
        self.assertIsNone(result.error)
        self.assertEqual(result.group.id, winner.id)
        self.assertFalse(other.is_opt_in)

    def test_inactive_opt_in_group_does_not_block_a_new_one(self):
        first = ensure_audience(self.org, self.user)
        first.group.release(self.user)
        second = ensure_audience(self.org, self.user)
        first.group.refresh_from_db()
        self.assertTrue(first.group.is_opt_in)
        self.assertFalse(first.group.is_active)
        self.assertTrue(second.group.is_opt_in)
        self.assertTrue(second.group.is_active)
