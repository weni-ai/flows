from unittest.mock import patch

from rest_framework import status
from rest_framework.response import Response

from django.contrib.auth.models import User

from temba.api.v2.validators import LambdaURLValidator
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
        return Response(
            {
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
            },
            status=status.HTTP_200_OK,
        )

    @patch.object(LambdaURLValidator, "protected_resource")
    @patch("temba.mailroom.client.MailroomClient.ticket_open")
    def test_open_ticket(self, mock_ticket_open, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        mock_ticket_open.return_value = self.ticket_open_return_value()

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "sector": self.ticketer.config["sector_uuid"],
            "contact": self.joe.uuid,
            "assignee": "user_email@email.com",
            "queue": self.org.default_ticket_topic.queue_uuid,
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
    def test_open_ticket_without_assignee_and_queue(self, mock_ticket_open, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        mock_ticket_open.return_value = self.ticket_open_return_value()

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "sector": self.ticketer.config["sector_uuid"],
            "contact": self.joe.uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 200)

    @patch.object(LambdaURLValidator, "protected_resource")
    @patch("temba.mailroom.client.MailroomClient.ticket_open")
    def test_open_ticket_with_assignee_and_queue_empty(self, mock_ticket_open, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        mock_ticket_open.return_value = self.ticket_open_return_value()

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "sector": self.ticketer.config["sector_uuid"],
            "contact": self.joe.uuid,
            "assignee": "",
            "queue": "",
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
            "sector": self.ticketer.config["sector_uuid"],
            "contact_urn": self.joe.urns.first().path,
            "assignee": "user_email@email.com",
            "queue": self.org.default_ticket_topic.queue_uuid,
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
            "sector": "1cfa4c9e-d69b-436c-971e-ca444334b60f",
            "contact": self.joe.uuid,
            "assignee": "user_email@email.com",
            "queue": self.org.default_ticket_topic.queue_uuid,
            "conversation_started_on": "2025-01-01 00:00:00",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 400)

    @patch.object(LambdaURLValidator, "protected_resource")
    @patch("temba.mailroom.client.MailroomClient.ticket_open")
    def test_open_ticket_default_topic_if_not_found(self, mock_ticket_open, mock_protected_resource):
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        mock_ticket_open.return_value = self.ticket_open_return_value()

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "sector": self.ticketer.config["sector_uuid"],
            "contact": self.joe.uuid,
            "assignee": "user_email@email.com",
            "queue": "76d73017-7479-4817-960c-a154d3dac4a1",
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
    @patch("temba.mailroom.client.MailroomClient.ticket_open")
    def test_open_ticket_with_assignee(self, mock_ticket_open, mock_protected_resource):
        self.user = User.objects.create_user(username="suppport", email="suppport@email.com")
        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        mock_ticket_open.return_value = self.ticket_open_return_value()

        url = "/api/v2/internals/open_ticket"
        body = {
            "project": self.org.proj_uuid,
            "sector": self.ticketer.config["sector_uuid"],
            "contact": self.joe.uuid,
            "assignee": self.user.email,
            "queue": self.org.default_ticket_topic.queue_uuid,
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
            "sector": self.ticketer.config["sector_uuid"],
            "contact": "0f3e1b46-a58e-4246-8fae-52bfd3087850",
            "assignee": "user_email@email.com",
            "queue": self.org.default_ticket_topic.queue_uuid,
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
            "sector": self.ticketer.config["sector_uuid"],
            "contact_urn": "5582998765432",
            "assignee": "user_email@email.com",
            "queue": self.org.default_ticket_topic.queue_uuid,
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
            "sector": self.ticketer.config["sector_uuid"],
            "contact_urn": "5582998765432",
            "assignee": "user_email@email.com",
            "queue": self.org.default_ticket_topic.queue_uuid,
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
        url = f"/api/v2/internals/get_departments?project={self.org.proj_uuid}&uuid={ticketer.uuid}"
        response = self.client.get(url)

        expected_data = {
            "uuid": str(ticketer.uuid),
            "name": ticketer.name,
            "type": str(ticketer.ticketer_type),
            "created_on": ticketer.created_on.isoformat().replace("+00:00", "Z"),
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
