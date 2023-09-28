import json

from weni.internal.models import Project

from django.contrib.auth import get_user_model

from temba.classifiers.models import Classifier
from temba.flows.models import FlowRevision, IntegrationRequest

User = get_user_model()


def create_classifier(
    repository: str, access_token: str, name: str, project_uuid: str, user_email: str, uuid: str
) -> Classifier:
    project = Project.objects.get(project_uuid=project_uuid)
    integration_requests = IntegrationRequest.objects.filter(project=project, repository=repository)

    user, created = User.objects.get_or_create(email=user_email)

    classifier = Classifier.objects.create(
        org=project.org,
        classifier_type="bothub",
        created_by=user,
        modified_by=user,
        uuid=uuid,
        name=name,
        config={"access_token": access_token, "repository": repository},
    )

    classifier.sync()

    for integration_request in integration_requests:
        flow = integration_request.flow
        last_revision = FlowRevision.objects.filter(flow=flow).last()
        definition = last_revision.definition

        dumps_definition = json.dumps(definition)
        updated_definition = dumps_definition.replace(
            str(integration_request.integration_uuid),
            str(classifier.uuid),
        )

        loads_definition = json.loads(updated_definition)
        last_revision.definition = loads_definition
        last_revision.save()

    return classifier
