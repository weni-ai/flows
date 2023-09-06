import json

from weni.internal.models import Project, TicketerQueue

from django.contrib.auth import get_user_model

from temba.flows.models import FlowRevision, IntegrationRequest
from temba.tickets.models import Ticketer

User = get_user_model()


def list_flow_definition_ticketers(flow_definition) -> list:
    ticketers = []

    for node in flow_definition["nodes"]:
        actions = node.get("actions", [])
        for action in actions:
            ticketer = action.get("ticketer", {})
            topic = action.get("topic", {})
            if ticketer:
                ticketer = {
                    "name": ticketer.get("name"),
                    "uuid": ticketer.get("uuid"),
                    "topic": {},
                }
                if topic:
                    queue = {
                        "name": topic.get("name"),
                        "uuid": topic.get("uuid"),
                    }
                    ticketer["topic"].update(queue)
                ticketers.append(ticketer)

    return ticketers


def create_ticketer(
    project_auth: str, name: str, project_uuid: str, user_email: str, uuid: str, queues: list
) -> Ticketer:
    project = Project.objects.get(project_uuid=project_uuid)
    integration_requests = IntegrationRequest.objects.filter(project=project, name=name)

    if not integration_requests:
        raise KeyError("IntegrationRquest does not exist")

    user, created = User.objects.get_or_create(email=user_email)

    ticketer = Ticketer.objects.create(
        uuid=uuid,
        org=project.org,
        ticketer_type="wenichats",
        created_by=user,
        modified_by=user,
        name=name,
        config=dict(
            project_auth=project_auth,
            sector_uuid=uuid,
        ),
    )

    for queue in queues:
        TicketerQueue.objects.create(
            uuid=queue.get("uuid"),
            name=queue.get("name"),
            org=project.org,
            created_by=user,
            modified_by=user,
            ticketer=ticketer,
        )

    for integration_request in integration_requests:
        flow = integration_request.flow
        last_revision = FlowRevision.objects.filter(flow=flow).last()
        definition = last_revision.definition

        dumps_definition = json.dumps(definition)
        updated_definition = dumps_definition.replace(
            str(integration_request.integration_uuid),
            str(ticketer.uuid),
        )

        flow_definition_ticketers = list_flow_definition_ticketers(definition)

        for flow_definition_ticketer in flow_definition_ticketers:
            topic = flow_definition_ticketer.get("topic", {})
            topic_uuid = topic.get("uuid")
            topic_name = topic.get("name")

            queue = ticketer.queues.get(name=topic_name)
            updated_definition = updated_definition.replace(str(topic_uuid), str(queue.uuid))

        loads_definition = json.loads(updated_definition)
        last_revision.definition = loads_definition
        last_revision.save()

    return ticketer
