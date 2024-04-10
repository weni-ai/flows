from rest_framework import serializers


class TemplateSyncSerializer(serializers.Serializer):
    webhook = serializers.DictField()
    template_data = serializers.ListField()
    template_name = serializers.CharField(required=True)
