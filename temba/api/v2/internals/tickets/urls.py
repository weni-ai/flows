from django.urls import path

from .views import TicketAssigneeView, OpenTicketView

urlpatterns = [
    path("ticket_assignee", TicketAssigneeView.as_view(), name="ticket_assignee"),
    path("open_ticket", OpenTicketView.as_view(), name="open_ticket"),
]
