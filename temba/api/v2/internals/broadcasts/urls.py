from rest_framework import routers

from django.urls import path

from .views import BroadcastsViewSet, InternalBroadcastStatisticMontlyEndpoint, InternalBroadcastStatisticsEndpoint, InternalWhatsappBroadcastsEndpoint

router = routers.DefaultRouter()
router.register(r"broadcasts", BroadcastsViewSet, basename="broadcasts")

urlpatterns = [
    path(
        "whatsapp_broadcasts",
        InternalWhatsappBroadcastsEndpoint.as_view(),
        name="internal-whatsapp-broadcasts",
    ),
    path("broadcasts-statistics", InternalBroadcastStatisticsEndpoint.as_view(), name="internal-broadcast-statistics"),
    path("broadcasts-statistics-stats", InternalBroadcastStatisticMontlyEndpoint.as_view(), name="internal-broadcast-statistics-stats"),
]

urlpatterns += router.urls
