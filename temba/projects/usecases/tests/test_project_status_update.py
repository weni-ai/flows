import uuid

import pytz

from django.conf import settings
from django.contrib.auth import get_user_model

from temba.orgs.models import Org
from temba.projects.usecases.project_status_update import update_project_status
from temba.tests.base import TembaTest

User = get_user_model()


class TestUpdateProjectStatus(TembaTest):
    def setUp(self):
        super().setUp()
        self.test_org = Org.objects.create(
            name="Test Org",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
            config={"description": "Test description"},
            language="en-us",
            is_active=True,
        )
        self.project_uuid = str(self.test_org.proj_uuid)

    def test_update_status_to_active(self):
        """Test updating project status to ACTIVE"""
        self.test_org.is_active = False
        self.test_org.save()

        updated_org = update_project_status(
            project_uuid=self.project_uuid,
            status="ACTIVE",
            user_email=self.user.email,
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertIsNotNone(updated_org)
        self.assertTrue(reloaded_org.is_active)
        self.assertEqual(updated_org, reloaded_org)
        self.assertEqual(reloaded_org.modified_by, self.user)

    def test_update_status_to_in_test(self):
        """Test updating project status to IN_TEST (should set is_active to True)"""
        self.test_org.is_active = False
        self.test_org.save()

        updated_org = update_project_status(
            project_uuid=self.project_uuid,
            status="IN_TEST",
            user_email=self.user.email,
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertIsNotNone(updated_org)
        self.assertTrue(reloaded_org.is_active)
        self.assertEqual(updated_org, reloaded_org)

    def test_update_status_to_inactive(self):
        """Test updating project status to INACTIVE (should set is_active to False)"""
        self.assertTrue(self.test_org.is_active)

        updated_org = update_project_status(
            project_uuid=self.project_uuid,
            status="INACTIVE",
            user_email=self.user.email,
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertIsNotNone(updated_org)
        self.assertFalse(reloaded_org.is_active)
        self.assertEqual(updated_org, reloaded_org)

    def test_update_status_with_new_user(self):
        """Test updating status with a new user email"""
        new_user_email = "statusupdater@example.com"

        updated_org = update_project_status(
            project_uuid=self.project_uuid,
            status="INACTIVE",
            user_email=new_user_email,
        )

        # Verify user was created
        new_user = User.objects.get(email=new_user_email)
        self.assertEqual(new_user.username, new_user_email)

        # Verify project was updated
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertFalse(reloaded_org.is_active)
        self.assertEqual(reloaded_org.modified_by, new_user)
        self.assertIsNotNone(updated_org)

    def test_update_status_same_value_does_not_modify(self):
        """Test that updating to the same status doesn't change modified_on"""
        self.assertTrue(self.test_org.is_active)
        original_modified_on = self.test_org.modified_on

        updated_org = update_project_status(
            project_uuid=self.project_uuid,
            status="ACTIVE",  # Already active
            user_email=self.user.email,
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertIsNotNone(updated_org)
        self.assertTrue(reloaded_org.is_active)
        # modified_on should not change
        self.assertEqual(reloaded_org.modified_on, original_modified_on)

    def test_update_status_invalid_status_raises_error(self):
        """Test that invalid status raises ValueError"""
        with self.assertRaises(ValueError) as context:
            update_project_status(
                project_uuid=self.project_uuid,
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
        self.assertTrue(self.test_org.is_active)

        # Change to INACTIVE
        update_project_status(
            project_uuid=self.project_uuid,
            status="INACTIVE",
            user_email=self.user.email,
        )
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertFalse(reloaded_org.is_active)

        # Change to IN_TEST
        update_project_status(
            project_uuid=self.project_uuid,
            status="IN_TEST",
            user_email=self.user.email,
        )
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertTrue(reloaded_org.is_active)

        # Change to ACTIVE
        update_project_status(
            project_uuid=self.project_uuid,
            status="ACTIVE",
            user_email=self.user.email,
        )
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertTrue(reloaded_org.is_active)

    def test_status_mapping_correctness(self):
        """Test that status mapping is correct for all valid statuses"""
        # Test ACTIVE -> True
        self.test_org.is_active = False
        self.test_org.save()
        
        update_project_status(self.project_uuid, "ACTIVE", self.user.email)
        self.test_org.refresh_from_db()
        self.assertTrue(self.test_org.is_active)

        # Test IN_TEST -> True
        self.test_org.is_active = False
        self.test_org.save()
        
        update_project_status(self.project_uuid, "IN_TEST", self.user.email)
        self.test_org.refresh_from_db()
        self.assertTrue(self.test_org.is_active)

        # Test INACTIVE -> False
        self.test_org.is_active = True
        self.test_org.save()
        
        update_project_status(self.project_uuid, "INACTIVE", self.user.email)
        self.test_org.refresh_from_db()
        self.assertFalse(self.test_org.is_active)
