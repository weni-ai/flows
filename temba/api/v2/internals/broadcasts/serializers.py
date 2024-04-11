from rest_framework import serializers
from weni.serializers import fields as weni_serializers

from temba.api.v2 import fields
from temba.api.v2.serializers import WriteSerializer
from temba.msgs.models import Broadcast, Msg
from temba.utils import on_transaction_commit


class UserAndProjectSerializer(serializers.Serializer):
    user = weni_serializers.UserEmailRelatedField(required=True, write_only=True)
    project = weni_serializers.ProjectUUIDRelatedField(required=True, write_only=True)


class BroadcastSerializer(WriteSerializer):
    text = fields.TranslatableField(required=True, max_length=Msg.MAX_TEXT_LEN)
    urns = fields.URNListField(required=True)
    ticket = fields.TicketField(required=False)

    def save(self):
        text, base_language = self.validated_data["text"]

        broadcast = Broadcast.create(
            self.context["org"],
            self.context["user"],
            text=text,
            base_language=base_language,
            urns=self.validated_data.get("urns", []),
            template_state=Broadcast.TEMPLATE_STATE_UNEVALUATED,
            ticket=self.validated_data.get("ticket"),
        )

        on_transaction_commit(lambda: broadcast.send_async())

        return broadcast
