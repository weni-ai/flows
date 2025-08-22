import uuid

from rest_framework import serializers


class ConversionEventSerializer(serializers.Serializer):
    """
    Serializer to validate received conversion events
    """

    EVENT_TYPE_CHOICES = [
        ("lead", "LeadSubmitted"),
        ("purchase", "Purchase"),
    ]

    event_type = serializers.ChoiceField(choices=EVENT_TYPE_CHOICES, required=True)
    channel_uuid = serializers.UUIDField(required=True)
    contact_urn = serializers.CharField(required=True, max_length=255)
    payload = serializers.JSONField(required=False, default=dict)

    def validate_channel_uuid(self, value):
        """Validate if channel_uuid is a valid UUID"""
        if not isinstance(value, uuid.UUID) and not uuid.UUID(str(value)):
            raise serializers.ValidationError("channel_uuid must be a valid UUID")
        return value

    def validate_payload(self, value):
        """Validate additional payload"""
        if not isinstance(value, dict):
            raise serializers.ValidationError("payload must be a valid JSON object")
        return value
