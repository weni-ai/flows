import uuid

import pytz
from weni.internal.models import Project

from django.conf import settings
from django.contrib.auth import get_user_model

from temba.projects.usecases.project_update import update_project_config
from temba.tests.base import TembaTest

User = get_user_model()


class TestUpdateProjectConfig(TembaTest):
    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(
            project_uuid=str(uuid.uuid4()),
            name="Test Project",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
            config={"description": "Old description"},
            language="en-us",
        )

    def test_update_description_only(self):
        """Test updating only the description field"""
        updated_project = update_project_config(
            project_uuid=self.project.project_uuid,
            user_email=self.user.email,
            description="New description",
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)

        self.assertEqual(reloaded_project.config["description"], "New description")
        self.assertEqual(reloaded_project.name, "Test Project")
        self.assertEqual(reloaded_project.language, "en-us")
        self.assertEqual(updated_project, reloaded_project)
        self.assertEqual(reloaded_project.modified_by, self.user)

    def test_update_name_only(self):
        """Test updating only the name field"""
        updated_project = update_project_config(
            project_uuid=self.project.project_uuid,
            user_email=self.user.email,
            name="Updated Project Name",
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)

        self.assertEqual(reloaded_project.name, "Updated Project Name")
        self.assertEqual(reloaded_project.config["description"], "Old description")
        self.assertEqual(reloaded_project.language, "en-us")
        self.assertEqual(updated_project, reloaded_project)

    def test_update_language_only(self):
        """Test updating only the language field"""
        updated_project = update_project_config(
            project_uuid=self.project.project_uuid,
            user_email=self.user.email,
            language="pt-br",
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)

        self.assertEqual(reloaded_project.language, "pt-br")
        self.assertEqual(reloaded_project.name, "Test Project")
        self.assertEqual(reloaded_project.config["description"], "Old description")
        self.assertEqual(updated_project, reloaded_project)

    def test_update_all_fields(self):
        """Test updating all fields at once"""
        updated_project = update_project_config(
            project_uuid=self.project.project_uuid,
            user_email=self.user.email,
            name="Completely New Name",
            description="Completely new description",
            language="es",
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)

        self.assertEqual(reloaded_project.name, "Completely New Name")
        self.assertEqual(reloaded_project.config["description"], "Completely new description")
        self.assertEqual(reloaded_project.language, "es")
        self.assertEqual(updated_project, reloaded_project)

    def test_update_without_user_email(self):
        """Test updating without providing user_email"""
        updated_project = update_project_config(
            project_uuid=self.project.project_uuid,
            description="Description without user",
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)

        self.assertEqual(reloaded_project.config["description"], "Description without user")
        self.assertEqual(updated_project, reloaded_project)
        # modified_by should remain unchanged
        self.assertEqual(reloaded_project.modified_by, self.user)

    def test_update_with_new_user_email(self):
        """Test updating with a new user email (creates user if not exists)"""
        new_user_email = "newuser@example.com"
        
        updated_project = update_project_config(
            project_uuid=self.project.project_uuid,
            user_email=new_user_email,
            description="Updated by new user",
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        new_user = User.objects.get(email=new_user_email)

        self.assertEqual(reloaded_project.config["description"], "Updated by new user")
        self.assertEqual(reloaded_project.modified_by, new_user)
        self.assertEqual(new_user.username, new_user_email)

    def test_update_with_none_values_does_not_change_fields(self):
        """Test that passing None values doesn't change existing fields"""
        original_name = self.project.name
        original_language = self.project.language
        
        updated_project = update_project_config(
            project_uuid=self.project.project_uuid,
            user_email=self.user.email,
            name=None,
            description="Only description changed",
            language=None,
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)

        self.assertEqual(reloaded_project.name, original_name)
        self.assertEqual(reloaded_project.language, original_language)
        self.assertEqual(reloaded_project.config["description"], "Only description changed")

    def test_update_description_when_config_is_none(self):
        """Test updating description when config field is None"""
        project_without_config = Project.objects.create(
            project_uuid=str(uuid.uuid4()),
            name="Project Without Config",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
            config=None,
            language="en-us",
        )

        updated_project = update_project_config(
            project_uuid=project_without_config.project_uuid,
            user_email=self.user.email,
            description="New description for empty config",
        )

        reloaded_project = Project.objects.get(project_uuid=project_without_config.project_uuid)

        self.assertIsNotNone(reloaded_project.config)
        self.assertEqual(reloaded_project.config["description"], "New description for empty config")

    def test_update_same_values_does_not_save(self):
        """Test that updating with same values doesn't trigger unnecessary saves"""
        # Update with same name
        updated_project = update_project_config(
            project_uuid=self.project.project_uuid,
            name="Test Project",  # Same as original
        )

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertEqual(updated_project, reloaded_project)

    def test_update_nonexistent_project_raises_error(self):
        """Test that updating a non-existent project raises an error"""
        fake_uuid = str(uuid.uuid4())
        
        with self.assertRaises(Project.DoesNotExist):
            update_project_config(
                project_uuid=fake_uuid,
                user_email=self.user.email,
                description="This should fail",
            )
