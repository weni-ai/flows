from django.conf.urls import url

from .views import GetExternalTypes

urlpatterns = [
    url(r"^externals/(?P<slug>[^/.]+)/actions", GetExternalTypes.as_view(), name="actions"),
]
