import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from temba.api.v2.weni_authz_patches import (
    _org_for_privileged_action,
    _patched_is_suspended,
    _patched_suspend_flag,
    _patched_ticketer_queues_get,
)
from temba.tests.base import TembaTest
from temba.tickets.models import Ticketer


class WeniAuthzPatchTests(TembaTest):
    def test_outsider_cannot_suspend_foreign_org(self):
        view = SimpleNamespace()
        request = SimpleNamespace(user=self.non_org_user)
        with self.assertRaises(PermissionDenied):
            _org_for_privileged_action(view, request, uuid=self.org.uuid)

    def test_unauthenticated_user_is_denied(self):
        view = SimpleNamespace()
        request = SimpleNamespace(user=None)
        with self.assertRaises(PermissionDenied):
            _org_for_privileged_action(view, request, uuid=self.org.uuid)

    def test_member_can_resolve_own_org(self):
        view = SimpleNamespace()
        request = SimpleNamespace(user=self.admin)
        org = _org_for_privileged_action(view, request, uuid=self.org.uuid)
        self.assertEqual(org.id, self.org.id)

    def test_trusted_internal_can_resolve_foreign_org(self):
        view = SimpleNamespace()
        request = SimpleNamespace(user=self.non_org_user)
        with patch("temba.api.v2.weni_authz_patches.CanCommunicateInternally.has_permission", return_value=True):
            org = _org_for_privileged_action(view, request, uuid=self.org.uuid)
        self.assertEqual(org.id, self.org.id)

    def test_member_can_suspend_org(self):
        view = SimpleNamespace()
        request = SimpleNamespace(user=self.admin, data={"is_suspended": True})
        response = _patched_is_suspended(view, request, uuid=self.org.uuid)
        self.assertEqual(response.status_code, 200)
        self.org.refresh_from_db()
        self.assertTrue(self.org.is_suspended)

    def test_member_can_clear_and_set_suspend_flags(self):
        view = SimpleNamespace()
        self.org.config["date_billing_expired"] = "2026-01-01"
        self.org.config["date_org_will_suspend"] = "2026-02-01"
        self.org.save(update_fields=("config",))

        delete_request = SimpleNamespace(user=self.admin, method="DELETE", data={})
        delete_resp = _patched_suspend_flag(view, delete_request, uuid=self.org.uuid)
        self.assertEqual(delete_resp.status_code, 200)
        self.org.refresh_from_db()
        self.assertNotIn("date_billing_expired", self.org.config)
        self.assertNotIn("date_org_will_suspend", self.org.config)

        serializer = MagicMock()
        serializer.is_valid.return_value = True
        serializer.data = {"date_org_will_suspend": "2026-03-01"}
        patch_request = SimpleNamespace(user=self.admin, method="PATCH", data={})
        with patch("weni.orgs_api.serializers.FlagOrgSerializer", return_value=serializer):
            patch_resp = _patched_suspend_flag(view, patch_request, uuid=self.org.uuid)
        self.assertEqual(patch_resp.status_code, 200)
        self.assertEqual(json.loads(patch_resp.content), {"date_org_will_suspend": "2026-03-01"})

    def test_ticketer_queues_requires_uuid(self):
        request = Request(APIRequestFactory().get("/api/v2/ticketer_queues"))
        request.user = self.admin
        with self.assertRaises(ValidationError):
            _patched_ticketer_queues_get(SimpleNamespace(), request)

    def test_ticketer_queues_unknown_ticketer_returns_empty(self):
        request = Request(
            APIRequestFactory().get("/api/v2/ticketer_queues?ticketer_uuid=dddddddd-dddd-4ddd-8ddd-dddddddddddd")
        )
        request.user = self.admin
        with patch.object(Ticketer.objects, "get", side_effect=Ticketer.DoesNotExist):
            response = _patched_ticketer_queues_get(SimpleNamespace(), request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_ticketer_queues_denies_non_member(self):
        ticketer = MagicMock()
        ticketer.org.has_user.return_value = False
        raw = APIRequestFactory().get("/api/v2/ticketer_queues?ticketer_uuid=dddddddd-dddd-4ddd-8ddd-dddddddddddd")
        request = Request(raw)
        request.user = self.non_org_user
        view = SimpleNamespace()
        with patch.object(Ticketer.objects, "get", return_value=ticketer):
            with self.assertRaises(PermissionDenied):
                _patched_ticketer_queues_get(view, request)

    def test_ticketer_queues_allows_trusted_internal(self):
        ticketer = MagicMock()
        ticketer.org.has_user.return_value = False
        request = Request(
            APIRequestFactory().get("/api/v2/ticketer_queues?ticketer_uuid=dddddddd-dddd-4ddd-8ddd-dddddddddddd")
        )
        request.user = self.non_org_user
        with patch(
            "temba.api.v2.weni_authz_patches.CanCommunicateInternally.has_permission",
            return_value=True,
        ), patch.object(Ticketer.objects, "get", return_value=ticketer), patch(
            "temba.api.v2.weni_authz_patches.TicketerQueue"
        ) as TQ, patch(
            "temba.api.v2.weni_authz_patches.TicketerQueueSerializer"
        ) as Ser:
            TQ.objects.filter.return_value = []
            Ser.return_value.data = []
            response = _patched_ticketer_queues_get(SimpleNamespace(), request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_ticketer_queues_allows_member(self):
        ticketer = MagicMock()
        ticketer.org.has_user.return_value = True
        request = Request(
            APIRequestFactory().get("/api/v2/ticketer_queues?ticketer_uuid=dddddddd-dddd-4ddd-8ddd-dddddddddddd")
        )
        request.user = self.admin
        with patch.object(Ticketer.objects, "get", return_value=ticketer), patch(
            "temba.api.v2.weni_authz_patches.TicketerQueue"
        ) as TQ, patch("temba.api.v2.weni_authz_patches.TicketerQueueSerializer") as Ser:
            TQ.objects.filter.return_value = []
            Ser.return_value.data = []
            response = _patched_ticketer_queues_get(SimpleNamespace(), request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])
