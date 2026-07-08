from django.urls import path

from .views import CreateTicketerView, GetDepartmentsView, GetQueuesView, OpenTicketView, TicketAssigneeView

urlpatterns = [
    path("ticket_assignee", TicketAssigneeView.as_view(), name="ticket_assignee"),
    path("ticketer", CreateTicketerView.as_view(), name="create_ticketer"),
    path("open_ticket", OpenTicketView.as_view(), name="open_ticket"),
    path("get_departments", GetDepartmentsView.as_view(), name="get_departments"),
    path("get_queues", GetQueuesView.as_view(), name="get_queues"),
]
