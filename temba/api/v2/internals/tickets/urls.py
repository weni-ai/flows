from django.urls import path

from .views import GetDepartmentsView, GetQueuesView, OpenTicketView, TicketAssigneeView

urlpatterns = [
    path("ticket_assignee", TicketAssigneeView.as_view(), name="ticket_assignee"),
    path("open_ticket", OpenTicketView.as_view(), name="open_ticket"),
    path("get_departments", GetDepartmentsView.as_view(), name="get_departments"),
    path("get_queues", GetQueuesView.as_view(), name="get_queues"),
]
