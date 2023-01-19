from rest_framework import serializers
from django.utils.translation import ugettext_lazy as _

from temba.externals.models import ExternalService


class OmieSerializer(serializers.ModelSerializer):
    name = serializers.CharField()
    app_key = serializers.CharField()
    app_secret = serializers.CharField()

    class Meta:
        model = ExternalService
        fields = ("name", "app_key", "app_secret")

    def create(self, validated_data):
        type_ = validated_data.pop("type")

        config = {
            type_.CONFIG_APP_KEY: validated_data.pop("app_key"),
            type_.CONFIG_APP_SECRET: validated_data.pop("app_secret"),
        }

        return ExternalService.objects.create(
            external_service_type=type_.slug, name=validated_data.pop("name"), config=config, **validated_data
        )
