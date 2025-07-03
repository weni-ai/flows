from rest_framework import routers

from temba.conversion_events.views import ConversionEventView

router = routers.DefaultRouter()
router.register(r"conversion", ConversionEventView, basename="conversion-events")

urlpatterns = router.urls
