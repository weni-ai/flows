import uuid

import pytz
from weni.internal.models import Project

from django.conf import settings
from django.contrib.auth.models import Group

from temba.api.models import APIToken
from temba.projects.usecases.permission_update import (
    _release_user_api_tokens,
    create_user_permission,
    get_name_permisssions,
    get_or_create_user_by_email,
    update_permission,
)
from temba.tests.base import TembaTest


class PermissionUpdateTestCase(TembaTest):
    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(
            project_uuid=uuid.uuid4(),
            name="Test Project",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
        )

    def test_get_name_permissions_returns_correct_name(self):
        """Test that get_name_permisssions returns correct permission name for each role"""
        self.assertEqual(get_name_permisssions(1), "viewer")
        self.assertEqual(get_name_permisssions(2), "editor")
        self.assertEqual(get_name_permisssions(3), "administrator")
        self.assertEqual(get_name_permisssions(4), "administrator")
        self.assertEqual(get_name_permisssions(5), "agent")
        self.assertEqual(get_name_permisssions(6), "marketing")

    def test_create_user_permission_viewer(self):
        """Test creating a viewer permission"""
        user, _ = get_or_create_user_by_email("viewer@example.com")
        create_user_permission(1, self.project, user)
        self.assertTrue(self.project.viewers.filter(pk=user.pk).exists())

    def test_create_user_permission_editor(self):
        """Test creating an editor permission"""
        user, _ = get_or_create_user_by_email("editor@example.com")
        create_user_permission(2, self.project, user)
        self.assertTrue(self.project.editors.filter(pk=user.pk).exists())

    def test_create_user_permission_administrator(self):
        """Test creating an administrator permission for role 3 and 4"""
        user3, _ = get_or_create_user_by_email("admin3@example.com")
        user4, _ = get_or_create_user_by_email("admin4@example.com")
        create_user_permission(3, self.project, user3)
        create_user_permission(4, self.project, user4)
        self.assertTrue(self.project.administrators.filter(pk=user3.pk).exists())
        self.assertTrue(self.project.administrators.filter(pk=user4.pk).exists())

    def test_create_user_permission_agent(self):
        """Test creating an agent permission"""
        user, _ = get_or_create_user_by_email("agent@example.com")
        create_user_permission(5, self.project, user)
        self.assertTrue(self.project.agents.filter(pk=user.pk).exists())

    def test_create_user_permission_marketing(self):
        """Test creating a marketing permission"""
        user, _ = get_or_create_user_by_email("marketing@example.com")
        create_user_permission(6, self.project, user)
        self.assertTrue(self.project.marketing.filter(pk=user.pk).exists())

    def test_update_permission_create_action(self):
        """Test update_permission with create action"""
        project = update_permission(
            project_uuid=self.project.project_uuid,
            action="create",
            user_email="newuser@example.com",
            role=6,
        )
        user = get_or_create_user_by_email("newuser@example.com")[0]
        self.assertTrue(project.marketing.filter(pk=user.pk).exists())

    def test_update_permission_delete_action(self):
        """Test update_permission with delete action"""
        user, _ = get_or_create_user_by_email("deleteuser@example.com")
        self.project.marketing.add(user)
        self.project.save()

        update_permission(
            project_uuid=self.project.project_uuid,
            action="delete",
            user_email="deleteuser@example.com",
            role=6,
        )
        self.assertFalse(self.project.marketing.filter(pk=user.pk).exists())

    def test_update_permission_update_action(self):
        """Test update_permission with update action changes role"""
        user, _ = get_or_create_user_by_email("updateuser@example.com")
        self.project.viewers.add(user)
        self.project.save()

        update_permission(
            project_uuid=self.project.project_uuid,
            action="update",
            user_email="updateuser@example.com",
            role=6,
        )
        self.project.refresh_from_db()
        self.assertFalse(self.project.viewers.filter(pk=user.pk).exists())
        self.assertTrue(self.project.marketing.filter(pk=user.pk).exists())

    def test_update_permission_delete_action_releases_user_api_tokens(self):
        """Delete action should deactivate the user's API tokens for that project's org"""
        user, _ = get_or_create_user_by_email("admin-with-token@example.com")
        self.project.administrators.add(user)
        self.project.save()

        token = APIToken.get_or_create(self.project, user, Group.objects.get(name="Administrators"))
        self.assertTrue(token.is_active)

        update_permission(
            project_uuid=self.project.project_uuid,
            action="delete",
            user_email="admin-with-token@example.com",
            role=3,
        )

        token.refresh_from_db()
        self.assertFalse(token.is_active)

    def test_update_permission_delete_action_keeps_other_users_tokens_active(self):
        """Delete must not affect tokens of other users in the same org"""
        deleted_user, _ = get_or_create_user_by_email("deleted-admin@example.com")
        kept_user, _ = get_or_create_user_by_email("kept-admin@example.com")
        self.project.administrators.add(deleted_user, kept_user)
        self.project.save()

        deleted_token = APIToken.get_or_create(self.project, deleted_user, Group.objects.get(name="Administrators"))
        kept_token = APIToken.get_or_create(self.project, kept_user, Group.objects.get(name="Administrators"))

        update_permission(
            project_uuid=self.project.project_uuid,
            action="delete",
            user_email="deleted-admin@example.com",
            role=3,
        )

        deleted_token.refresh_from_db()
        kept_token.refresh_from_db()
        self.assertFalse(deleted_token.is_active)
        self.assertTrue(kept_token.is_active)

    def test_update_permission_delete_action_keeps_tokens_for_other_orgs(self):
        """Delete should only release tokens scoped to the project being changed"""
        user, _ = get_or_create_user_by_email("multi-org-admin@example.com")

        self.project.administrators.add(user)
        self.project.save()
        self.org2.administrators.add(user)

        project_token = APIToken.get_or_create(self.project, user, Group.objects.get(name="Administrators"))
        other_org_token = APIToken.get_or_create(self.org2, user, Group.objects.get(name="Administrators"))

        update_permission(
            project_uuid=self.project.project_uuid,
            action="delete",
            user_email="multi-org-admin@example.com",
            role=3,
        )

        project_token.refresh_from_db()
        other_org_token.refresh_from_db()
        self.assertFalse(project_token.is_active)
        self.assertTrue(other_org_token.is_active)

    def test_update_permission_delete_action_when_user_has_no_token(self):
        """Delete should run cleanly when there is no API token to release"""
        user, _ = get_or_create_user_by_email("tokenless-admin@example.com")
        self.project.administrators.add(user)
        self.project.save()

        update_permission(
            project_uuid=self.project.project_uuid,
            action="delete",
            user_email="tokenless-admin@example.com",
            role=3,
        )

        self.assertFalse(self.project.administrators.filter(pk=user.pk).exists())
        self.assertFalse(APIToken.objects.filter(org=self.project, user=user).exists())

    def test_release_user_api_tokens_deactivates_all_active_tokens(self):
        """Deactivates every active token of the user in that org and returns the count"""
        user, _ = get_or_create_user_by_email("multi-token-user@example.com")
        self.project.administrators.add(user)
        self.project.save()

        APIToken.get_or_create(self.project, user, Group.objects.get(name="Administrators"))
        APIToken.get_or_create(self.project, user, Group.objects.get(name="Editors"))

        released = _release_user_api_tokens(self.project, user)

        self.assertEqual(released, 2)
        self.assertEqual(
            APIToken.objects.filter(org=self.project, user=user, is_active=True).count(),
            0,
        )

    def test_release_user_api_tokens_ignores_already_inactive_tokens(self):
        """Already deactivated tokens should not be touched again (idempotent)"""
        user, _ = get_or_create_user_by_email("inactive-token-user@example.com")
        self.project.administrators.add(user)
        self.project.save()

        token = APIToken.get_or_create(self.project, user, Group.objects.get(name="Administrators"))
        token.release()

        released = _release_user_api_tokens(self.project, user)

        self.assertEqual(released, 0)
