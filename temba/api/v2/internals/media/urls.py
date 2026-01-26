from django.conf.urls import url

from .views import S3MediaProxyView

urlpatterns = [
    # S3 media proxy endpoint
    # file_id can be:
    # - A URL-encoded S3 URL
    # - A bucket:key format
    # - A relative path in the default bucket
    url(
        r"^api/v2/internals/media/download/(?P<file_id>.+)/$",
        S3MediaProxyView.as_view(),
        name="internals.media_download",
    ),
]
