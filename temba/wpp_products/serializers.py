from rest_framework import serializers


class UpdateCatalogSerializer(serializers.Serializer):
    name = serializers.CharField(required=True)
    facebook_catalog_id = serializers.CharField(required=True)
    is_active = serializers.BooleanField()
