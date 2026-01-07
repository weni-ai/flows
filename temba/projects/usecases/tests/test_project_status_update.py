import uuid

import pytz
from weni.internal.models import Project

from django.conf import settings
from django.contrib.auth import get_user_model

from temba.projects.usecases.project_status_update import update_project_status
from temba.tests.base import TembaTest

User = get_user_model()


class TestUpdateProjectStatus(TembaTest):
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
            is_active=True,
        )

    def test_update_status_to_active(self):
        """Test updating project status to ACTIVE"""
        self.project.is_active = False
        self.project.save()

        updated_project = update_project_status(
            project_uuid=self.project.project_uuid,
            status="ACTIVE",
            user_email=self.user.email,
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)

        self.assertIsNotNone(updated_project)
        self.assertTrue(reloaded_project.is_active)
        self.assertEqual(updated_project, reloaded_project)
        self.assertEqual(reloaded_project.modified_by, self.user)

    def test_update_status_to_in_test(self):
        """Test updating project status to IN_TEST (should set is_active to True)"""
        self.project.is_active = False
        self.project.save()

        updated_project = update_project_status(
            project_uuid=self.project.project_uuid,
            status="IN_TEST",
            user_email=self.user.email,
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)

        self.assertIsNotNone(updated_project)
        self.assertTrue(reloaded_project.is_active)
        self.assertEqual(updated_project, reloaded_project)

    def test_update_status_to_inactive(self):
        """Test updating project status to INACTIVE (should set is_active to False)"""
        self.assertTrue(self.project.is_active)

        updated_project = update_project_status(
            project_uuid=self.project.project_uuid,
            status="INACTIVE",
            user_email=self.user.email,
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)

        self.assertIsNotNone(updated_project)
        self.assertFalse(reloaded_project.is_active)
        self.assertEqual(updated_project, reloaded_project)

    def test_update_status_with_new_user(self):
        """Test updating status with a new user email"""
        new_user_email = "statusupdater@example.com"

        updated_project = update_project_status(
            project_uuid=self.project.project_uuid,
            status="INACTIVE",
            user_email=new_user_email,
        )

        # Verify user was created
        new_user = User.objects.get(email=new_user_email)
        self.assertEqual(new_user.username, new_user_email)

        # Verify project was updated
        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertFalse(reloaded_project.is_active)
        self.assertEqual(reloaded_project.modified_by, new_user)
        self.assertIsNotNone(updated_project)

    def test_update_status_same_value_does_not_modify(self):
        """Test that updating to the same status doesn't change modified_on"""
        self.assertTrue(self.project.is_active)
        original_modified_on = self.project.modified_on

        updated_project = update_project_status(
            project_uuid=self.project.project_uuid,
            status="ACTIVE",  # Already active
            user_email=self.user.email,
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)

        self.assertIsNotNone(updated_project)
        self.assertTrue(reloaded_project.is_active)
        # modified_on should not change
        self.assertEqual(reloaded_project.modified_on, original_modified_on)

    def test_update_status_invalid_status_raises_error(self):
        """Test that invalid status raises ValueError"""
        with self.assertRaises(ValueError) as context:
            update_project_status(
                project_uuid=self.project.project_uuid,
                status="INVALID_STATUS",
                user_email=self.user.email,
            )

        self.assertIn("Invalid status", str(context.exception))
        self.assertIn("INVALID_STATUS", str(context.exception))

    def test_update_status_nonexistent_project_returns_none(self):
        """Test that updating status of non-existent project returns None"""
        fake_uuid = str(uuid.uuid4())

        result = update_project_status(
            project_uuid=fake_uuid,
            status="ACTIVE",
            user_email=self.user.email,
        )

        self.assertIsNone(result)

    def test_update_status_transitions(self):
        """Test multiple status transitions"""
        # Start with ACTIVE
        self.assertTrue(self.project.is_active)

        # Change to INACTIVE
        update_project_status(
            project_uuid=self.project.project_uuid,
            status="INACTIVE",
            user_email=self.user.email,
        )
        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertFalse(reloaded_project.is_active)

        # Change to IN_TEST
        update_project_status(
            project_uuid=self.project.project_uuid,
            status="IN_TEST",
            user_email=self.user.email,
        )
        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertTrue(reloaded_project.is_active)

        # Change to ACTIVE
        update_project_status(
            project_uuid=self.project.project_uuid,
            status="ACTIVE",
            user_email=self.user.email,
        )
        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertTrue(reloaded_project.is_active)

    def test_status_mapping_correctness(self):
        """Test that status mapping is correct for all valid statuses"""
        # Test ACTIVE -> True
        self.project.is_active = False
        self.project.save()
        
        update_project_status(self.project.project_uuid, "ACTIVE", self.user.email)
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_active)

        # Test IN_TEST -> True
        self.project.is_active = False
        self.project.save()
        
        update_project_status(self.project.project_uuid, "IN_TEST", self.user.email)
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_active)

        # Test INACTIVE -> False
        self.project.is_active = True
        self.project.save()
        
        update_project_status(self.project.project_uuid, "INACTIVE", self.user.email)
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_active)
