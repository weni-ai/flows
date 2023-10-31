from weni.internal.models import Project

from django.contrib.auth import get_user_model

from ..models import TemplateType
from .exceptions import InvalidTemplateTypeData

User = get_user_model()


class FlowSetupHandlerUseCase:
    def setup_flows_in_project(self, project: Project, template_type: TemplateType, user: User):
        setup = template_type.setup

        if setup == {}:
            raise InvalidTemplateTypeData(f"The `setup` of TemplateType {template_type.uuid} is empty!")

        project.import_app(setup, user)
        self.disable_flows_has_issues(project, setup)

    def disable_flows_has_issues(self, project, sample_flows):
        flows_name = list(map(lambda flow: flow.get("name"), sample_flows.get("flows")))
        project.flows.filter(name__in=flows_name).update(has_issues=False)
