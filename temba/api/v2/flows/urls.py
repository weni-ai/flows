from django.urls import path

from .views import SimulateAPIView

urlpatterns = [
    path("flows/<uuid:flow_uuid>/simulate", SimulateAPIView.as_view(), name="flow_simulation"),
]
