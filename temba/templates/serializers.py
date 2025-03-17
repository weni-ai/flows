from rest_framework import serializers


class TemplateSyncSerializer(serializers.Serializer):
    webhook = serializers.DictField(required=False)
    template_data = serializers.DictField(required=True)
    template_name = serializers.CharField(required=True)
