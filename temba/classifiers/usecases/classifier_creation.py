import json

from django.contrib.auth import get_user_model

from weni.internal.models import Project

from temba.classifiers.models import Classifier
from temba.flows.models import FlowRevision, IntegrationRequest


User = get_user_model()


def create_classifier(
    repository: str, access_token: str, name: str, project_uuid: str, user_email: str, uuid: str
) -> Classifier:
    project = Project.objects.get(project_uuid=project_uuid)
    integration_request = IntegrationRequest.objects.filter(repository=repository, project=project)

    user, created = User.objects.get_or_create(email=user_email)

    new_classifier = Classifier(
        org=project.org,
        created_by=user,
        modified_by=user,
        uuid=uuid,
        name=name,
        config={"access_token": access_token, "repository": repository},
    )
    new_classifier.save()

    if not integration_request:
        IntegrationRequest.objects.create(
            flow=None, integration_uuid=uuid, name=name, repository=repository, project=project
        )

    else:
        for integration in integration_request:
            flow = integration.flow
            print(flow, "\n")
            last_revision = FlowRevision.objects.filter(flow=flow).last()
            definition = json.dumps(last_revision.definition)

            for node in definition[0]["nodes"]:
                if node["actions"]:
                    if "classifier" in node["actions"][0]:
                        classifier_data = node["actions"][0]["classifier"]
                        classifier_uuid = classifier_data["uuid"]

            if classifier_uuid:
                update_classifier = definition.replace(
                    classifier_uuid, integration.integration_uuid, 
                )

                definition = json.loads(update_classifier)
                last_revision.definition = definition
                last_revision.save()

    return new_classifier
