from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from temba.api.v2.weni_authz_patches import _org_for_privileged_action, _patched_ticketer_queues_get
from temba.tests.base import TembaTest
from temba.tickets.models import Ticketer


class WeniAuthzPatchTests(TembaTest):
    def test_outsider_cannot_suspend_foreign_org(self):
        view = SimpleNamespace()
        request = SimpleNamespace(user=self.non_org_user)
        with self.assertRaises(PermissionDenied):
            _org_for_privileged_action(view, request, uuid=self.org.uuid)

    def test_member_can_resolve_own_org(self):
        view = SimpleNamespace()
        request = SimpleNamespace(user=self.admin)
        org = _org_for_privileged_action(view, request, uuid=self.org.uuid)
        self.assertEqual(org.id, self.org.id)

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
