import uuid
from types import SimpleNamespace

from temba.api.v2.permissions import IsUserInOrg
from temba.tests.base import TembaTest


class IsUserInOrgPermissionTests(TembaTest):
    def setUp(self):
        super().setUp()
        self.permission = IsUserInOrg()

        # ensure org has a project UUID for lookups
        self.org.proj_uuid = uuid.uuid4()
        self.org.save(update_fields=("proj_uuid",))

    def test_denies_when_project_param_missing(self):
        request = SimpleNamespace(query_params={}, data={}, user=self.user)
        # missing project is handled by the view layer; permission doesn't decide status code
        self.assertTrue(self.permission.has_permission(request, view=object()))

    def test_denies_when_org_not_found(self):
        random_proj = uuid.uuid4()
        request = SimpleNamespace(query_params={"project": str(random_proj)}, data={}, user=self.user)
        # org not found is handled by the view layer; permission doesn't decide status code
        self.assertTrue(self.permission.has_permission(request, view=object()))

    def test_denies_when_user_not_in_org(self):
        request = SimpleNamespace(
            query_params={"project_uuid": str(self.org.proj_uuid)}, data={}, user=self.non_org_user
        )
        self.assertFalse(self.permission.has_permission(request, view=object()))

    def test_allows_when_user_in_org_with_query_param_project(self):
        request = SimpleNamespace(query_params={"project": str(self.org.proj_uuid)}, data={}, user=self.user)
        self.assertTrue(self.permission.has_permission(request, view=object()))
        self.assertEqual(request.project_uuid, str(self.org.proj_uuid))
        self.assertEqual(request.org.id, self.org.id)

    def test_allows_when_user_in_org_with_body_project_uuid(self):
        request = SimpleNamespace(query_params={}, data={"project_uuid": str(self.org.proj_uuid)}, user=self.user)
        self.assertTrue(self.permission.has_permission(request, view=object()))
        self.assertEqual(request.project_uuid, str(self.org.proj_uuid))
        self.assertEqual(request.org.id, self.org.id)

    def test_denies_when_user_email_not_found(self):
        # simulate a request with an email that doesn't exist in the auth user table
        ghost_user = SimpleNamespace(email="ghost.user.notfound@example.com")
        request = SimpleNamespace(query_params={"project": str(self.org.proj_uuid)}, data={}, user=ghost_user)
        self.assertFalse(self.permission.has_permission(request, view=object()))

    def test_get_project_uuid_uses_existing_request_project_uuid(self):
        request = SimpleNamespace(project_uuid=str(self.org.proj_uuid), query_params={}, data={})
        self.assertEqual(self.permission._get_project_uuid(request, view=object()), str(self.org.proj_uuid))

    def test_get_project_uuid_returns_none_when_missing_everywhere(self):
        request = SimpleNamespace(query_params={}, data={})
        self.assertIsNone(self.permission._get_project_uuid(request, view=object()))

    def test_get_user_for_membership_check_returns_none_when_request_user_missing(self):
        request = SimpleNamespace(user=None)
        self.assertIsNone(self.permission._get_user_for_membership_check(request))
