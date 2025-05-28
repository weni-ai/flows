import pytz
from rest_framework import serializers

from temba.api.v2 import fields
from temba.api.v2.serializers import ReadSerializer
from temba.msgs.models import Msg


class InternalMsgReadSerializer(ReadSerializer):
    STATUSES = {
        Msg.STATUS_INITIALIZING: "initializing",
        Msg.STATUS_PENDING: "queued",  # same as far as users are concerned
        Msg.STATUS_QUEUED: "queued",
        Msg.STATUS_WIRED: "wired",
        Msg.STATUS_SENT: "sent",
        Msg.STATUS_DELIVERED: "delivered",
        Msg.STATUS_HANDLED: "handled",
        Msg.STATUS_ERRORED: "errored",
        Msg.STATUS_FAILED: "failed",
        Msg.STATUS_RESENT: "resent",
        Msg.STATUS_READ: "read",
    }
    TYPES = {Msg.TYPE_INBOX: "inbox", Msg.TYPE_FLOW: "flow", Msg.TYPE_IVR: "ivr"}
    VISIBILITIES = {
        Msg.VISIBILITY_VISIBLE: "visible",
        Msg.VISIBILITY_ARCHIVED: "archived",
        Msg.VISIBILITY_DELETED: "deleted",
    }

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
