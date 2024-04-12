from rest_framework import routers

from .views import FlowStartViewSet

router = routers.DefaultRouter()
router.register(r"flow_starts", FlowStartViewSet, basename="flow_starts")

urlpatterns = router.urls
