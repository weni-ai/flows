import pytz
from rest_framework import serializers
from weni.internal.models import TicketerQueue

from django.contrib.auth import get_user_model
from django.core import exceptions as django_exceptions

from temba.api.v2.serializers import ReadSerializer
from temba.contacts.models import Contact, ContactURN
from temba.orgs.models import Org
from temba.tickets.models import Ticketer, Topic
from temba.tickets.types.generic.type import GenericType
from temba.tickets.types.wenichats.type import WeniChatsType

User = get_user_model()


class TicketAssigneeSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    email = serializers.EmailField()


class CreateTicketerSerializer(serializers.Serializer):
    user = serializers.EmailField(required=True)
    org = serializers.CharField(required=True)
    name = serializers.CharField(required=True, max_length=64)
    ticketer_type = serializers.CharField(required=False, default=GenericType.slug, max_length=16)
    config = serializers.JSONField(required=True)

    def validate_org(self, value):
        try:
            self.org = Org.objects.get(proj_uuid=value)
        except (Org.DoesNotExist, django_exceptions.ValidationError, ValueError):
            raise serializers.ValidationError("Project not found")
        return value

    def validate_user(self, value):
        try:
            self.acting_user = User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found")
        return value

    def validate_config(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("config must be an object")
        return value

    def create(self, validated_data):
        return Ticketer.create(
            org=self.org,
            user=self.acting_user,
            ticketer_type=validated_data.get("ticketer_type") or GenericType.slug,
            name=validated_data["name"],
            config=validated_data["config"],
        )


class OpenTicketSerializer(serializers.Serializer):
    project = serializers.UUIDField()
    ticketer = serializers.UUIDField()
    topic = serializers.UUIDField(required=False, allow_null=True)
    contact = serializers.UUIDField(required=False, allow_null=True)
    contact_urn = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    assignee = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    conversation_started_on = serializers.DateTimeField(required=False)
    protocol = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=64)

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

        if topic_uuid is not None:
            try:
                topic = Topic.objects.get(uuid=topic_uuid)
            except Topic.DoesNotExist:
                raise serializers.ValidationError({"topic": "topic not found"})
        elif ticketer.ticketer_type == WeniChatsType.slug:
            raise serializers.ValidationError({"topic": "This field is required."})
        else:
            topic = org.default_ticket_topic

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


class GetDepartmentsSerializer(serializers.ModelSerializer):
    ticketer_uuid = serializers.UUIDField(source="uuid")
    ticketer_name = serializers.CharField(source="name")
    type = serializers.SerializerMethodField()
    created_on = serializers.DateTimeField(default_timezone=pytz.UTC)
    topics = serializers.SerializerMethodField()

    def get_type(self, obj):
        return obj.ticketer_type

    def get_topics(self, obj):
        queues = TicketerQueue.objects.filter(ticketer=obj, is_active=True)
        return GetTicketerQueueSerializer(queues, many=True).data

    class Meta:
        model = Ticketer
        fields = ("ticketer_uuid", "ticketer_name", "type", "created_on", "topics")


class GetTicketerQueueSerializer(ReadSerializer):
    topic_name = serializers.CharField(source="name")
    topic_uuid = serializers.UUIDField(source="uuid")
    topic_purpose = serializers.CharField(source="queue_purpose", allow_null=True)

    class Meta:
        model = TicketerQueue
        fields = (
            "topic_name",
            "topic_uuid",
            "topic_purpose",
        )
