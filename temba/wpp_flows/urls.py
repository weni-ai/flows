from rest_framework_nested import routers

from django.urls import include, path

from temba.wpp_flows.views import WhatsappFlowsViewset

router = routers.DefaultRouter()
router.register("whatsapp_flows", WhatsappFlowsViewset, basename="whatsapp_flows")

urlpatterns = [
    path("", include(router.urls)),
]
