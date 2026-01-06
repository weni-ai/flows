import pytz
from rest_framework import serializers

from temba.api.v2 import fields
from temba.api.v2.serializers import MsgReadSerializer, ReadSerializer
from temba.msgs.models import Msg


class InternalMsgReadSerializer(ReadSerializer):
    STATUSES = MsgReadSerializer.STATUSES
    VISIBILITIES = MsgReadSerializer.VISIBILITIES

    contact = fields.ContactField()
    urn = fields.URNField(source="contact_urn")
    channel = fields.ChannelField()
    direction = serializers.SerializerMethodField()
    created_on = serializers.DateTimeField(default_timezone=pytz.UTC)

    def get_direction(self, obj):
        return "in" if obj.direction == Msg.DIRECTION_IN else "out"

    class Meta:
        model = Msg
        fields = (
            "id",
            "contact",
            "urn",
            "channel",
            "direction",
            "text",
            "created_on",
        )


class MsgStreamSerializer(serializers.Serializer):
    project_uuid = serializers.UUIDField()
    direction = serializers.ChoiceField(choices=("in", "out", "I", "O"))
    contact_uuid = serializers.UUIDField(required=False)
    urn = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    channel_uuid = serializers.UUIDField(required=False)
    template = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    message = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    msg = serializers.DictField(required=False)
    attachments = serializers.ListField(child=serializers.URLField(), required=False)
    created_on = serializers.DateTimeField(required=False)
    sent_on = serializers.DateTimeField(required=False)
    status = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    visibility = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    labels = serializers.ListField(child=serializers.UUIDField(), required=False)

    def validate(self, data):
        # require at least one contact identifier
        if not data.get("contact_uuid") and not data.get("urn"):
            raise serializers.ValidationError("Must provide either contact_uuid or urn")

        # require some content
        if not (data.get("text") or data.get("message") or data.get("attachments") or data.get("msg")):
            raise serializers.ValidationError("Must provide text, message, attachments or msg")

        return data
