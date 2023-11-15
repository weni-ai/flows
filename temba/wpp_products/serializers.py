from rest_framework import serializers


class UpdateCatalogSerializer(serializers.Serializer):
    channel = serializers.UUIDField(required=True)
    facebook_catalog_id = serializers.CharField(required=True)
