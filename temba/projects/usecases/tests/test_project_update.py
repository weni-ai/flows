import uuid

import pytz
from weni.internal.models import Project

from django.conf import settings

from temba.projects.usecases.project_update import update_project_config
from temba.tests.base import TembaTest


class TestUpdateProjectConfig(TembaTest):
    def test_update_project_config(self):
        project = Project.objects.create(
            project_uuid=str(uuid.uuid4()),
            name="Temba New",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
            config={"description": "Old description"},
        )

        updated_project = update_project_config(project.project_uuid, "New description", self.user.email)
        reloaded_project = Project.objects.get(project_uuid=project.project_uuid)

        self.assertEqual(reloaded_project.config["description"], "New description")

        self.assertEqual(updated_project, reloaded_project)

        updated_project_without_user_email = update_project_config(project.project_uuid, "New description 2")
        reloaded_project = Project.objects.get(project_uuid=project.project_uuid)

        self.assertEqual(reloaded_project.config["description"], "New description 2")
        self.assertEqual(updated_project_without_user_email, reloaded_project)
