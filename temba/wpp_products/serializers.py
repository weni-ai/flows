from rest_framework import serializers


class UpdateCatalogSerializer(serializers.Serializer):
    facebook_catalog_id = serializers.CharField(required=True)
    is_active = serializers.BooleanField()
