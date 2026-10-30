from rest_framework import serializers

MAX_MEDIA_URLS_PER_REQUEST = 20
MAX_MEDIA_URL_LENGTH = 2048


class MediaUrlsSerializer(serializers.Serializer):
    urls = serializers.ListField(
        child=serializers.CharField(max_length=MAX_MEDIA_URL_LENGTH, trim_whitespace=False),
        allow_empty=False,
        max_length=MAX_MEDIA_URLS_PER_REQUEST,
    )

    def validate_urls(self, urls):
        # URLs are echoed back as response keys, so they are kept as sent rather than trimmed
        if any(not url.strip() for url in urls):
            raise serializers.ValidationError("URLs must not be blank.")

        return urls
