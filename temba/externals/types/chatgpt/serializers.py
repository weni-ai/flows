from rest_framework import serializers

from temba.externals.models import ExternalService

AI_MODELS = [
    ("gpt-3.5-turbo-16k", "gpt-3.5-turbo-16k"),
    ("gpt-3.5-turbo", "gpt-3.5-turbo"),
    ("gpt-4", "gpt-4"),
]


class ChatGPTSerializer(serializers.ModelSerializer):
    name = serializers.CharField()
    api_key = serializers.CharField()
    ai_model = serializers.ChoiceField(choices=AI_MODELS)

    class Meta:
        model = ExternalService
        fields = ("name", "api_key", "ai_model")

    def create(self, validated_data):
        type = validated_data.pop("type")

        config = {
            type.CONFIG_API_KEY: validated_data.pop("api_key"),
            type.CONFIG_AI_MODEL: validated_data.pop("ai_model"),
        }

        return ExternalService.objects.create(
            external_service_type=type.slug, name=validated_data.pop("name"), config=config, **validated_data
        )
