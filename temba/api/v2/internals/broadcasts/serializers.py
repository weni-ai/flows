from rest_framework import serializers
from weni.serializers import fields as weni_serializers

from temba.api.v2 import fields
from temba.api.v2.serializers import WriteSerializer
from temba.msgs.models import Broadcast, Msg
from temba.templates.models import Template
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


class BroadcastWithStatisticsSerializer(serializers.ModelSerializer):
    statistics = serializers.SerializerMethodField()
    template = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    groups = fields.ContactGroupField(many=True)

    class Meta:
        model = Broadcast
        fields = [
            "id",
            "name",
            "created_by",
            "created_on",
            "modified_on",
            "text",
            "media",
            "broadcast_type",
            "groups",
            "status",
            "statistics",
            "template",
        ]

    def get_statistics(self, obj):
        stat = obj.statistics.first()
        return {
            "processed": stat.processed if stat else 0,
            "sent": stat.sent if stat else 0,
            "delivered": stat.delivered if stat else 0,
            "failed": stat.failed if stat else 0,
            "contact_count": stat.contact_count if stat else 0,
            "read": stat.read if stat else 0,
            "cost": stat.cost if stat else 0,
            "currency": stat.currency if stat else "BRL",
            "template_price": stat.template_price if stat else 0,
            "created_on": stat.created_on,
            "modified_on": stat.modified_on,
        }

    def get_template(self, obj):
        if not obj.template_id:
            return None
        template = Template.objects.filter(id=obj.template_id).first()
        if not template:
            return None
        return {"id": template.id, "name": template.name}

    def get_created_by(self, obj):
        return obj.created_by.email if obj.created_by else None
