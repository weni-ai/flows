import ast

import pytz
from rest_framework import serializers

from temba.contacts.models import Contact


class GetContactsSerializer(serializers.ModelSerializer):
    urns = serializers.SerializerMethodField()
    created_on = serializers.DateTimeField(default_timezone=pytz.UTC)
    modified_on = serializers.DateTimeField(default_timezone=pytz.UTC)
    last_seen_on = serializers.DateTimeField(default_timezone=pytz.UTC)
    groups = serializers.SerializerMethodField()

    def get_urns(self, obj):
        return [urn.api_urn() for urn in obj.get_urns()]

    def get_groups(self, obj):
        if not obj.is_active:
            return []

        groups = obj.prefetched_user_groups if hasattr(obj, "prefetched_user_groups") else obj.user_groups.all()
        return [{"uuid": g.uuid, "name": g.name} for g in groups]

    class Meta:
        model = Contact
        fields = (
            "id",
            "uuid",
            "name",
            "org_id",
            "urns",
            "groups",
            "created_on",
            "modified_on",
            "last_seen_on",
        )


class ContactsElasticSerializer(serializers.ModelSerializer):
    urns = serializers.ListField(child=serializers.CharField(), required=False)
    groups = serializers.ListField(child=serializers.CharField(), required=False)
    created_on = serializers.DateTimeField(default_timezone=pytz.UTC)
    modified_on = serializers.DateTimeField(default_timezone=pytz.UTC)
    last_seen_on = serializers.DateTimeField(default_timezone=pytz.UTC)

    def get_urns(self, instance):
        urns = instance.get("urns", [])
        urns_list = []
        for urn_str in urns:
            urn_dict = ast.literal_eval(urn_str)
            urns_list.append(urn_dict)
        return urns_list

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["urns"] = self.get_urns(instance)
        return data

    class Meta:
        model = Contact
        fields = (
            "id",
            "uuid",
            "name",
            "org_id",
            "urns",
            "groups",
            "created_on",
            "modified_on",
            "last_seen_on",
        )
