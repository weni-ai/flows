import iso8601
from rest_framework import serializers

from temba.conversion_events.models import CtwaReferralSource


class ListCtwaReferralSourceQuerySerializer(serializers.Serializer):
    project_uuid = serializers.UUIDField(required=True)
    source_type = serializers.ChoiceField(
        choices=CtwaReferralSource.SOURCE_TYPE_CHOICES, required=False
    )
    after = serializers.CharField(required=False, allow_blank=True)
    before = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        errors = {}
        after_date = self._parse_iso_date(
            attrs.get("after"), "after", "Invalid after, expected ISO-8601 date", errors
        )
        before_date = self._parse_iso_date(
            attrs.get("before"), "before", "Invalid before, expected ISO-8601 date", errors
        )

        if after_date and before_date and after_date > before_date:
            errors["non_field_errors"] = "after must be <= before"

        if errors:
            raise serializers.ValidationError(errors)

        attrs["after"] = after_date
        attrs["before"] = before_date
        return attrs

    def _parse_iso_date(self, value, field_name, error_message, errors):
        if not value:
            return None
        try:
            return iso8601.parse_date(value).date()
        except Exception:
            errors[field_name] = error_message
            return None


class CtwaReferralSourceSerializer(serializers.ModelSerializer):
    project_uuid = serializers.UUIDField(source="org.proj_uuid", read_only=True)

    class Meta:
        model = CtwaReferralSource
        fields = (
            "id",
            "org",
            "project_uuid",
            "source_id",
            "source_type",
            "source_url",
            "headline",
            "body",
            "first_seen_at",
            "last_seen_at",
            "created_at",
            "updated_at",
        )
