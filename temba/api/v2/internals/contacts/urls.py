from django.urls import path

from .views import InternalContactView

urlpatterns = [path("contacts", InternalContactView.as_view(), name="internal_contacts")]
