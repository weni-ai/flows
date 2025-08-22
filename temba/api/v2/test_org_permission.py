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
        self.assertFalse(self.permission.has_permission(request, view=object()))

    def test_denies_when_org_not_found(self):
        random_proj = uuid.uuid4()
        request = SimpleNamespace(query_params={"project": str(random_proj)}, data={}, user=self.user)
        self.assertFalse(self.permission.has_permission(request, view=object()))

    def test_denies_when_user_not_in_org(self):
        request = SimpleNamespace(
            query_params={"project_uuid": str(self.org.proj_uuid)}, data={}, user=self.non_org_user
        )
        self.assertFalse(self.permission.has_permission(request, view=object()))

    def test_allows_when_user_in_org_with_query_param_project(self):
        request = SimpleNamespace(query_params={"project": str(self.org.proj_uuid)}, data={}, user=self.user)
        self.assertTrue(self.permission.has_permission(request, view=object()))

    def test_allows_when_user_in_org_with_body_project_uuid(self):
        request = SimpleNamespace(query_params={}, data={"project_uuid": str(self.org.proj_uuid)}, user=self.user)
        self.assertTrue(self.permission.has_permission(request, view=object()))

    def test_denies_when_user_email_not_found(self):
        # simulate a request with an email that doesn't exist in the auth user table
        ghost_user = SimpleNamespace(email="ghost.user.notfound@example.com")
        request = SimpleNamespace(query_params={"project": str(self.org.proj_uuid)}, data={}, user=ghost_user)
        self.assertFalse(self.permission.has_permission(request, view=object()))
