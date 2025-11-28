from rest_framework import serializers

from django.conf import settings
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404

from temba.channels.models import Channel
from temba.contacts.models import ContactField, ContactURN
from temba.orgs.models import Org

User = get_user_model()


class InternalContactSerializer(serializers.Serializer):
    contacts = serializers.ListSerializer(child=serializers.UUIDField(), min_length=1, max_length=100)


class InternalContactFieldsValuesSerializer(serializers.Serializer):
    project_uuid = serializers.UUIDField(required=False)
    channel_uuid = serializers.UUIDField(required=False)
    contact_fields = serializers.DictField(child=serializers.CharField(allow_null=True, allow_blank=True))
    contact_urn = serializers.CharField(required=True)

    def validate(self, data):
        project_uuid = data.get("project_uuid")
        channel_uuid = data.get("channel_uuid")
        contact_urn = data.get("contact_urn")

        if project_uuid:
            org = get_object_or_404(Org, proj_uuid=project_uuid)

        elif channel_uuid:
            channel = get_object_or_404(Channel, uuid=channel_uuid)
            org = channel.org
            if not org:
                raise serializers.ValidationError({"channel": "Channel is not associated with a project"})

        else:
            raise serializers.ValidationError("At least either a channel or a project is required")

        data["org"] = org

        contact = ContactURN.lookup(org, contact_urn)
        if not contact:
            raise serializers.ValidationError({"contact_urn": "Contact URN not found"})

        return data

    def validate_contact_fields(self, value):
        if not value:
            raise serializers.ValidationError("contact_fields must not be an empty dictionary")
        return value

    def update(self, instance, validated_data):
        org = validated_data.get("org")
        contact_urn = validated_data.get("contact_urn")
        contact_fields = validated_data.get("contact_fields", {})
        user = User.objects.get(email=settings.INTERNAL_USER_EMAIL)

        urn = ContactURN.lookup(org, contact_urn)
        contact = urn.contact

        mods = []

        name = contact_fields.pop("name", None)
        language = contact_fields.pop("language", None)
        if name is not None or language is not None:
            mods.extend(contact.update(name=name, language=language))

        fields_to_update = {}
        for key, value in contact_fields.items():
            contact_field = ContactField.all_fields.filter(key=key, org=org).first()
            if contact_field:
                fields_to_update[contact_field] = value

        if fields_to_update:
            mods.extend(contact.update_fields(fields_to_update))

        if mods:
            contact.modify(user, mods)

        return instance


class ContactWithMessageSerializer(serializers.Serializer):
    contact_id = serializers.IntegerField()
    msg_text = serializers.CharField()
    msg_created_on = serializers.DateTimeField()


class ContactWithMessagesListSerializer(serializers.Serializer):
    contact_id = serializers.IntegerField()
    messages = ContactWithMessageSerializer(many=True)
