import re
import urllib.parse

import pytz
from rest_framework import serializers

from temba.api.v2 import fields
from temba.api.v2.serializers import MsgReadSerializer, ReadSerializer
from temba.msgs.models import Msg

# RFC 3986 unreserved and reserved characters. A CTA url is a URI, not an IRI.
URI_ALLOWED_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~:/?#[]@!$&'()*+,;=")
CTA_URL_PATTERN = re.compile(r"^https?://.+")
PERCENT_ENCODING = re.compile(r"%[0-9A-Fa-f]{2}")
CTA_URL_ERROR = "Enter a valid http(s) URL."
UNEXPECTED_FIELD_ERROR = "Unexpected field."
NULL_FIELD_ERROR = "This field may not be null."

MSG_COMPONENT_FIELDS = ("quick_replies", "list_message", "cta_message", "interaction_type", "header", "footer")


class InternalMsgReadSerializer(ReadSerializer):
    STATUSES = MsgReadSerializer.STATUSES
    VISIBILITIES = MsgReadSerializer.VISIBILITIES

    contact = fields.ContactField()
    urn = fields.URNField(source="contact_urn")
    channel = fields.ChannelField()
    direction = serializers.SerializerMethodField()
    created_on = serializers.DateTimeField(default_timezone=pytz.UTC)

    def get_direction(self, obj):
        return "in" if obj.direction == Msg.DIRECTION_IN else "out"

    class Meta:
        model = Msg
        fields = (
            "id",
            "contact",
            "urn",
            "channel",
            "direction",
            "text",
            "created_on",
        )


class StrictCharField(serializers.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("trim_whitespace", False)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class StrictIntegerField(serializers.IntegerField):
    def to_internal_value(self, data):
        # bool is a subclass of int, and IntegerField would accept numeric strings.
        if isinstance(data, bool) or isinstance(data, str) or not isinstance(data, (int, float)):
            self.fail("invalid")
        if isinstance(data, float) and not data.is_integer():
            self.fail("invalid")
        return super().to_internal_value(data)


class StrictChoiceField(serializers.ChoiceField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid_choice", input=data)
        return super().to_internal_value(data)


def validate_cta_url(value):
    if not CTA_URL_PATTERN.match(value):
        raise serializers.ValidationError(CTA_URL_ERROR)
    index = 0
    while index < len(value):
        if value[index] == "%":
            if PERCENT_ENCODING.match(value, index) is None:
                raise serializers.ValidationError(CTA_URL_ERROR)
            index += 3
            continue
        if value[index] not in URI_ALLOWED_CHARS:
            raise serializers.ValidationError(CTA_URL_ERROR)
        index += 1
    try:
        urllib.parse.urlsplit(value)
    except ValueError:
        raise serializers.ValidationError(CTA_URL_ERROR)


class ClosedSerializer(serializers.Serializer):
    """Reject keys the contract does not declare, and keep the field path in the error."""

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            return super().to_internal_value(data)

        errors = {}
        try:
            validated = super().to_internal_value(data)
        except serializers.ValidationError as exc:
            detail = exc.detail
            if isinstance(detail, dict):
                errors.update(detail)
            else:
                errors["non_field_errors"] = detail
            validated = None

        for key in data:
            if key not in self.fields:
                errors[key] = [UNEXPECTED_FIELD_ERROR]
        if errors:
            raise serializers.ValidationError(errors)
        return validated


class ListItemSerializer(ClosedSerializer):
    uuid = StrictCharField(min_length=1)
    title = StrictCharField(min_length=1)
    description = StrictCharField(required=False, allow_blank=True)


class ListMessageSerializer(ClosedSerializer):
    button_text = StrictCharField(min_length=1)
    list_items = serializers.ListField(child=ListItemSerializer(), allow_empty=False)
    item_count = StrictIntegerField(required=False, min_value=1)


class CtaMessageSerializer(ClosedSerializer):
    display_text = StrictCharField(min_length=1)
    url = StrictCharField(validators=[validate_cta_url])


class HeaderSerializer(ClosedSerializer):
    type = StrictChoiceField(choices=["text"], required=False)
    text = StrictCharField(required=False, allow_blank=True)


_OBJECT_SERIALIZERS = {
    "list_message": ListMessageSerializer,
    "cta_message": CtaMessageSerializer,
    "header": HeaderSerializer,
}


def _validate_component(name, value):
    serializer_class = _OBJECT_SERIALIZERS.get(name)
    if serializer_class is not None:
        serializer = serializer_class(data=value)
        if not serializer.is_valid():
            raise serializers.ValidationError(serializer.errors)
        return
    if name == "quick_replies":
        field = serializers.ListField(child=StrictCharField(min_length=1), allow_empty=False)
    elif name == "interaction_type":
        field = StrictChoiceField(choices=["list", "cta_url"])
    elif name == "footer":
        field = StrictCharField(allow_blank=True)
    else:
        raise KeyError(name)
    field.run_validation(value)


class StreamMsgField(serializers.DictField):
    """Validate the six component fields and return the original msg object.

    Keys other than the six stay in the dict, so existing callers keep whatever
    they already store in Msg.metadata. Values are not rewritten.
    """

    def to_internal_value(self, data):
        super().to_internal_value(data)
        errors = {}
        for name in MSG_COMPONENT_FIELDS:
            if name not in data:
                continue
            value = data[name]
            if value is None:
                errors[name] = [NULL_FIELD_ERROR]
                continue
            try:
                _validate_component(name, value)
            except serializers.ValidationError as exc:
                errors[name] = exc.detail
        if errors:
            raise serializers.ValidationError(errors)
        return data


class MsgStreamSerializer(serializers.Serializer):
    project_uuid = serializers.UUIDField()
    direction = serializers.ChoiceField(choices=("in", "out", "I", "O"), required=False, default="out")
    contact_uuid = serializers.UUIDField(required=False)
    urns = serializers.ListField(child=serializers.CharField(), required=False)
    channel_uuid = serializers.UUIDField(required=False)
    template = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    message = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    msg = StreamMsgField(required=False)
    attachments = serializers.ListField(child=serializers.URLField(), required=False)
    created_on = serializers.DateTimeField(required=False)
    sent_on = serializers.DateTimeField(required=False)
    status = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    visibility = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    labels = serializers.ListField(child=serializers.UUIDField(), required=False)

    def validate(self, data):
        # require at least one contact identifier
        if not data.get("contact_uuid") and not data.get("urns"):
            raise serializers.ValidationError("Must provide either contact_uuid or urns")

        # require some content
        if not (data.get("text") or data.get("message") or data.get("attachments") or data.get("msg")):
            raise serializers.ValidationError("Must provide text, message, attachments or msg")

        return data
