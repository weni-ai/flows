import json
import uuid

import pytz
from weni.internal.models import Project, TicketerQueue

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from temba.flows.models import FlowRevision, IntegrationRequest
from temba.tests.base import TembaTest
from temba.tickets.models import Ticketer
from temba.tickets.usecases.ticketer_creation import create_ticketer, list_flow_definition_ticketers


class ListFlowDefinitionTestCase(TestCase):
    def test_list_flow_definition_ticketers_return_flow_ticketers(self):
        ticketer_list = [
            {
                "uuid": "a69844ab-b49f-4988-9e13-2d2a50ffb23f",
                "name": "Setor teste EDA",
                "topic": {
                    "name": "Queue 1",
                    "uuid": "de6d19af-a905-475e-b824-bf7fbca277fd",
                },
            },
        ]

        with open("temba/tickets/usecases/tests/flowrevision_definition.json", "r") as file:
            definition = json.loads(file.read())

        ticketers = list_flow_definition_ticketers(definition)

        self.assertEquals(len(ticketers), 1)
        self.assertEquals(ticketer_list, ticketers)


class TicketerCreationTestCase(TembaTest):
    def setUp(self):
        self.user_email = "test@example.com"
        self.project_uuid = str(uuid.uuid4())
        self.project_auth = "project-auth"
        self.name = "Integration Request Name"
        self.queues = [{"uuid": "1d8176f2-c852-4d92-8521-9dbad81ae531", "name": "Queue 1"}]
        self.user, _ = User.objects.get_or_create(email=self.user_email)

        with open("temba/tickets/usecases/tests/flowrevision_definition.json", "r") as file:
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

    def test_create_ticketer_with_integration_request(self):
        self.integration_request = IntegrationRequest.objects.create(
            project=self.project,
            name=self.name,
            integration_uuid=str(uuid.uuid4()),
            repository=None,
            flow=self.flow,
        )

        ticketer_uuid = str(uuid.uuid4())

        ticketer = create_ticketer(
            uuid=ticketer_uuid,
            project_auth=self.project_auth,
            name=self.name,
            project_uuid=self.project_uuid,
            user_email=self.user_email,
            queues=self.queues,
        )

        self.assertIsInstance(ticketer, Ticketer)
        self.assertEqual(str(ticketer.uuid), ticketer_uuid)

        created_queues = TicketerQueue.objects.filter(ticketer=ticketer)
        self.assertEqual(created_queues.count(), len(self.queues))
        self.assertEqual(str(created_queues.first().queue_uuid), self.queues[0].get("uuid"))

    def test_adding_new_queue_to_existing_ticketer(self):
        ticketer_uuid = str(uuid.uuid4())

        ticketer = create_ticketer(
            uuid=ticketer_uuid,
            project_auth=self.project_auth,
            name=self.name,
            project_uuid=self.project_uuid,
            user_email=self.user_email,
            queues=self.queues,
        )

        self.assertEqual(ticketer.queues.count(), 1)

        queues = self.queues + [{"uuid": str(uuid.uuid4()), "name": "Queue 2"}]

        ticketer = create_ticketer(
            uuid=ticketer_uuid,
            project_auth=self.project_auth,
            name=self.name,
            project_uuid=self.project_uuid,
            user_email=self.user_email,
            queues=queues,
        )

        self.assertEqual(ticketer.queues.count(), 2)

        for queue in queues:
            queue_uuid = queue.get("uuid")
            ticketer.queues.get(queue_uuid=queue_uuid)
