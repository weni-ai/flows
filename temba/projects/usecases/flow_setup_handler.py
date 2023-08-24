from django.contrib.auth import get_user_model

from ..models import TemplateType
from weni.internal.models import Project
from .exceptions import InvalidTemplateTypeData



User = get_user_model()


class FlowSetupHandlerUseCase:
    def setup_flows_in_project(self, project: Project, template_type: TemplateType, user: User):
        setup = template_type.setup

        if setup == {}:
            raise InvalidTemplateTypeData(f"The `setup` of TemplateType {template_type.uuid} is empty!")

        project.import_app(setup, user)
