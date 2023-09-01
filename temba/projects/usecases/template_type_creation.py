import itertools

from temba.campaigns.models import Campaign
from temba.projects.models import TemplateType

from weni.internal.models import Project


def create_template_type(uuid: str, name: str, project_uuid: Project) -> TemplateType:
    project = Project.objects.get(project_uuid=project_uuid)
    flows = project.flows.all()

    campaigns = Campaign.objects.filter(org=project.org, is_active=True)
    components = set(itertools.chain(flows, campaigns))
    setup = project.export_definitions("https://flows.weni.ai", components) # TODO: find a way to get branding["link"]

    template_type = TemplateType(uuid=uuid, name=name, setup=setup)
    template_type.save()

    return template_type
