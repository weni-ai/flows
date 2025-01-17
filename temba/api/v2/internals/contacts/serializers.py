from rest_framework import serializers


class InternalContactSerializer(serializers.Serializer):
    contacts = serializers.ListSerializer(child=serializers.UUIDField(), min_length=1, max_length=100)
