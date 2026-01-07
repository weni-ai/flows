import uuid

import pytz
from weni.internal.models import Project

from django.conf import settings
from django.contrib.auth import get_user_model

from temba.projects.usecases.project_delete import delete_project
from temba.tests.base import TembaTest

User = get_user_model()


class TestDeleteProject(TembaTest):
    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(
            project_uuid=str(uuid.uuid4()),
            name="Test Project",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
            config={"description": "Test description"},
            language="en-us",
        )

    def test_delete_project_successfully(self):
        """Test successfully deleting a project"""
        self.assertTrue(self.project.is_active)
        self.assertIsNone(self.project.released_on)

        deleted_project = delete_project(
            project_uuid=self.project.project_uuid,
            user_email=self.user.email,
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)

        self.assertIsNotNone(deleted_project)
        self.assertEqual(deleted_project, reloaded_project)
        self.assertFalse(reloaded_project.is_active)
        self.assertIsNotNone(reloaded_project.released_on)

    def test_delete_project_with_new_user(self):
        """Test deleting a project with a new user email"""
        new_user_email = "deleter@example.com"

        deleted_project = delete_project(
            project_uuid=self.project.project_uuid,
            user_email=new_user_email,
        )

        # Verify user was created
        new_user = User.objects.get(email=new_user_email)
        self.assertEqual(new_user.username, new_user_email)

        # Verify project was deleted
        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertFalse(reloaded_project.is_active)
        self.assertIsNotNone(reloaded_project.released_on)
        self.assertIsNotNone(deleted_project)

    def test_delete_nonexistent_project_returns_none(self):
        """Test that deleting a non-existent project returns None"""
        fake_uuid = str(uuid.uuid4())

        result = delete_project(
            project_uuid=fake_uuid,
            user_email=self.user.email,
        )

        self.assertIsNone(result)

    def test_delete_already_deleted_project(self):
        """Test deleting a project that was already deleted"""
        # First deletion
        delete_project(
            project_uuid=self.project.project_uuid,
            user_email=self.user.email,
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertFalse(reloaded_project.is_active)

        # Second deletion - should still work
        deleted_project = delete_project(
            project_uuid=self.project.project_uuid,
            user_email="another@example.com",
        )

        self.assertIsNotNone(deleted_project)
        self.assertFalse(deleted_project.is_active)

    def test_delete_project_removes_org_users(self):
        """Test that deleting a project removes org users"""
        # Add some users to the project
        viewer = self.create_user("viewer@example.com")
        editor = self.create_user("editor@example.com")
        
        self.project.viewers.add(viewer)
        self.project.editors.add(editor)

        self.assertEqual(self.project.viewers.count(), 1)
        self.assertEqual(self.project.editors.count(), 1)

        # Delete the project
        delete_project(
            project_uuid=self.project.project_uuid,
            user_email=self.user.email,
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        
        # Verify users were removed
        self.assertEqual(reloaded_project.viewers.count(), 0)
        self.assertEqual(reloaded_project.editors.count(), 0)
