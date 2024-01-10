from rest_framework import routers

from temba.templates.views import TemplateViewSet

router = routers.DefaultRouter()
router.register(r"template", TemplateViewSet, basename="template")

urlpatterns = router.urls
