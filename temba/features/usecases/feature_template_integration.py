from weni.internal.models import Project

from django.contrib.auth import get_user_model

from temba.event_driven.publisher.rabbitmq_publisher import RabbitmqPublisher
from temba.projects.usecases.globals_creation import create_globals

User = get_user_model()


def get_or_create_user_by_email(email: str) -> tuple:  # pragma: no cover
    return User.objects.get_or_create(email=email, username=email)


def integrate_feature_template_consumer(
    project_uuid: Project,
    definition: dict,
    parameters: dict,
    feature_version_uuid: str,
    feature_uuid: str,
    user_email=None,
) -> Project:  # pragma: no cover
    project = Project.objects.get(project_uuid=project_uuid)
    user, _ = get_or_create_user_by_email(user_email)

    new_flows = project.import_app(definition, user)
    disable_flows_has_issues(project, definition)

    if parameters:
        create_globals(parameters, project, user)

    publish_integrate_success(
        project.project_uuid, feature_version_uuid, feature_uuid, format_new_flows_data(new_flows)
    )

    return project


def disable_flows_has_issues(project, sample_flows):  # pragma: no cover
    flows_name = list(map(lambda flow: flow.get("name"), sample_flows.get("flows")))
    project.flows.filter(name__in=flows_name).update(has_issues=False)


def format_new_flows_data(new_flows):
    flows_list = []
    for flow in new_flows:
        flow_data = {"base_uuid": flow.father_uuid, "uuid": flow.uuid, "name": flow.name}
        flows_list.append(flow_data)

    return flows_list


def publish_integrate_success(project_uuid, feature_version_uuid, feature_uuid, imported_data):  # pragma: no cover
    rabbitmq_publisher = RabbitmqPublisher()
    rabbitmq_publisher.send_message(
        body=dict(
            project_uuid=str(project_uuid),
            feature_version_uuid=feature_version_uuid,
            feature_uuid=feature_uuid,
            imported_flows=imported_data,
        ),
        exchange="flows-integrated-feature.topic",
        routing_key="",
    )
