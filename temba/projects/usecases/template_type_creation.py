from temba.projects.models import TemplateType


def create_template_type(uuid: str, name: str, setup: dict) -> TemplateType:
    template_type = TemplateType(uuid=uuid, name=name, setup=dict(setup))
    template_type.save()

    return template_type
