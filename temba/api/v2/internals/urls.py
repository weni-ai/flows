from .broadcasts.urls import urlpatterns as broadcasts_urlpatterns
from .channels.urls import urlpatterns as channels_urlpatterns
from .contacts.urls import urlpatterns as contacts_urlpatterns
from .flows.urls import urlpatterns as flows_urlpatterns
from .media.urls import urlpatterns as media_urlpatterns
from .msgs.urls import urlpatterns as msgs_urlpatterns
from .tickets.urls import urlpatterns as tickets_urlpatterns

urlpatterns = []
urlpatterns += broadcasts_urlpatterns
urlpatterns += flows_urlpatterns
urlpatterns += channels_urlpatterns
urlpatterns += tickets_urlpatterns
urlpatterns += contacts_urlpatterns
urlpatterns += msgs_urlpatterns
urlpatterns += media_urlpatterns
