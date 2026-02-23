from django.conf.urls import url

from .views import S3MediaProxyView

urlpatterns = [
    # S3 media proxy endpoint
    # object_key is the S3 object key (path + filename in the bucket)
    # Example: /api/v2/internals/media/download/media/image.jpg/
    url(
        r"^api/v2/internals/media/download/(?P<object_key>.+)/$",
        S3MediaProxyView.as_view(),
        name="internals.media_download",
    ),
]
