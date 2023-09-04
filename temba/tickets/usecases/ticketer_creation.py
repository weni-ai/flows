import json

from django.contrib.auth import get_user_model

from weni.internal.models import Project

from temba.flows.models import FlowRevision, IntegrationRequest
from temba.tickets.models import Ticket, Ticketer, Topic


User = get_user_model()


def create_ticketer(
    ticketer_type: str, name: str, project_uuid: str, user_email: str, uuid: str
) -> Ticketer:
    project = Project.objects.get(project_uuid=project_uuid)
    integration_request = IntegrationRequest.objects.filter(project=project)

    user, created = User.objects.get_or_create(email=user_email)

    new_ticketer = Ticketer(
        org=project.org,
        ticketer_type=ticketer_type, 
        created_by=user,
        modified_by=user,
        uuid=uuid,
        name=name,
        config={},
    )

    new_ticketer.save()

    if not integration_request:
        IntegrationRequest.objects.create(
            flow=None, integration_uuid=uuid, name=name, repository=None, project=project
        )

    else:
        for integration in integration_request:
            ticketer_uuid=None
            topic_uuid=None
            flow = integration.flow
            last_revision = FlowRevision.objects.filter(flow=flow).last()
            definition = last_revision.definition

            for node in definition[0]["nodes"]:
                if node["actions"]:
                    if "ticketer" in node["actions"][0]:
                        ticketer_uuid = node["actions"][0]["ticketer"]["uuid"]
                    if "topic" in node["actions"][0]:
                        topic_uuid = node["actions"][0]["topic"]["uuid"]

            dumps_definition = json.dumps(last_revision.definition)
            
            if ticketer_uuid:
                update_ticketer = dumps_definition.replace(
                    ticketer_uuid, integration.integration_uuid, 
                )

                loads_definition = json.loads(update_ticketer)
                last_revision.definition = loads_definition
                last_revision.save()
            
            if topic_uuid:
                update_topic = dumps_definition.replace(
                    topic_uuid, integration.integration_uuid,
                )
                 

                loads_definition = json.loads(update_topic)
                last_revision.definition = loads_definition
                last_revision.save()

    return new_ticketer
