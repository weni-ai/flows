from rest_framework import routers

from django.urls import path

from .views import BroadcastsViewSet, InternalBroadcastsUploadMediaEndpoint, InternalWhatsappBroadcastsEndpoint

router = routers.DefaultRouter()
router.register(r"broadcasts", BroadcastsViewSet, basename="broadcasts")

urlpatterns = [
    path(
        "whatsapp_broadcasts",
        InternalWhatsappBroadcastsEndpoint.as_view(),
        name="internal-whatsapp-broadcasts",
    ),
    path(
        "broadcasts/upload_media",
        InternalBroadcastsUploadMediaEndpoint.as_view(),
        name="internal-broadcasts-upload-media",
    ),
]

urlpatterns += router.urls
