from rest_framework import serializers

from django.contrib.auth import get_user_model

from temba.contacts.models import Contact, ContactURN
from temba.orgs.models import Org
from temba.tickets.models import Ticketer, Topic

User = get_user_model()


class TicketAssigneeSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    email = serializers.EmailField()


class OpenTicketSerializer(serializers.Serializer):
    project = serializers.UUIDField()
    ticketer = serializers.UUIDField()
    topic = serializers.UUIDField()
    contact = serializers.UUIDField(required=False, allow_null=True)
    contact_urn = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    assignee = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    conversation_started_on = serializers.DateTimeField()

    def validate(self, data):
        project_uuid = data.get("project")
        ticketer_uuid = data.get("ticketer")
        topic_uuid = data.get("topic")
        contact_uuid = data.get("contact")
        urn = data.get("contact_urn")

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            raise serializers.ValidationError({"project": "project not found"})

        try:
            ticketer = Ticketer.objects.get(uuid=ticketer_uuid)
        except Ticketer.DoesNotExist:
            raise serializers.ValidationError({"ticketer": "ticketer not found"})

        try:
            topic = Topic.objects.get(uuid=topic_uuid)
        except Topic.DoesNotExist:
            raise serializers.ValidationError({"topic": "topic not found"})

        if contact_uuid is not None:
            try:
                ctt = Contact.objects.get(uuid=contact_uuid)
                data["contact_id"] = ctt.id
            except Contact.DoesNotExist:
                raise serializers.ValidationError({"contact": "contact not found"})

        else:
            try:
                ctt = ContactURN.objects.get(identity=urn, org_id=org.id)
                data["contact_id"] = ctt.contact.id
            except ContactURN.DoesNotExist:
                raise serializers.ValidationError({"contact_urn": "contact URN not found"})

        data["org_id"] = org.id
        data["ticketer_id"] = ticketer.id
        data["topic_id"] = topic.id

        return data
