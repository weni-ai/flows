from rest_framework import serializers


class ChannelProjectSerializer(serializers.Serializer):
    channels = serializers.ListSerializer(child=serializers.UUIDField(), min_length=1, max_length=100)


class ChannelElevenLabsApiKeySerializer(serializers.Serializer):
    channel_uuid = serializers.UUIDField(required=True)


class ChannelMarketingTagsSerializer(serializers.Serializer):
    channel_uuid = serializers.UUIDField(required=True)


class ChannelWabaMigrationSerializer(serializers.Serializer):
    old_waba_id = serializers.CharField(required=True, max_length=64)
    new_waba_id = serializers.CharField(required=True, max_length=64)


class ChannelSIPSerializer(serializers.Serializer):
    """Both identifiers must be UUIDs, so nothing else ever reaches a query or a cluster object name."""

    channel_uuid = serializers.UUIDField(required=True)
    project_uuid = serializers.UUIDField(required=True)
