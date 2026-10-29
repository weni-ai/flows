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

    def load_statistics(self, obj):
        """
        First statistics row, or None.

        Callers MUST prefetch ``statistics`` (see BroadcastsStatisticsEndpoint.apply_filters).
        ``.first()`` would always hit the database and reintroduce N+1; this only reads
        the prefetched cache.
        """
        statistics = list(obj.statistics.all())
        return statistics[0] if statistics else None

    def load_template(self, template_id):
        return self.context["templates_by_id"].get(template_id)
