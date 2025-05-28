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
