import logging

from rest_framework import serializers

from django.conf import settings
from django.contrib.auth import get_user_model

from temba.api.v2.internals.helpers import get_object_or_404
from temba.channels.models import Channel
from temba.contacts.models import Contact, ContactField, ContactURN
from temba.orgs.models import Org

User = get_user_model()

logger = logging.getLogger(__name__)

# Keys that update_contacts_fields may auto-create as text user fields when missing (org under field limit).
FALLBACK_AUTO_CREATE_CONTACT_FIELD_KEYS = frozenset({"segment", "orderform"})
FALLBACK_AUTO_CREATE_CONTACT_FIELD_LABELS = {
    "segment": "segment",
    "orderform": "orderform",
}


def _resolve_contact_field_for_update(org, user, raw_key):
    """
    Resolve a ContactField for PATCH update_contacts_fields. Unknown keys are ignored unless they are
    segment or orderform: then we create a text field if missing and the org is under its field limit.
    """
    canonical = raw_key.lower()
    field = ContactField.all_fields.filter(org=org, key=raw_key).first()
    if field:
        return field
    if canonical != raw_key:
        field = ContactField.all_fields.filter(org=org, key=canonical).first()
        if field:
            return field
    if canonical not in FALLBACK_AUTO_CREATE_CONTACT_FIELD_KEYS:
        return None
    limit = org.get_limit(Org.LIMIT_FIELDS)
    if ContactField.user_fields.count_active_for_org(org=org) >= limit:
        logger.warning(
            "Skipping auto-create of contact field %r for org %s: field limit reached",
            canonical,
            org.id,
        )
        return None
    label = FALLBACK_AUTO_CREATE_CONTACT_FIELD_LABELS[canonical]
    return ContactField.get_or_create(org, user, canonical, label=label, value_type=ContactField.TYPE_TEXT)


class InternalContactSerializer(serializers.Serializer):
    contacts = serializers.ListSerializer(child=serializers.UUIDField(), min_length=1, max_length=100)


class InternalContactFieldsValuesSerializer(serializers.Serializer):
    project = serializers.UUIDField(required=False)
    channel_uuid = serializers.UUIDField(required=False)
    contact_fields = serializers.DictField(child=serializers.CharField(allow_null=True, allow_blank=True))
    contact_urn = serializers.CharField(required=True)

    def validate(self, data):
        project_uuid = data.get("project") or self.context.get("project_uuid")
        channel_uuid = data.get("channel_uuid") or self.context.get("channel_uuid")
        contact_urn = data.get("contact_urn")

        if project_uuid:
            self.org = get_object_or_404(Org, field_error_name="project", proj_uuid=project_uuid)

        elif channel_uuid:
            channel = get_object_or_404(Channel, field_error_name="channel", uuid=channel_uuid)
            self.org = channel.org
            if not self.org:
                raise serializers.ValidationError({"channel": "Channel is not associated with a project"})

        else:
            raise serializers.ValidationError("At least either a channel or a project is required")

        data["org"] = self.org

        contact = ContactURN.lookup(self.org, contact_urn)
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
            contact_field = _resolve_contact_field_for_update(org, user, key)
            if contact_field:
                fields_to_update[contact_field] = value

        if fields_to_update:
            mods.extend(contact.update_fields(fields_to_update))

        if mods:
            contact.modify(user, mods)

        return instance


class CleanContactFieldsSerializer(serializers.Serializer):
    project_uuid = serializers.UUIDField(required=False)
    project = serializers.UUIDField(required=False)
    contact_uuid = serializers.UUIDField(required=False)
    contact_urn = serializers.CharField(required=False, allow_blank=False)

    def validate(self, data):
        contact_uuid = data.get("contact_uuid")
        contact_urn = data.get("contact_urn")
        org = self.context["org"]

        if not contact_uuid and not contact_urn:
            raise serializers.ValidationError("Either contact_uuid or contact_urn is required")

        if contact_uuid and contact_urn:
            raise serializers.ValidationError("Provide only one of contact_uuid or contact_urn")

        if contact_uuid:
            contact = Contact.objects.filter(org=org, is_active=True, uuid=contact_uuid).first()
            if not contact:
                raise serializers.ValidationError({"contact_uuid": "Contact not found"})
        else:
            contact = Contact.from_urn(org, contact_urn)
            if not contact:
                raise serializers.ValidationError({"contact_urn": "Contact URN not found"})

        data["contact"] = contact
        return data


class ContactWithMessageSerializer(serializers.Serializer):
    contact_id = serializers.IntegerField()
    msg_text = serializers.CharField()
    msg_created_on = serializers.DateTimeField()


class ContactWithMessagesListSerializer(serializers.Serializer):
    contact_id = serializers.IntegerField()
    messages = ContactWithMessageSerializer(many=True)
