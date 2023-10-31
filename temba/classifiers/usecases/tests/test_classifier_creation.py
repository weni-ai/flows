import json
import uuid

import pytz
from weni.internal.models import Project

from django.conf import settings
from django.contrib.auth.models import User

from temba.classifiers.models import Classifier
from temba.classifiers.usecases.classifier_creation import create_classifier
from temba.flows.models import FlowRevision, IntegrationRequest
from temba.tests.base import TembaTest


class ClassifierCreationTestCase(TembaTest):
    def setUp(self):
        self.user_email = "test@example.com"
        self.project_uuid = str(uuid.uuid4())
        self.project_auth = "project-auth"
        self.name = "Integration Classifier"
        self.uuid = str(uuid.uuid4())
        self.repository = str(uuid.uuid4())
        self.user, _ = User.objects.get_or_create(email=self.user_email)

        with open("temba/classifiers/usecases/tests/flowrevision_definition.json", "r") as file:
            definition = json.loads(file.read())

        self.project = Project.objects.create(
            project_uuid=self.project_uuid,
            name="Temba New",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
        )

        self.admin = self.user
        self.org = self.project.org
        self.flow = self.create_flow()

        self.revision = FlowRevision.objects.filter(flow=self.flow).last()
        self.revision.definition = definition
        self.revision.save()
        self.integration_request = IntegrationRequest.objects.create(
            project=self.project,
            name=self.name,
            integration_uuid=str(uuid.uuid4()),
            repository=self.repository,
            flow=self.flow,
        )

    def test_create_classifier(self):
        classifier = create_classifier(
            repository=self.repository,
            access_token=str(uuid.uuid4()),
            name=self.name,
            project_uuid=self.project_uuid,
            user_email=self.user_email,
            uuid=self.uuid,
        )

        self.assertIsInstance(classifier, Classifier)
        self.assertEqual(classifier.uuid, self.uuid)
