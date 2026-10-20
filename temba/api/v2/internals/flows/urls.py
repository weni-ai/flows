from rest_framework import routers

from django.urls import path

from .views import FlowImportView, FlowStartViewSet

router = routers.DefaultRouter()
router.register(r"flow_starts", FlowStartViewSet, basename="flow_starts")

urlpatterns = [
    path("flows/import", FlowImportView.as_view(), name="internal-flows-import"),
]

urlpatterns += router.urls
