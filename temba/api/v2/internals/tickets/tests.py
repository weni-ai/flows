from unittest.mock import patch

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
