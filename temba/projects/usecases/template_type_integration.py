from typing import TYPE_CHECKING

from ..models import TemplateType
from .exceptions import InvalidTemplateTypeData
from .interfaces import TemplateTypeIntegrationInterface

if TYPE_CHECKING:
    from ..models import Project
    from django.contrib.auth import get_user_model

    User = get_user_model()


class TemplateTypeIntegrationUseCase(TemplateTypeIntegrationInterface):
    def __init__(self, flow_setup_handler):
        self.__flow_setup_handler = flow_setup_handler

    def integrate_template_type_in_project(self, project: "Project", template_type_uuid: str, user: "User") -> None:
        if project.config.get("template_type") is not None:
            raise InvalidTemplateTypeData(f"The project `{project.uuid}` already has an integrated template!")

        if template_type_uuid is None:
            raise InvalidTemplateTypeData("'template_type_uuid' cannot be empty when 'is_template' is True!")

        try:
            template_type = TemplateType.objects.get(uuid=template_type_uuid)
        except TemplateType.DoesNotExist:
            raise InvalidTemplateTypeData(f"Template Type with uuid `{template_type_uuid}` does not exists!")

        self.__flow_setup_handler.setup_flows_in_project(project, template_type, user)

        project.config["template_type"] = str(template_type.uuid)
        project.save()
