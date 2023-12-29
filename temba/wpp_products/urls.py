from rest_framework_nested import routers

from django.urls import include, path

from .views import CatalogViewSet, ProductViewSet

router = routers.SimpleRouter()
router.register("catalogs", CatalogViewSet, basename="catalog")
router.register("products", ProductViewSet, basename="product")

urlpatterns = [
    path("", include(router.urls)),
]
