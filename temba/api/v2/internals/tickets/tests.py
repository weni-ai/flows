from unittest.mock import patch

from rest_framework import status
from rest_framework.response import Response
from weni.internal.models import TicketerQueue

from django.contrib.auth.models import User

from temba.api.v2.validators import LambdaURLValidator
from temba.mailroom.client import MailroomException
from temba.tests import TembaTest
from temba.tickets.models import Ticket, Ticketer


class TicketAssigneeViewTest(TembaTest):
    @patch("temba.api.v2.internals.tickets.views.TicketAssigneeView.authentication_classes", [])
    @patch("temba.api.v2.internals.tickets.views.TicketAssigneeView.permission_classes", [])
    def test_request_without_body(self):
        url = "/api/v2/internals/ticket_assignee"
        response = self.client.post(url)

        self.assertEqual(response.status_code, 400)

    @patch("temba.api.v2.internals.tickets.views.TicketAssigneeView.authentication_classes", [])
    @patch("temba.api.v2.internals.tickets.views.TicketAssigneeView.permission_classes", [])
    def test_request_with_invalid_email(self):
        url = "/api/v2/internals/ticket_assignee"
        body = {"email": "user_email@", "uuid": "bca00a03-20fa-4cc0-8920-885371241b55"}
        response = self.client.post(url, data=body)

        self.assertEqual(response.status_code, 400)

    @patch("temba.api.v2.internals.tickets.views.TicketAssigneeView.authentication_classes", [])
    @patch("temba.api.v2.internals.tickets.views.TicketAssigneeView.permission_classes", [])
    def test_request_with_invalid_uuid(self):
        url = "/api/v2/internals/ticket_assignee"
        body = {"email": "user_email@email.com", "uuid": "bca00a03-20fa-4cc0-8920-885371241b55"}
        response = self.client.post(url, data=body)

        self.assertEqual(response.status_code, 404)

    @patch("temba.api.v2.internals.tickets.views.TicketAssigneeView.authentication_classes", [])
    @patch("temba.api.v2.internals.tickets.views.TicketAssigneeView.permission_classes", [])
    def test_request_success(self):
        ticketer = Ticketer.create(self.org, self.user, "WWC", "Email (junior@email.com)", {})
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])

        ticket = Ticket.objects.create(
            org=self.org,
            ticketer=ticketer,
            contact=contact,
            topic=self.org.default_ticket_topic,
            body="Where are my cookies?",
            status="O",
        )
        url = "/api/v2/internals/ticket_assignee"
        body = {"email": "user_email@email.com", "uuid": ticket.uuid}
        response = self.client.post(url, data=body)

        self.assertEqual(response.status_code, 200)

        ticket.refresh_from_db()
        self.assertEqual(ticket.assignee.email, "user_email@email.com")


class OpenTicketTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.joe = self.create_contact("Joe Blow", phone="123", fields={"age": "17", "gender": "male"})
        self.ticketer = Ticketer.create(
            self.org,
            self.admin,
            "wenichats",
            "Support Tickets",
            {"sector_uuid": "30df650c-f15a-4996-b825-2a35cdc941cc"},
        )

    def ticket_open_return_value(self):
        return {
            "body": '{"history_after":"2025-01-01 00:00:00"}',
            "external_id": "8ecb1e4a-b457-4645-a161-e2b02ddffa88",
            "ticketer": {
                "name": self.ticketer.name,
                "uuid": self.ticketer.uuid,
            },
            "topic": {
                "name": "General",
                "queue_uuid": self.org.default_ticket_topic.queue_uuid,
                "uuid": self.org.default_ticket_topic.uuid,
            },
            "uuid": "970b8069-50f5-4f6f-8f41-6b2d9f33d623",
        }

    @patch.object(LambdaURLValidator, "protected_resource")
    @patch("temba.mailroom.client.MailroomClient.ticket_open")
    def test_open_ticket(self, mock_ticket_open, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        mock_ticket_open.return_value = self.ticket_open_return_value()

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "ticketer": self.ticketer.uuid,
            "contact": self.joe.uuid,
            "assignee": "user_email@email.com",
            "topic": self.org.default_ticket_topic.uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        mock_ticket_open.assert_called_once_with(
            self.org.id,
            self.joe.id,
            self.ticketer.id,
            self.org.default_ticket_topic.id,
            0,
            '{"history_after":"2025-01-01 00:00:00+02:00"}',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["uuid"], "970b8069-50f5-4f6f-8f41-6b2d9f33d623")
        self.assertEqual(response.data["topic"]["uuid"], self.org.default_ticket_topic.uuid)

    @patch.object(LambdaURLValidator, "protected_resource")
    @patch("temba.mailroom.client.MailroomClient.ticket_open")
    def test_open_ticket_without_assignee(self, mock_ticket_open, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        mock_ticket_open.return_value = self.ticket_open_return_value()

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "ticketer": self.ticketer.uuid,
            "contact": self.joe.uuid,
            "topic": self.org.default_ticket_topic.uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 200)

    @patch.object(LambdaURLValidator, "protected_resource")
    @patch("temba.mailroom.client.MailroomClient.ticket_open")
    def test_open_ticket_with_assignee_empty(self, mock_ticket_open, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        mock_ticket_open.return_value = self.ticket_open_return_value()

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "ticketer": self.ticketer.uuid,
            "contact": self.joe.uuid,
            "assignee": "",
            "topic": self.org.default_ticket_topic.uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 200)

    @patch.object(LambdaURLValidator, "protected_resource")
    @patch("temba.mailroom.client.MailroomClient.ticket_open")
    def test_open_ticket_with_urn(self, mock_ticket_open, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        mock_ticket_open.return_value = self.ticket_open_return_value()

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "ticketer": self.ticketer.uuid,
            "contact_urn": self.joe.urns.first().identity,
            "assignee": "user_email@email.com",
            "topic": self.org.default_ticket_topic.uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        mock_ticket_open.assert_called_once_with(
            self.org.id,
            self.joe.id,
            self.ticketer.id,
            self.org.default_ticket_topic.id,
            0,
            '{"history_after":"2025-01-01 00:00:00+02:00"}',
        )

        self.assertEqual(response.status_code, 200)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_open_ticket_without_ticketer(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "contact": self.joe.uuid,
            "assignee": "user_email@email.com",
            "topic": self.org.default_ticket_topic.uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 400)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_open_ticket_not_found_ticketer(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "contact": self.joe.uuid,
            "ticketer": "77305cb6-4867-48f0-8d53-8d853e4ead1c",
            "assignee": "user_email@email.com",
            "topic": self.org.default_ticket_topic.uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 400)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_open_ticket_without_topic(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "ticketer": self.ticketer.uuid,
            "contact": self.joe.uuid,
            "assignee": "user_email@email.com",
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 400)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_open_ticket_not_found_topic(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "ticketer": self.ticketer.uuid,
            "contact": self.joe.uuid,
            "topic": "90ea2409-59d9-4cb6-b1ea-b92eabb373d0",
            "assignee": "user_email@email.com",
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 400)

    @patch.object(LambdaURLValidator, "protected_resource")
    @patch("temba.mailroom.client.MailroomClient.ticket_open")
    def test_open_ticket_invalid_topic(self, mock_ticket_open, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        error_response = {"error": "queue not found"}
        mock_ticket_open.side_effect = MailroomException("ticket_open", None, error_response)

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "ticketer": self.ticketer.uuid,
            "contact": self.joe.uuid,
            "assignee": "user_email@email.com",
            "topic": self.org.default_ticket_topic.uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        mock_ticket_open.assert_called_once_with(
            self.org.id,
            self.joe.id,
            self.ticketer.id,
            self.org.default_ticket_topic.id,
            0,
            '{"history_after":"2025-01-01 00:00:00+02:00"}',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, str(error_response))

    @patch.object(LambdaURLValidator, "protected_resource")
    @patch("temba.mailroom.client.MailroomClient.ticket_open")
    def test_open_ticket_with_assignee(self, mock_ticket_open, mock_protected_resource):
        self.user = User.objects.create_user(username="suppport", email="suppport@email.com")
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        mock_ticket_open.return_value = self.ticket_open_return_value()

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "ticketer": self.ticketer.uuid,
            "contact": self.joe.uuid,
            "assignee": self.user.email,
            "topic": self.org.default_ticket_topic.uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        mock_ticket_open.assert_called_once_with(
            self.org.id,
            self.joe.id,
            self.ticketer.id,
            self.org.default_ticket_topic.id,
            self.user.id,
            '{"history_after":"2025-01-01 00:00:00+02:00"}',
        )

        self.assertEqual(response.status_code, 200)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_open_ticket_wrong_contact(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "ticketer": self.ticketer.uuid,
            "contact": "0f3e1b46-a58e-4246-8fae-52bfd3087850",
            "assignee": "user_email@email.com",
            "topic": self.org.default_ticket_topic.uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 400)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_open_ticket_wrong_urn(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "ticketer": self.ticketer.uuid,
            "contact_urn": "5582998765432",
            "assignee": "user_email@email.com",
            "topic": self.org.default_ticket_topic.uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 400)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_open_ticket_invalid_project(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": "91b45788-8beb-48dd-8355-64aab570e0c9",
            "ticketer": self.ticketer.uuid,
            "contact_urn": "5582998765432",
            "assignee": "user_email@email.com",
            "topic": self.org.default_ticket_topic.uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 400)


class GetDepartmentsViewTest(TembaTest):
    @patch.object(LambdaURLValidator, "protected_resource")
    def test_get_departments(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = f"/api/v2/internals/get_departments?project={self.org.proj_uuid}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_get_departments_with_uuid(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)
        ticketer = Ticketer.create(
            self.org,
            self.admin,
            "wenichats",
            "Viewers Ticketer",
            {"sector_uuid": "bae31477-1a17-4302-9b1a-902f1b22fdce"},
        )

        queue = TicketerQueue.objects.create(
            created_by=self.user,
            modified_by=self.user,
            org=self.org,
            name="Fake Queue",
            ticketer=ticketer,
        )

        url = f"/api/v2/internals/get_departments?project={self.org.proj_uuid}&uuid={ticketer.uuid}"
        response = self.client.get(url)

        expected_data = {
            "ticketer_uuid": str(ticketer.uuid),
            "ticketer_name": ticketer.name,
            "type": str(ticketer.ticketer_type),
            "created_on": ticketer.created_on.isoformat().replace("+00:00", "Z"),
            "topics": [
                {
                    "topic_name": queue.name,
                    "topic_uuid": str(queue.uuid),
                }
            ],
        }

        self.assertEqual(response.status_code, 200)

        response_results = [dict(item) for item in response.data.get("results", [])]

        self.assertIn(expected_data, response_results)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_get_departments_without_project(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/get_departments"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_get_departments_with_invalid_project(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/get_departments?project=91b45788-8beb-48dd-8355-64aab570e0c9"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)


class GetQueuesViewTest(TembaTest):
    @patch.object(LambdaURLValidator, "protected_resource")
    def test_get_queues(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = f"/api/v2/internals/get_queues?project={self.org.proj_uuid}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_get_queues_without_project(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/get_queues"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_get_queues_with_invalid_project(self, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/get_queues?project=91b45788-8beb-48dd-8355-64aab570e0c9"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)
