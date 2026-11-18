import uuid
from unittest.mock import patch

import pytz

from django.conf import settings
from django.contrib.auth import get_user_model

from temba.orgs.models import Org
from temba.projects.usecases.project_delete import delete_project
from temba.tests.base import TembaTest

User = get_user_model()


class TestDeleteProject(TembaTest):
    def setUp(self):
        super().setUp()
        self.test_org = Org.objects.create(
            name="Test Org",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            proj_uuid=uuid.uuid4(),
            created_by=self.user,
            modified_by=self.user,
            config={"description": "Test description"},
            language="en-us",
        )
        self.project_uuid = str(self.test_org.proj_uuid)

    def test_delete_project_successfully(self):
        """Test successfully deleting a project"""
        self.assertTrue(self.test_org.is_active)
        self.assertIsNone(self.test_org.released_on)

        deleted_org = delete_project(
            project_uuid=self.project_uuid,
            user_email=self.user.email,
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertIsNotNone(deleted_org)
        self.assertEqual(deleted_org, reloaded_org)
        self.assertFalse(reloaded_org.is_active)
        self.assertIsNotNone(reloaded_org.released_on)

    def test_delete_project_with_new_user(self):
        """Test deleting a project with a new user email"""
        new_user_email = "deleter@example.com"

        deleted_org = delete_project(
            project_uuid=self.project_uuid,
            user_email=new_user_email,
        )

        # Verify user was created
        new_user = User.objects.get(email=new_user_email)
        self.assertEqual(new_user.username, new_user_email)

        # Verify project was deleted
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertFalse(reloaded_org.is_active)
        self.assertIsNotNone(reloaded_org.released_on)
        self.assertIsNotNone(deleted_org)

    def test_delete_nonexistent_project_returns_none(self):
        """Test that deleting a non-existent project returns None"""
        fake_uuid = str(uuid.uuid4())

        result = delete_project(
            project_uuid=fake_uuid,
            user_email=self.user.email,
        )

        self.assertIsNone(result)

    def test_delete_already_deleted_project(self):
        """A second deletion leaves the released org untouched and creates no user"""
        delete_project(
            project_uuid=self.project_uuid,
            user_email=self.user.email,
        )
        released = Org.objects.get(proj_uuid=self.project_uuid)
        users_before = User.objects.count()

        with self.assertLogs("temba.projects", level="INFO") as logs:
            deleted_org = delete_project(
                project_uuid=self.project_uuid,
                user_email="another@example.com",
            )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertEqual(deleted_org, reloaded_org)
        self.assertFalse(reloaded_org.is_active)
        self.assertEqual(reloaded_org.released_on, released.released_on)
        self.assertEqual(reloaded_org.modified_by, self.user)
        self.assertEqual(User.objects.count(), users_before)
        self.assertEqual(
            logs.output,
            [
                "INFO:temba.projects.usecases.project_delete:project_already_released "
                f"project_uuid={self.project_uuid} org_id={self.test_org.id}"
            ],
        )

    def test_failed_release_leaves_org_active(self):
        """A channel that fails to release rolls the whole release back"""
        channel = self.create_channel("A", "Failing", "+250785551212", org=self.test_org)

        with patch("temba.channels.models.Channel.release", side_effect=RuntimeError("provider down")):
            with self.assertRaises(RuntimeError):
                delete_project(project_uuid=self.project_uuid, user_email=self.user.email)

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertTrue(reloaded_org.is_active)
        self.assertIsNone(reloaded_org.released_on)
        channel.refresh_from_db()
        self.assertTrue(channel.is_active)

    def test_logs_have_no_email_nor_org_name(self):
        with self.assertLogs("temba.projects", level="INFO") as logs:
            delete_project(project_uuid=self.project_uuid, user_email=self.user.email)
            delete_project(project_uuid=self.project_uuid, user_email=self.user.email)

        output = "\n".join(logs.output)
        self.assertNotIn(self.user.email, output)
        self.assertNotIn(self.test_org.name, output)
        self.assertIn(f"project_released project_uuid={self.project_uuid} org_id={self.test_org.id}", logs.output[0])

    def test_delete_project_removes_org_users(self):
        """Test that deleting a project removes org users"""
        # Add some users to the org
        viewer = self.create_user("viewer@example.com")
        editor = self.create_user("editor@example.com")

        self.test_org.viewers.add(viewer)
        self.test_org.editors.add(editor)

        self.assertEqual(self.test_org.viewers.count(), 1)
        self.assertEqual(self.test_org.editors.count(), 1)

        # Delete the project
        delete_project(
            project_uuid=self.project_uuid,
            user_email=self.user.email,
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        # Verify users were removed
        self.assertEqual(reloaded_org.viewers.count(), 0)
        self.assertEqual(reloaded_org.editors.count(), 0)
