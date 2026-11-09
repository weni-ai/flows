from unittest.mock import patch

import requests

from django.test import override_settings

from temba import mailroom
from temba.api.weni_jwt_test_utils import WeniJWTTestMixin
from temba.contacts.models import Contact, ContactField
from temba.contacts.usecases.opt_in import ensure_audience
from temba.mailroom.client import MailroomException
from temba.orgs.models import Org
from temba.tests import TembaTest
from temba.tests.mailroom import Mocks, TestClient
from temba.utils.uuid import uuid4


@override_settings(INTERNAL_USER_EMAIL="super@user.com")
class OptInInternalsTest(WeniJWTTestMixin, TembaTest):
    def setUp(self):
        super().setUp()
        if not self.org.proj_uuid:
            self.org.proj_uuid = self.project.project_uuid
            self.org.save(update_fields=["proj_uuid"])
        self.mailroom = patch("temba.mailroom.get_client", return_value=TestClient(Mocks()))
        self.queue = patch("temba.mailroom.queue._queue_batch_task")
        self.mailroom.start()
        self.queue.start()

    def tearDown(self):
        self.queue.stop()
        self.mailroom.stop()
        super().tearDown()

    def _headers(self, **claims):
        claims.setdefault("project_uuid", str(self.project.project_uuid))
        claims.setdefault("can_communicate_internally", True)
        return self.jwt_headers(**claims)

    def _post(self, path, data=None, **claims):
        return self.client.post(path, data=data or {}, content_type="application/json", **self._headers(**claims))

    def _get(self, path, **claims):
        return self.client.get(path, **self._headers(**claims))

    def _patch(self, path, data, **claims):
        return self.client.patch(path, data=data, content_type="application/json", **self._headers(**claims))

    def test_audience_auth_and_idempotent(self):
        self.assertEqual(self.client.post("/api/v2/internals/opt_in/audience").status_code, 401)
        self.assertEqual(
            self._post("/api/v2/internals/opt_in/audience", can_communicate_internally=False).status_code, 403
        )
        missing = self._post("/api/v2/internals/opt_in/audience", project_uuid=str(uuid4()))
        self.assertEqual(missing.status_code, 404)

        first = self._post("/api/v2/internals/opt_in/audience", {"project_uuid": str(uuid4())})
        self.assertEqual(first.status_code, 201)
        second = self._post("/api/v2/internals/opt_in/audience")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["group_uuid"], second.json()["group_uuid"])
        self.assertEqual(second.json()["count"], 0)
        self.assertEqual(second.json()["name"], "Opt-in")

        listed = self._get("/api/v2/internals/opt_in/audience")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["group_uuid"], first.json()["group_uuid"])

    def test_audience_adopts_static_name_and_repoints_inactive_group(self):
        existing = self.create_group("Opt-in")
        adopted = self._post("/api/v2/internals/opt_in/audience")
        self.assertEqual(adopted.status_code, 201)
        self.assertEqual(adopted.json()["group_uuid"], str(existing.uuid))

        existing.release(self.user)
        repointed = self._post("/api/v2/internals/opt_in/audience")
        self.assertEqual(repointed.status_code, 201)
        self.assertNotEqual(repointed.json()["group_uuid"], str(existing.uuid))
        self.assertEqual(repointed.json()["name"], "Opt-in")

    def test_audience_conflicts(self):
        self.create_group("Opt-in", query='name != ""')
        taken = self._post("/api/v2/internals/opt_in/audience")
        self.assertEqual(taken.status_code, 409)
        self.assertEqual(taken.json()["error"], "opt_in_name_taken")

    def test_audience_group_limit(self):
        from temba.contacts.models import ContactGroup

        limits = dict(self.org.limits or {})
        limits[Org.LIMIT_GROUPS] = ContactGroup.user_groups.filter(org=self.org).count()
        self.org.limits = limits
        self.org.save(update_fields=["limits"])
        response = self._post("/api/v2/internals/opt_in/audience")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "group_limit_reached")

    def test_create_contract(self):
        self._post("/api/v2/internals/opt_in/audience")
        with self.assertLogs("temba.api.v2.internals.opt_in.views", level="INFO") as logs:
            created = self._post(
                "/api/v2/internals/opt_in/contacts",
                {"name": "Maria", "whatsapp": "5561912345678", "email": "maria@example.com"},
            )
        self.assertEqual(created.status_code, 201)
        body = created.json()
        self.assertEqual(body["outcome"], "created")
        self.assertTrue(body["contact_uuid"])
        joined = "\n".join(logs.output)
        self.assertNotIn("5561912345678", joined)
        self.assertNotIn("maria@example.com", joined)
        self.assertNotIn("Maria", joined)

        duplicate = self._post(
            "/api/v2/internals/opt_in/contacts",
            {"name": "Other", "whatsapp": "5561912345678", "email": "other@example.com"},
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json(), {"outcome": "duplicate_number"})

        invalid = self._post("/api/v2/internals/opt_in/contacts", {"name": " ", "whatsapp": "12", "email": "nope"})
        self.assertEqual(invalid.status_code, 400)

        counted = self._get("/api/v2/internals/opt_in/audience")
        self.assertEqual(counted.json()["count"], 1)

    def test_create_before_audience(self):
        response = self._post("/api/v2/internals/opt_in/contacts", {"name": "Maria", "whatsapp": "5561912345678"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "opt_in_audience_missing")

    def test_create_when_group_inactive(self):
        created = ensure_audience(self.org, self.user)
        created.group.release(self.user)
        response = self._post("/api/v2/internals/opt_in/contacts", {"name": "Maria", "whatsapp": "5561912345678"})
        self.assertEqual(response.status_code, 409)

    def test_mailroom_failure_is_503(self):
        self._post("/api/v2/internals/opt_in/audience")
        client = mailroom.get_client()
        with patch.object(client, "contact_create", side_effect=requests.Timeout()):
            response = self._post("/api/v2/internals/opt_in/contacts", {"name": "Maria", "whatsapp": "5561922222222"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("duplicate_number", response.content.decode())

        error = MailroomException("contact/create", None, {"error": "database down"})
        with patch.object(client, "contact_create", side_effect=error):
            response = self._post("/api/v2/internals/opt_in/contacts", {"name": "Maria", "whatsapp": "5561933333333"})
        self.assertEqual(response.status_code, 503)

    def test_fill_identifier(self):
        self._post("/api/v2/internals/opt_in/audience")
        created = self._post("/api/v2/internals/opt_in/contacts", {"name": "Maria", "whatsapp": "5561944444444"})
        contact_uuid = created.json()["contact_uuid"]
        path = f"/api/v2/internals/opt_in/contacts/{contact_uuid}"
        updated = self._patch(path, {"email": "maria@example.com"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["outcome"], "updated")
        again = self._patch(path, {"email": "other@example.com"})
        self.assertEqual(again.json()["outcome"], "unchanged")
        contact = Contact.objects.get(uuid=contact_uuid)
        email = ContactField.user_fields.get(org=self.org, key="email")
        self.assertEqual(contact.get_field_value(email), "maria@example.com")

        outsider = self.create_contact("Out", urns=["whatsapp:5561955555555"])
        skipped = self._patch(f"/api/v2/internals/opt_in/contacts/{outsider.uuid}", {"email": "out@example.com"})
        self.assertEqual(skipped.json()["outcome"], "unchanged")

        self.org2.proj_uuid = uuid4()
        self.org2.save(update_fields=["proj_uuid"])
        missing = self._patch(path, {"email": "x@example.com"}, project_uuid=str(self.org2.proj_uuid))
        self.assertEqual(missing.status_code, 404)

        bad = self._patch(path, {"email": "not-an-email"})
        self.assertEqual(bad.status_code, 400)

        with patch.object(mailroom.get_client(), "contact_modify", side_effect=requests.Timeout()):
            fresh = self._post("/api/v2/internals/opt_in/contacts", {"name": "Ana", "whatsapp": "5561966666666"})
            failed = self._patch(
                f"/api/v2/internals/opt_in/contacts/{fresh.json()['contact_uuid']}",
                {"email": "ana@example.com"},
            )
        self.assertEqual(failed.status_code, 503)
