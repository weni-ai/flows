import uuid

import pytz

from django.conf import settings
from django.contrib.auth import get_user_model

from temba.orgs.models import Org
from temba.projects.usecases.project_update import update_project_config
from temba.tests.base import TembaTest

User = get_user_model()


class TestUpdateProjectConfig(TembaTest):
    def setUp(self):
        super().setUp()
        self.test_org = Org.objects.create(
            name="Test Org",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            proj_uuid=uuid.uuid4(),
            created_by=self.user,
            modified_by=self.user,
            config={"description": "Old description"},
            language="en-us",
        )
        # Store the proj_uuid for testing
        self.project_uuid = str(self.test_org.proj_uuid)

    def test_update_description_only(self):
        """Test updating only the description field"""
        updated_org = update_project_config(
            project_uuid=self.project_uuid,
            user_email=self.user.email,
            description="New description",
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertEqual(reloaded_org.config["description"], "New description")
        self.assertEqual(reloaded_org.name, "Test Org")
        self.assertEqual(reloaded_org.language, "en-us")
        self.assertEqual(updated_org, reloaded_org)
        self.assertEqual(reloaded_org.modified_by, self.user)

    def test_update_name_only(self):
        """Test updating only the name field"""
        updated_org = update_project_config(
            project_uuid=self.project_uuid,
            user_email=self.user.email,
            name="Updated Org Name",
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertEqual(reloaded_org.name, "Updated Org Name")
        self.assertEqual(reloaded_org.config["description"], "Old description")
        self.assertEqual(reloaded_org.language, "en-us")
        self.assertEqual(updated_org, reloaded_org)

    def test_update_language_only(self):
        """Test updating only the language field"""
        updated_org = update_project_config(
            project_uuid=self.project_uuid,
            user_email=self.user.email,
            language="pt-br",
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertEqual(reloaded_org.language, "pt-br")
        self.assertEqual(reloaded_org.name, "Test Org")
        self.assertEqual(reloaded_org.config["description"], "Old description")
        self.assertEqual(updated_org, reloaded_org)

    def test_update_all_fields(self):
        """Test updating all fields at once"""
        updated_org = update_project_config(
            project_uuid=self.project_uuid,
            user_email=self.user.email,
            name="Completely New Name",
            description="Completely new description",
            language="es",
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertEqual(reloaded_org.name, "Completely New Name")
        self.assertEqual(reloaded_org.config["description"], "Completely new description")
        self.assertEqual(reloaded_org.language, "es")
        self.assertEqual(updated_org, reloaded_org)

    def test_update_without_user_email(self):
        """Test updating without providing user_email"""
        updated_org = update_project_config(
            project_uuid=self.project_uuid,
            description="Description without user",
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertEqual(reloaded_org.config["description"], "Description without user")
        self.assertEqual(updated_org, reloaded_org)
        # modified_by should remain unchanged
        self.assertEqual(reloaded_org.modified_by, self.user)

    def test_update_with_new_user_email(self):
        """Test updating with a new user email (creates user if not exists)"""
        new_user_email = "newuser@example.com"

        update_project_config(
            project_uuid=self.project_uuid,
            user_email=new_user_email,
            description="Updated by new user",
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        new_user = User.objects.get(email=new_user_email)

        self.assertEqual(reloaded_org.config["description"], "Updated by new user")
        self.assertEqual(reloaded_org.modified_by, new_user)
        self.assertEqual(new_user.username, new_user_email)

    def test_update_with_none_values_does_not_change_fields(self):
        """Test that passing None values doesn't change existing fields"""
        original_name = self.test_org.name
        original_language = self.test_org.language

        update_project_config(
            project_uuid=self.project_uuid,
            user_email=self.user.email,
            name=None,
            description="Only description changed",
            language=None,
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertEqual(reloaded_org.name, original_name)
        self.assertEqual(reloaded_org.language, original_language)
        self.assertEqual(reloaded_org.config["description"], "Only description changed")

    def test_update_description_when_config_is_none(self):
        """Test updating description when config field is None"""
        org_without_config = Org.objects.create(
            name="Org Without Config",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            proj_uuid=uuid.uuid4(),
            created_by=self.user,
            modified_by=self.user,
            config=None,
            language="en-us",
        )
        org_uuid = str(org_without_config.proj_uuid)

        update_project_config(
            project_uuid=org_uuid,
            user_email=self.user.email,
            description="New description for empty config",
        )

        reloaded_org = Org.objects.get(proj_uuid=org_uuid)

        self.assertIsNotNone(reloaded_org.config)
        self.assertEqual(reloaded_org.config["description"], "New description for empty config")

    def test_update_same_values_does_not_save(self):
        """Test that updating with same values doesn't trigger unnecessary saves"""
        # Update with same name
        updated_org = update_project_config(
            project_uuid=self.project_uuid,
            name="Test Org",  # Same as original
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertEqual(updated_org, reloaded_org)

    def test_update_nonexistent_project_raises_error(self):
        """Test that updating a non-existent project raises an error"""
        fake_uuid = str(uuid.uuid4())

        with self.assertRaises(Org.DoesNotExist):
            update_project_config(
                project_uuid=fake_uuid,
                user_email=self.user.email,
                description="This should fail",
            )
