import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError

from temba.api.v2.internals.broadcasts.context import (
    ProjectMismatch,
    _get_or_create_user,
    resolve_org_and_user_internal_whatsapp,
)
from temba.tests.base import TembaTest


class ResolveOrgAndUserInternalWhatsappTests(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = self.org.proj_uuid or uuid.uuid4()
        self.org.save(update_fields=("proj_uuid",))

    def _request(self, *, user=None, jwt_payload=None, org=None, project_uuid=None):
        return SimpleNamespace(
            user=user,
            jwt_payload=jwt_payload,
            org=org,
            project_uuid=project_uuid,
        )

    def test_body_email_is_ignored_for_untrusted_caller(self):
        request = self._request(user=self.admin, org=self.org)
        org, user = resolve_org_and_user_internal_whatsapp(
            drf_request=request,
            data={"project": str(self.org.proj_uuid), "user_email": "admin-of-a@example.com"},
        )
        self.assertEqual(org.id, self.org.id)
        self.assertEqual(user.email, self.admin.email)

    def test_query_and_body_project_mismatch_raises(self):
        request = self._request(user=self.admin, org=self.org)
        with self.assertRaises(ProjectMismatch):
            resolve_org_and_user_internal_whatsapp(
                drf_request=request,
                data={"project": str(uuid.uuid4())},
            )

    def test_jwt_project_mismatch_raises(self):
        request = self._request(
            user=self.admin,
            jwt_payload={"project_uuid": str(uuid.uuid4()), "email": self.admin.email},
        )
        with self.assertRaises(ProjectMismatch):
            resolve_org_and_user_internal_whatsapp(
                drf_request=request,
                data={"project": str(self.org.proj_uuid)},
            )

    def test_trusted_internal_may_act_on_behalf_of_body_email(self):
        request = self._request(user=self.admin, org=self.org)
        with patch(
            "temba.api.v2.internals.broadcasts.context.CanCommunicateInternally.has_permission",
            return_value=True,
        ):
            org, user = resolve_org_and_user_internal_whatsapp(
                drf_request=request,
                data={"project": str(self.org.proj_uuid), "user_email": "on-behalf@example.com"},
            )
        self.assertEqual(org.id, self.org.id)
        self.assertEqual(user.email, "on-behalf@example.com")

    def test_attached_org_and_jwt_project_mismatch_raises(self):
        request = self._request(
            user=self.admin,
            org=self.org,
            jwt_payload={"project_uuid": str(uuid.uuid4())},
        )
        with self.assertRaises(ProjectMismatch):
            resolve_org_and_user_internal_whatsapp(drf_request=request, data={})

    def test_jwt_project_not_found_raises(self):
        request = self._request(
            user=self.admin,
            jwt_payload={"project_uuid": str(uuid.uuid4()), "email": self.admin.email},
        )
        with self.assertRaises(ValueError) as ctx:
            resolve_org_and_user_internal_whatsapp(drf_request=request, data={})
        self.assertEqual(str(ctx.exception), "Project not found")

    def test_module_jwt_without_project_claim_does_not_use_body(self):
        request = self._request(user=self.admin, jwt_payload={"email": self.admin.email})
        with self.assertRaises(ValueError) as ctx:
            resolve_org_and_user_internal_whatsapp(
                drf_request=request,
                data={"project": str(self.org.proj_uuid)},
            )
        self.assertEqual(str(ctx.exception), "Project not provided")

    def test_get_or_create_user_recovers_from_integrity_error(self):
        with patch(
            "temba.api.v2.internals.broadcasts.context.User.objects.get_or_create",
            side_effect=IntegrityError("duplicate"),
        ), patch(
            "temba.api.v2.internals.broadcasts.context.User.objects.get",
            return_value=self.admin,
        ), patch(
            "temba.api.v2.internals.broadcasts.context.logger"
        ) as mock_logger:
            user = _get_or_create_user(self.admin.email)
        self.assertEqual(user.email, self.admin.email)
        mock_logger.debug.assert_called_once()
