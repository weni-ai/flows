from django.urls import path

from .views import InternalFirstContactsView

urlpatterns = [path("first_contacts", InternalFirstContactsView.as_view(), name="internal_first_contacts")]
