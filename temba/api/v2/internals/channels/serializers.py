from rest_framework import serializers


class ChannelProjectSerializer(serializers.Serializer):
    channels = serializers.ListSerializer(child=serializers.UUIDField(), min_length=1, max_length=100)


class ChannelElevenLabsApiKeySerializer(serializers.Serializer):
    channel_uuid = serializers.UUIDField(required=True)
