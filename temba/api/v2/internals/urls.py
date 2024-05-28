from .broadcasts.urls import urlpatterns as broadcasts_urlpatterns
from .channels.urls import urlpatterns as channels_urlpatterns
from .flows.urls import urlpatterns as flows_urlpatterns

urlpatterns = []
urlpatterns += broadcasts_urlpatterns
urlpatterns += flows_urlpatterns
urlpatterns += channels_urlpatterns
