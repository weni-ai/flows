from dataclasses import dataclass

from django.contrib.auth import get_user_model

from temba.flows.services import set_flows_mutability
from temba.orgs.models import Org

User = get_user_model()


@dataclass
class FlowImportDTO:
    project_uuid: str
    user_email: str
    definition: dict
    is_mutable: bool


class FlowImportUseCase:
    def get_org_by_project_uuid(self, project_uuid: str):
        return Org.objects.get(proj_uuid=project_uuid)

    def get_user_by_email(self, email: str):
        return User.objects.get(email=email)

    def import_flows(self, dto: FlowImportDTO) -> list:
        org = self.get_org_by_project_uuid(dto.project_uuid)
        user = self.get_user_by_email(dto.user_email)

        new_flows = org.import_app(dto.definition, user)

        set_flows_mutability(new_flows, dto.is_mutable)

        return [
            {
                "uuid": str(flow.uuid),
                "name": flow.name,
            }
            for flow in new_flows
        ]
