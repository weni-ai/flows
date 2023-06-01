from rest_framework import serializers
from temba.externals.models import ExternalService


class ChatGPTSerializer(serializers.ModelSerializer):
    name = serializers.CharField()
    api_key = serializers.CharField()

    class Meta:
        model = ExternalService
        fields = ("name", "api_key", "ai_model", "rules", "knowledge_base")

    def create(self, validated_data):
        type_ = validated_data.pop("type")

        config = {
            type.CONFIG_APP_KEY: validated_data.pop("api_key"),
            type.CONFIG_AI_MODEL: validated_data.pop("ai_model"),
            type.CONFIG_RULES: validated_data.pop("rules"),
            type.CONFIG_KNOWLEDGE_BASE: validated_data.pop("knowledge_base"),
        }

        return ExternalService.objects.create(
            external_service_type=type_.slug,
            name=validated_data.pop("name"),
            config=config,
            **validated_data
        )
