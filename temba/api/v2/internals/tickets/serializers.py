from rest_framework import serializers

from django.contrib.auth import get_user_model

from temba.contacts.models import Contact, ContactURN
from temba.orgs.models import Org
from temba.tickets.models import Ticketer

User = get_user_model()


class TicketAssigneeSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    email = serializers.EmailField()


class OpenTicketSerializer(serializers.Serializer):
    project = serializers.UUIDField()
    sector = serializers.UUIDField()
    contact = serializers.UUIDField(required=False, allow_null=True)
    contact_urn = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    assignee = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    conversation_started_on = serializers.DateTimeField()

    def validate(self, data):
        project_uuid = data.get("project")
        sector_uuid = data.get("sector")
        contact_uuid = data.get("contact")
        urn = data.get("contact_urn")

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
            data["org_id"] = org.id
        except Org.DoesNotExist:
            raise serializers.ValidationError({"project": "project not found"})

        ticketer = Ticketer.objects.filter(config__sector_uuid=str(sector_uuid), org_id=org.id).first()
        if not ticketer:
            raise serializers.ValidationError({"ticketer": "ticketer for sector not found"})
        if contact_uuid is not None:
            try:
                ctt = Contact.objects.get(uuid=contact_uuid)
            except Contact.DoesNotExist:
                raise serializers.ValidationError({"contact": "contact not found"})
        else:
            try:
                ctt = ContactURN.objects.get(path=urn, org_id=org.id)
                data["contact"] = ctt.contact.uuid
            except ContactURN.DoesNotExist:
                raise serializers.ValidationError({"contact_urn": "contact URN not found"})

        return data
