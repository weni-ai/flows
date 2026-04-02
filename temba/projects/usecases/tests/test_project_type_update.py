import uuid

import pytz

from django.conf import settings
from django.contrib.auth import get_user_model

from temba.orgs.models import Org
from temba.projects.usecases.project_type_update import update_project_type
from temba.tests.base import TembaTest

User = get_user_model()


class TestUpdateProjectType(TembaTest):
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
            is_active=True,
        )
        self.project_uuid = str(self.test_org.proj_uuid)

    def test_set_is_multi_agents_true(self):
        """Test setting is_multi_agents to True"""
        updated_org = update_project_type(
            project_uuid=self.project_uuid,
            is_multi_agents=True,
            user_email=self.user.email,
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertIsNotNone(updated_org)
        self.assertTrue(reloaded_org.config["is_multi_agents"])
        self.assertEqual(updated_org, reloaded_org)
        self.assertEqual(reloaded_org.modified_by, self.user)

    def test_set_is_multi_agents_false(self):
        """Test setting is_multi_agents to False"""
        self.test_org.config["is_multi_agents"] = True
        self.test_org.save()

        updated_org = update_project_type(
            project_uuid=self.project_uuid,
            is_multi_agents=False,
            user_email=self.user.email,
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertIsNotNone(updated_org)
        self.assertFalse(reloaded_org.config["is_multi_agents"])
        self.assertEqual(updated_org, reloaded_org)
        self.assertEqual(reloaded_org.modified_by, self.user)

    def test_set_is_multi_agents_preserves_other_config_keys(self):
        """Test that setting is_multi_agents does not remove other config keys"""
        updated_org = update_project_type(
            project_uuid=self.project_uuid,
            is_multi_agents=True,
            user_email=self.user.email,
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertIsNotNone(updated_org)
        self.assertTrue(reloaded_org.config["is_multi_agents"])
        self.assertEqual(reloaded_org.config["description"], "Test description")

    def test_set_is_multi_agents_when_config_is_none(self):
        """Test setting is_multi_agents when org config is None"""
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

        updated_org = update_project_type(
            project_uuid=org_uuid,
            is_multi_agents=True,
            user_email=self.user.email,
        )

        reloaded_org = Org.objects.get(proj_uuid=org_uuid)

        self.assertIsNotNone(updated_org)
        self.assertIsNotNone(reloaded_org.config)
        self.assertTrue(reloaded_org.config["is_multi_agents"])

    def test_same_value_does_not_update_modified_on(self):
        """Test that setting is_multi_agents to the same value skips the database update"""
        self.test_org.config["is_multi_agents"] = True
        self.test_org.save()

        original_modified_on = self.test_org.modified_on

        updated_org = update_project_type(
            project_uuid=self.project_uuid,
            is_multi_agents=True,
            user_email=self.user.email,
        )

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertIsNotNone(updated_org)
        self.assertTrue(reloaded_org.config["is_multi_agents"])
        self.assertEqual(reloaded_org.modified_on, original_modified_on)

    def test_update_with_new_user_email(self):
        """Test that a new user is created when an unknown email is provided"""
        new_user_email = "typeupdater@example.com"

        updated_org = update_project_type(
            project_uuid=self.project_uuid,
            is_multi_agents=True,
            user_email=new_user_email,
        )

        new_user = User.objects.get(email=new_user_email)
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)

        self.assertIsNotNone(updated_org)
        self.assertEqual(new_user.username, new_user_email)
        self.assertEqual(reloaded_org.modified_by, new_user)
        self.assertTrue(reloaded_org.config["is_multi_agents"])

    def test_nonexistent_project_returns_none(self):
        """Test that updating a non-existent project returns None"""
        fake_uuid = str(uuid.uuid4())

        result = update_project_type(
            project_uuid=fake_uuid,
            is_multi_agents=True,
            user_email=self.user.email,
        )

        self.assertIsNone(result)
