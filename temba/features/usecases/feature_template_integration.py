from weni.internal.models import Project

from django.contrib.auth import get_user_model

from temba.projects.usecases.globals_creation import create_globals

User = get_user_model()


def get_or_create_user_by_email(email: str) -> tuple:  # pragma: no cover
    return User.objects.get_or_create(email=email, username=email)


def integrate_feature_template_consumer(
    project_uuid: Project, definition: dict, parameters: dict, user_email=None
) -> Project:  # pragma: no cover
    project = Project.objects.get(project_uuid=project_uuid)
    user, _ = get_or_create_user_by_email(user_email)

    project.import_app(definition, user)
    disable_flows_has_issues(project, definition)

    if parameters:
        create_globals(parameters, project, user)

    return project


def disable_flows_has_issues(project, sample_flows):  # pragma: no cover
    flows_name = list(map(lambda flow: flow.get("name"), sample_flows.get("flows")))
    project.flows.filter(name__in=flows_name).update(has_issues=False)
