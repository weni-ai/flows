from rest_framework import serializers

from django.contrib.auth import get_user_model

from temba.contacts.models import Contact, ContactURN
from temba.tickets.models import Ticketer

User = get_user_model()


class TicketAssigneeSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    email = serializers.EmailField()


class OpenTicketSerializer(serializers.Serializer):
    sector = serializers.UUIDField()
    contact = serializers.UUIDField(required=False)
    contact_urn = serializers.CharField(required=False)
    assignee = serializers.EmailField()
    conversation_started_on = serializers.DateTimeField()
    queue = serializers.UUIDField()

    def validate(self, data):
        sector_uuid = data.get("sector")
        contact_uuid = data.get("contact")
        urn = data.get("contact_urn")

        ticketer = Ticketer.objects.filter(config__sector_uuid=str(sector_uuid)).first()
        if not ticketer:
            raise serializers.ValidationError({"ticketer": "ticketer for sector not found"})
        if contact_uuid is not None:
            try:
                ctt = Contact.objects.get(uuid=contact_uuid)
            except Contact.DoesNotExist:
                raise serializers.ValidationError({"contact": "contact not found"})
        else:
            try:
                ctt = ContactURN.objects.get(path=urn)
                data["contact"] = ctt.contact.uuid
            except ContactURN.DoesNotExist:
                raise serializers.ValidationError({"contact_urn": "contact URN not found"})

        return data
