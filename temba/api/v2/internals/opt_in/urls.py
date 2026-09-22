from django.urls import path

from .views import OptInAudienceView, OptInContactCreateView, OptInContactFillView

urlpatterns = [
    path("opt_in/audience", OptInAudienceView.as_view(), name="internal_opt_in_audience"),
    path("opt_in/contacts", OptInContactCreateView.as_view(), name="internal_opt_in_contacts"),
    path(
        "opt_in/contacts/<uuid:contact_uuid>",
        OptInContactFillView.as_view(),
        name="internal_opt_in_contact_fill",
    ),
]
