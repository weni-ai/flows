from dataclasses import dataclass

from weni.internal.models import Project

from django.contrib.auth import get_user_model

from temba.globals.models import Global

from .exceptions import InvalidProjectData
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

    def get_user_by_email(self, email: str) -> User:
        try:
            return User.objects.get(email=email)
        except User.DoesNotExist:
            raise InvalidProjectData(f"User with email `{email}` does not exist!")

    def get_or_create_project(self, project_dto: ProjectCreationDTO, user: User) -> tuple:
        return Project.objects.get_or_create(
            uuid=project_dto.uuid,
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

    def create_project(self, project_dto: ProjectCreationDTO, user_email: str) -> None:
        user = self.get_user_by_email(user_email)
        project, _ = self.get_or_create_project(project_dto, user)
        project.administrators.add(user)
        project.save()

        '''if extra_field in extra_fields:
            Global.objects.create(org=project.org, key=extra_fields.get("key"))'''

        if project_dto.is_template:
            self.__template_type_integration.integrate_template_type_in_project(
                project, project_dto.template_type_uuid, user
            )
