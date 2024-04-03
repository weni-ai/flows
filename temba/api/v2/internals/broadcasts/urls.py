from rest_framework import routers

from .views import BroadcastsViewSet


router = routers.DefaultRouter()
router.register(r"broadcasts", BroadcastsViewSet, basename="broadcasts")

urlpatterns = router.urls
