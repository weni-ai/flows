from unittest.mock import patch
from uuid import uuid4

from django.urls import reverse

from temba.contacts.models import Contact, ContactAnchor, ContactIdentityEvent, ContactURN
from temba.msgs.models import Protocol
from temba.tests.base import TembaTest


@patch("temba.api.v2.internals.identity.views.IdentityView.authentication_classes", [])
@patch("temba.api.v2.internals.identity.views.IdentityView.permission_classes", [])
class IdentityAPITest(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid4()
        self.org.save()
        self.org2.proj_uuid = uuid4()
        self.org2.save()

    def _post(self, name, payload):
        return self.client.post(reverse(name), data=payload, content_type="application/json")

    def test_verified_attach_creates_consumer_and_moves_a_second_urn(self):
        first = self.create_contact("Ann", urns=["tel:+250788111010"])
        second = self.create_contact("Bob", urns=["tel:+250788111011"])
        first_urn = first.urns.get()
        second_urn = second.urns.get()
        protocol = Protocol.objects.create(org=self.org, contact=second, urn=second_urn)

        created = self._post(
            "internal_identity_attach",
            {
                "project_id": str(self.org.proj_uuid),
                "urn_id": first_urn.id,
                "anchor": {"type": "commerce_user_id", "value": "store-user-42", "verified": True},
            },
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["consumer_id"], str(first.uuid))
        self.assertEqual(created.json()["attachment_status"], "confirmed")
        first_urn.refresh_from_db()
        self.assertEqual(first_urn.attachment_status, ContactURN.ATTACHMENT_CONFIRMED)

        moved = self._post(
            "internal_identity_attach",
            {
                "project_id": str(self.org.proj_uuid),
                "urn_id": second_urn.id,
                "anchor": {"type": "commerce_user_id", "value": "store-user-42", "verified": True},
            },
        )
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["consumer_id"], str(first.uuid))
        self.assertEqual(moved.json()["affected_protocol_ids"], [protocol.id])
        second_urn.refresh_from_db()
        protocol.refresh_from_db()
        self.assertEqual(second_urn.contact_id, first.id)
        self.assertEqual(protocol.contact_id, first.id)
        second.refresh_from_db()
        self.assertEqual(second.status, Contact.STATUS_ARCHIVED)
        self.assertEqual(ContactAnchor.objects.filter(org=self.org, value="store-user-42").count(), 1)

        again = self._post(
            "internal_identity_attach",
            {
                "project_id": str(self.org.proj_uuid),
                "urn_id": first_urn.id,
                "anchor": {"type": "commerce_user_id", "value": "store-user-42", "verified": True},
            },
        )
        self.assertEqual(again.json()["outcome"], "noop")
        self.assertEqual(
            ContactIdentityEvent.objects.filter(urn=first_urn, outcome=ContactIdentityEvent.OUTCOME_NOOP).count(),
            1,
        )

    def test_claimed_attach_does_not_merge(self):
        first = self.create_contact("Ann", urns=["tel:+250788111012"])
        second = self.create_contact("Bob", urns=["tel:+250788111013"])
        ContactAnchor.objects.create(
            org=self.org,
            contact=first,
            anchor_type=ContactAnchor.ANCHOR_COMMERCE_USER_ID,
            value="store-user-7",
            verified=True,
        )
        response = self._post(
            "internal_identity_attach",
            {
                "project_id": str(self.org.proj_uuid),
                "urn_id": second.urns.get().id,
                "anchor": {"type": "commerce_user_id", "value": "store-user-7", "verified": False},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["attachment_status"], "claimed")
        self.assertEqual(response.json()["consumer_id"], str(second.uuid))
        second.urns.get().refresh_from_db()
        self.assertEqual(second.urns.get().contact_id, second.id)

    def test_distinct_verified_anchors_conflict(self):
        first = self.create_contact("Ann", urns=["tel:+250788111014"])
        second = self.create_contact("Bob", urns=["tel:+250788111015"])
        ContactAnchor.objects.create(
            org=self.org,
            contact=first,
            anchor_type=ContactAnchor.ANCHOR_COMMERCE_USER_ID,
            value="buyer-1",
            verified=True,
        )
        ContactAnchor.objects.create(
            org=self.org,
            contact=second,
            anchor_type=ContactAnchor.ANCHOR_COMMERCE_USER_ID,
            value="buyer-2",
            verified=True,
        )
        response = self._post(
            "internal_identity_attach",
            {
                "project_id": str(self.org.proj_uuid),
                "urn_id": second.urns.get().id,
                "anchor": {"type": "commerce_user_id", "value": "buyer-1", "verified": True},
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "conflicting_consumer")
        second.urns.get().refresh_from_db()
        self.assertEqual(second.urns.get().contact_id, second.id)
        self.assertTrue(
            ContactIdentityEvent.objects.filter(
                outcome=ContactIdentityEvent.OUTCOME_CONFLICT, urn=second.urns.get()
            ).exists()
        )

    def test_empty_anchor_does_not_write(self):
        contact = self.create_contact("Ann", urns=["tel:+250788111016"])
        response = self._post(
            "internal_identity_attach",
            {
                "project_id": str(self.org.proj_uuid),
                "urn_id": contact.urns.get().id,
                "anchor": {"type": "verified_email", "value": "  ", "verified": True},
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "validation")
        self.assertEqual(ContactIdentityEvent.objects.count(), 0)
        self.assertEqual(ContactAnchor.objects.count(), 0)

    def test_email_is_normalized_and_isolated_by_project(self):
        contact = self.create_contact("Ann", urns=["tel:+250788111017"])
        other = self.create_contact("Bob", urns=["tel:+250788111018"], org=self.org2)
        response = self._post(
            "internal_identity_attach",
            {
                "project_id": str(self.org.proj_uuid),
                "urn_id": contact.urns.get().id,
                "anchor": {"type": "verified_email", "value": "Person@Example.com", "verified": True},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactAnchor.objects.get(contact=contact).value, "person@example.com")
        other_response = self._post(
            "internal_identity_attach",
            {
                "project_id": str(self.org2.proj_uuid),
                "urn_id": other.urns.get().id,
                "anchor": {"type": "verified_email", "value": "Person@Example.com", "verified": True},
            },
        )
        self.assertEqual(other_response.status_code, 200)
        self.assertEqual(other_response.json()["consumer_id"], str(other.uuid))

    def test_unknown_project_is_forbidden(self):
        contact = self.create_contact("Ann", urns=["tel:+250788111019"])
        response = self._post(
            "internal_identity_attach",
            {
                "project_id": str(uuid4()),
                "urn_id": contact.urns.get().id,
                "anchor": {"type": "commerce_user_id", "value": "x", "verified": True},
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ContactIdentityEvent.objects.count(), 0)

    def test_detach_requires_a_code_then_moves_protocols(self):
        source = self.create_contact("Ann", urns=["tel:+250788111020"])
        target = self.create_contact("Bob", urns=["tel:+250788111021"])
        urn = source.urns.get()
        ContactAnchor.objects.create(
            org=self.org,
            contact=source,
            anchor_type=ContactAnchor.ANCHOR_VERIFIED_EMAIL,
            value="ann@example.com",
            verified=True,
        )
        ContactAnchor.objects.create(
            org=self.org,
            contact=target,
            anchor_type=ContactAnchor.ANCHOR_COMMERCE_USER_ID,
            value="bob-shop",
            verified=True,
        )
        urn.attachment_status = ContactURN.ATTACHMENT_CONFIRMED
        urn.save(update_fields=["attachment_status"])
        protocol = Protocol.objects.create(org=self.org, contact=source, urn=urn)

        refused = self._post(
            "internal_identity_detach",
            {"project_id": str(self.org.proj_uuid), "urn_id": urn.id, "target_consumer_id": str(target.uuid)},
        )
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["error"], "confirmation_required")
        urn.refresh_from_db()
        self.assertEqual(urn.contact_id, source.id)

        issued = self._post(
            "internal_identity_confirmation",
            {"project_id": str(self.org.proj_uuid), "urn_id": urn.id},
        )
        self.assertEqual(issued.status_code, 201)
        moved = self._post(
            "internal_identity_detach",
            {
                "project_id": str(self.org.proj_uuid),
                "urn_id": urn.id,
                "target_consumer_id": str(target.uuid),
                "confirmation_code": issued.json()["confirmation_code"],
            },
        )
        self.assertEqual(moved.status_code, 200)
        urn.refresh_from_db()
        protocol.refresh_from_db()
        self.assertEqual(urn.contact_id, target.id)
        self.assertEqual(protocol.contact_id, target.id)
        self.assertEqual(urn.attachment_status, ContactURN.ATTACHMENT_CONFIRMED)

    def test_detach_without_target_returns_the_urn_to_not_attached(self):
        source = self.create_contact("Ann", urns=["tel:+250788111022"])
        urn = source.urns.get()
        ContactAnchor.objects.create(
            org=self.org,
            contact=source,
            anchor_type=ContactAnchor.ANCHOR_TAX_DOCUMENT,
            value="12345678901",
            verified=True,
        )
        urn.attachment_status = ContactURN.ATTACHMENT_CONFIRMED
        urn.save(update_fields=["attachment_status"])
        protocol = Protocol.objects.create(org=self.org, contact=source, urn=urn)
        response = self._post(
            "internal_identity_detach",
            {"project_id": str(self.org.proj_uuid), "urn_id": urn.id, "privileged": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["attachment_status"], "not-attached")
        urn.refresh_from_db()
        protocol.refresh_from_db()
        self.assertNotEqual(urn.contact_id, source.id)
        self.assertEqual(protocol.contact_id, urn.contact_id)
        source.refresh_from_db()
        self.assertEqual(source.status, Contact.STATUS_ACTIVE)

    def test_detach_to_a_colliding_anchor_is_refused(self):
        source = self.create_contact("Ann", urns=["tel:+250788111023"])
        target = self.create_contact("Bob", urns=["tel:+250788111024"])
        ContactAnchor.objects.create(
            org=self.org,
            contact=source,
            anchor_type=ContactAnchor.ANCHOR_COMMERCE_USER_ID,
            value="buyer-1",
            verified=True,
        )
        ContactAnchor.objects.create(
            org=self.org,
            contact=target,
            anchor_type=ContactAnchor.ANCHOR_COMMERCE_USER_ID,
            value="buyer-2",
            verified=True,
        )
        urn = source.urns.get()
        response = self._post(
            "internal_identity_detach",
            {
                "project_id": str(self.org.proj_uuid),
                "urn_id": urn.id,
                "target_consumer_id": str(target.uuid),
                "privileged": True,
            },
        )
        self.assertEqual(response.status_code, 409)
        urn.refresh_from_db()
        self.assertEqual(urn.contact_id, source.id)

    def test_inactivity_rejects_out_of_range_and_keeps_the_previous_value(self):
        saved = self._post(
            "internal_identity_inactivity",
            {"project_id": str(self.org.proj_uuid), "ai_inactivity_hours": 4, "human_inactivity_hours": 96},
        )
        self.assertEqual(saved.status_code, 200)
        rejected = self._post(
            "internal_identity_inactivity",
            {"project_id": str(self.org.proj_uuid), "ai_inactivity_hours": 48},
        )
        self.assertEqual(rejected.status_code, 400)
        self.org.refresh_from_db()
        self.assertEqual(self.org.config["ai_inactivity_hours"], 4)

    def test_graph_and_forget(self):
        contact = self.create_contact("Ann", urns=["tel:+250788111025"])
        contact.fields = {"note": "secret"}
        contact.save(update_fields=["fields"])
        ContactAnchor.objects.create(
            org=self.org,
            contact=contact,
            anchor_type=ContactAnchor.ANCHOR_COMMERCE_USER_ID,
            value="ann",
            verified=True,
        )
        graph = self.client.get(
            f"{reverse('internal_identity_graph')}?project_id={self.org.proj_uuid}&urn_id={contact.urns.get().id}"
        )
        self.assertEqual(graph.status_code, 200)
        self.assertEqual(graph.json()["anchors"][0]["value"], "ann")
        forgotten = self._post(
            "internal_identity_forget",
            {"project_id": str(self.org.proj_uuid), "consumer_id": str(contact.uuid)},
        )
        self.assertEqual(forgotten.status_code, 200)
        contact.refresh_from_db()
        self.assertEqual(contact.fields, {})
        self.assertTrue(
            ContactIdentityEvent.objects.filter(
                outcome=ContactIdentityEvent.OUTCOME_DELETED, consumer=contact
            ).exists()
        )
