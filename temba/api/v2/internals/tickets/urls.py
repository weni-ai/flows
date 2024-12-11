from django.urls import path

from .views import TicketAssigneeView

urlpatterns = [path("ticket_assignee", TicketAssigneeView.as_view(), name="ticket_assignee")]
