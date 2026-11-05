from rest_framework import serializers
from rest_framework.settings import ISO_8601

from temba.api.v2.internals.broadcasts.serializers import BroadcastWithStatisticsSerializer

DATE_INPUT_FORMATS = [ISO_8601, "%Y-%m-%d"]


class BroadcastsStatisticsQuerySerializer(serializers.Serializer):
    start_date = serializers.DateTimeField(required=False, allow_null=True, input_formats=DATE_INPUT_FORMATS)
    end_date = serializers.DateTimeField(required=False, allow_null=True, input_formats=DATE_INPUT_FORMATS)
    name = serializers.CharField(required=False, allow_blank=True)
    id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, data):
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError({"start_date": "Must be before or equal to end_date."})
        return data


class BroadcastStatisticsReadSerializer(BroadcastWithStatisticsSerializer):
    """
    Same representation as the internal endpoint, but reads statistics from a prefetch and templates from a map
    built once per page, so the number of queries does not grow with the page size.
    """

    def get_statistics(self, obj):
        # Prefetch is required (BroadcastsStatisticsEndpoint.apply_filters). ``.first()``
        # would always hit the database and reintroduce N+1.
        statistics = list(obj.statistics.all())
        stat = statistics[0] if statistics else None
        return {
            "processed": stat.processed if stat else 0,
            "sent": stat.sent if stat else 0,
            "delivered": stat.delivered if stat else 0,
            "failed": stat.failed if stat else 0,
            "contact_count": stat.contact_count if stat else 0,
            "read": stat.read if stat else 0,
            "cost": stat.cost if stat else 0,
            "currency": stat.currency if stat else "BRL",
            "template_price": stat.template_price if stat else 0,
            "created_on": stat.created_on if stat else None,
            "modified_on": stat.modified_on if stat else None,
        }

    def get_template(self, obj):
        if not obj.template_id:
            return None
        template = self.context["templates_by_id"].get(obj.template_id)
        if not template:
            return None
        return {"id": template.id, "name": template.name}
