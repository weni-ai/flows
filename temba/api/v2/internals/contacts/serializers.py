from rest_framework import serializers

from django.conf import settings
from django.contrib.auth import get_user_model

from temba.contacts.models import ContactField, ContactURN
from temba.orgs.models import Org

User = get_user_model()


class InternalContactSerializer(serializers.Serializer):
    contacts = serializers.ListSerializer(child=serializers.UUIDField(), min_length=1, max_length=100)


class InternalContactFieldsValuesSerializer(serializers.Serializer):
    project = serializers.UUIDField()
    contact_fields = serializers.DictField(child=serializers.CharField(allow_null=True, allow_blank=True))
    contact_urn = serializers.CharField(required=True)

    def validate(self, data):
        project_uuid = data.get("project")
        contact_urn = data.get("contact_urn")

        try:
            org = Org.objects.get(proj_uuid=project_uuid)

        except Org.DoesNotExist:
            raise serializers.ValidationError({"project": "Project not found"})

        contact = ContactURN.lookup(org, contact_urn)
        if not contact:
            raise serializers.ValidationError({"contact_urn": "Contact URN not found"})

        return data

    def validate_contact_fields(self, value):
        if not value:
            raise serializers.ValidationError("contact_fields must not be an empty dictionary")
        return value

    def update(self, instance, validated_data):
        project_uuid = validated_data.get("project")
        contact_urn = validated_data.get("contact_urn")
        contact_fields = validated_data.get("contact_fields", {})
        user = User.objects.get(email=settings.INTERNAL_USER_EMAIL)

        org = Org.objects.get(proj_uuid=project_uuid)
        urn = ContactURN.lookup(org, contact_urn)
        contact = urn.contact

        fields_to_update = {}
        for key, value in contact_fields.items():
            contact_field = ContactField.all_fields.filter(key=key, org=org).first()
            if contact_field:
                fields_to_update[contact_field] = value

        mods = contact.update_fields(fields_to_update)
        contact.modify(user, mods)

        return instance


class ContactWithMessageSerializer(serializers.Serializer):
    contact_id = serializers.IntegerField()
    msg_text = serializers.CharField()
    msg_created_on = serializers.DateTimeField()


class ContactWithMessagesListSerializer(serializers.Serializer):
    contact_id = serializers.IntegerField()
    messages = ContactWithMessageSerializer(many=True)
