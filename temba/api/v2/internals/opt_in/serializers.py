from rest_framework import serializers

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email

from temba.contacts.usecases.opt_in import _normalize_whatsapp
from temba.contacts.validators import clean_contact_name


class OptInContactCreateSerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True, trim_whitespace=False)
    whatsapp = serializers.CharField()
    email = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate_name(self, value):
        try:
            return clean_contact_name(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)

    def validate_whatsapp(self, value):
        try:
            return _normalize_whatsapp(value)
        except (ValueError, DjangoValidationError) as exc:
            messages = getattr(exc, "messages", None) or ["Enter a valid WhatsApp number."]
            raise serializers.ValidationError(messages)

    def validate_email(self, value):
        if not value:
            return None
        try:
            validate_email(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value


class OptInIdentifierSerializer(serializers.Serializer):
    email = serializers.CharField()

    def validate_email(self, value):
        try:
            validate_email(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value
