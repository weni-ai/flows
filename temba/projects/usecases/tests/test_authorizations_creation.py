import uuid

import pytz
from weni.internal.models import Project

from django.conf import settings

from temba.projects.usecases.authorizations_creation import create_authorizations, get_or_create_user_by_email
from temba.tests.base import TembaTest


class CreateAuthorizationsTestCase(TembaTest):
    def test_get_or_create_user_by_email(self):
        # Crie um usuário com um email específico e verifique se ele é retornado corretamente
        email = "test@example.com"
        user, created = get_or_create_user_by_email(email)
        self.assertEqual(user.email, email)
        self.assertTrue(created)

        # Tente criar o mesmo usuário novamente e verifique se ele não é criado novamente
        user, created = get_or_create_user_by_email(email)
        self.assertEqual(user.email, email)
        self.assertFalse(created)

    def test_create_authorizations(self):
        # Crie um projeto fictício
        project = Project.objects.create(
            project_uuid=uuid.uuid4(),
            name="Temba New",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
        )

        # Crie uma lista de autorizações fictícias
        authorizations = [
            {"user_email": "user1@example.com", "role": 1},
            {"user_email": "user2@example.com", "role": 2},
            {"user_email": "user3@example.com", "role": 3},
            {"user_email": "user4@example.com", "role": 4},
            {"user_email": "user5@example.com", "role": 5},
        ]

        # Chame a função create_authorizations e verifique se as associações de roles são corretas
        create_authorizations(authorizations, project)

        self.assertEqual(list(project.viewers.all().values_list("email", flat=True)), ["user1@example.com"])
        self.assertEqual(list(project.editors.all().values_list("email", flat=True)), ["user2@example.com"])
        self.assertEqual(
            list(project.administrators.all().values_list("email", flat=True)),
            ["user3@example.com", "user4@example.com"],
        )
        self.assertEqual(list(project.agents.all().values_list("email", flat=True)), ["user5@example.com"])
