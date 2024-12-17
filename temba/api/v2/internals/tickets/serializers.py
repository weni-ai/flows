from rest_framework import serializers


class TicketAssigneeSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    email = serializers.EmailField()
