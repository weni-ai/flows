from rest_framework import relations, serializers
from weni.serializers import fields as weni_serializers

from django.contrib.auth import get_user_model

from temba.api.v2 import fields
from temba.api.v2.serializers import WriteSerializer, normalize_extra
from temba.flows.models import Flow, FlowStart

User = get_user_model()


class FlowUUIDRelatedField(relations.SlugRelatedField):
    def __init__(self, **kwargs):
        super().__init__(slug_field="uuid", queryset=Flow.objects.all(), **kwargs)


class UserAndFlowSerializer(serializers.Serializer):
    user = weni_serializers.UserEmailRelatedField(required=True, write_only=True)
    flow = FlowUUIDRelatedField(required=True, write_only=True)


class FlowStartSerializer(WriteSerializer):
    urns = fields.URNListField(required=True)
    restart_participants = serializers.BooleanField(required=False)
    exclude_active = serializers.BooleanField(required=False)
    extra = serializers.JSONField(required=False)
    params = serializers.JSONField(required=False)

    def validate_extra(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be a valid JSON object")

        return normalize_extra(value)

    def validate_params(self, value):
        return self.validate_extra(value)

    def save(self):
        urns = self.validated_data.get("urns", [])
        restart_participants = self.validated_data.get("restart_participants", True)
        exclude_active = self.validated_data.get("exclude_active", False)
        extra = self.validated_data.get("extra")

        params = self.validated_data.get("params")
        if params:
            extra = params

        flow_start = FlowStart.create(
            self.context["flow"],
            self.context["user"],
            start_type=FlowStart.TYPE_API,
            restart_participants=restart_participants,
            include_active=not exclude_active,
            urns=urns,
            extra=extra,
        )

        flow_start.async_start()

        return flow_start


class FlowImportSerializer(serializers.Serializer):
    project_uuid = serializers.CharField(required=True)
    definition = serializers.JSONField(required=True)
