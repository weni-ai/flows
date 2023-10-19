from rest_framework_nested import routers

from django.urls import include, path

from .views import CatalogViewSet

router = routers.SimpleRouter()
router.register("catalogs", CatalogViewSet, basename="catalog")

urlpatterns = [
    path("", include(router.urls)),
]
