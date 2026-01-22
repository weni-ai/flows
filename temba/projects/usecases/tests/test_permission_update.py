import uuid

import pytz
from weni.internal.models import Project

from django.conf import settings

from temba.projects.usecases.permission_update import (
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
