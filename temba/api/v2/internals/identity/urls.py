from django.urls import path

from .views import (
    IdentityAttachView,
    IdentityConfirmationView,
    IdentityDetachView,
    IdentityForgetView,
    IdentityGraphView,
    IdentityInactivityView,
)

urlpatterns = [
    path("identity/attach", IdentityAttachView.as_view(), name="internal_identity_attach"),
    path("identity/detach", IdentityDetachView.as_view(), name="internal_identity_detach"),
    path("identity/confirmation", IdentityConfirmationView.as_view(), name="internal_identity_confirmation"),
    path("identity", IdentityGraphView.as_view(), name="internal_identity_graph"),
    path("identity/inactivity", IdentityInactivityView.as_view(), name="internal_identity_inactivity"),
    path("identity/forget", IdentityForgetView.as_view(), name="internal_identity_forget"),
]
