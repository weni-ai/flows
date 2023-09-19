from dataclasses import dataclass

from weni.internal.clients.connect import ConnectInternalClient
from weni.internal.models import Project

from django.contrib.auth import get_user_model

from temba.projects.usecases.globals_creation import create_globals

from .interfaces import TemplateTypeIntegrationInterface

User = get_user_model()


@dataclass
class ProjectCreationDTO:
    uuid: str
    name: str
    is_template: bool
    date_format: str
    timezone: str
    template_type_uuid: str


class ProjectCreationUseCase:
    def __init__(self, template_type_integration: TemplateTypeIntegrationInterface):
        self.__template_type_integration = template_type_integration

    def get_or_create_user_by_email(self, email: str) -> tuple:
        return User.objects.get_or_create(email=email)

    def get_or_create_project(self, project_dto: ProjectCreationDTO, user: User) -> tuple:
        return Project.objects.get_or_create(
            project_uuid=project_dto.uuid,
            defaults=dict(
                name=project_dto.name,
                date_format=project_dto.date_format,
                timezone=project_dto.timezone,
                created_by=user,
                modified_by=user,
                config={
                    "is_template": project_dto.is_template,
                },
            ),
        )

    def create_project(self, project_dto: ProjectCreationDTO, user_email: str, extra_fields: dict) -> None:
        user, _ = self.get_or_create_user_by_email(user_email)
        project, _ = self.get_or_create_project(project_dto, user)
        ConnectInternalClient().update_project(project)
        project.administrators.add(user)
        project.initialize(sample_flows=False)
        project.save()

        if extra_fields:
            create_globals(extra_fields, project, user)

        if project_dto.is_template:
            self.__template_type_integration.integrate_template_type_in_project(
                project, project_dto.template_type_uuid, user
            )
