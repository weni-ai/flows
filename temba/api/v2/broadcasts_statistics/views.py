from rest_framework.response import Response
from rest_framework.reverse import reverse

from django.db.models import Prefetch

from temba.api.v2.views_base import BaseAPIView, DefaultLimitOffsetPagination
from temba.msgs.models import Broadcast, BroadcastStatistics
from temba.templates.models import Template

from .serializers import BroadcastsStatisticsQuerySerializer, BroadcastStatisticsReadSerializer


class BroadcastsStatisticsEndpoint(BaseAPIView):
    """
    This endpoint allows you to list the bulk send broadcasts in your workspace along with their delivery statistics.

    ## Listing Broadcasts Statistics

    A `GET` returns the bulk send broadcasts of your workspace, listing the most recent first.

     * **id** - the id of the broadcast (int), filterable as `id`.
     * **name** - the name of the broadcast (string), filterable as `name` (case-insensitive contains).
     * **created_by** - the email of the user who created the broadcast (string or null).
     * **created_on** - when the broadcast was created (datetime), filterable as `start_date` and `end_date`.
     * **modified_on** - when the broadcast was last modified (datetime).
     * **text** - the message text of the broadcast (object).
     * **media** - the media of the broadcast (object).
     * **broadcast_type** - the type of the broadcast (string).
     * **groups** - the groups that received the broadcast (array of objects).
     * **status** - the status of the broadcast (string).
     * **statistics** - the delivery statistics of the broadcast (object).
     * **template** - the template used by the broadcast (object or null).

    Results are paginated with the `limit` (default 10, maximum 100) and `offset` parameters.

    `start_date` and `end_date` accept ISO 8601 dates or datetimes, ex: `2026-10-01` or `2026-10-01T12:00:00Z`.

    Example:

        GET /api/v2/broadcasts_statistics.json?start_date=2026-10-01&limit=10

    Response is a list of broadcasts with their statistics:

        {
            "count": 1,
            "next": null,
            "previous": null,
            "results": [
                {
                    "id": 123456,
                    "name": "Black Friday",
                    "created_by": "user@example.com",
                    "created_on": "2026-10-02T17:28:12.123456Z",
                    "modified_on": "2026-10-02T17:30:00.000000Z",
                    "text": {"eng": "Hello @contact.name"},
                    "media": {},
                    "broadcast_type": "W",
                    "groups": [{"uuid": "5a4eb79e-1b1f-4ae3-8700-09384cca385f", "name": "Customers"}],
                    "status": "S",
                    "statistics": {
                        "processed": 100,
                        "sent": 98,
                        "delivered": 95,
                        "failed": 2,
                        "contact_count": 100,
                        "read": 60,
                        "cost": 12.5,
                        "currency": "BRL",
                        "template_price": 0.125,
                        "created_on": "2026-10-02T17:28:13.000000Z",
                        "modified_on": "2026-10-02T18:00:00.000000Z"
                    },
                    "template": {"id": 42, "name": "black_friday"}
                }
            ]
        }
    """

    permission = "msgs.broadcast_statistics_api"
    model = Broadcast
    serializer_class = BroadcastStatisticsReadSerializer
    pagination_class = DefaultLimitOffsetPagination

    def get(self, request, *args, **kwargs):
        # browsing the endpoint docs shouldn't trigger a query
        if not kwargs.get("format"):
            return Response([])

        query = BroadcastsStatisticsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        queryset = self.apply_filters(self.get_queryset(), query.validated_data)
        page = self.paginate_queryset(queryset)

        context = self.get_serializer_context()
        context["templates_by_id"] = self.get_templates_by_id(page, using=queryset.db)

        serializer = self.get_serializer(page, many=True, context=context)
        return self.get_paginated_response(serializer.data)

    def apply_filters(self, queryset, filters: dict):
        queryset = queryset.filter(is_bulk_send=True)

        if filters.get("start_date"):
            queryset = queryset.filter(created_on__gte=filters["start_date"])
        if filters.get("end_date"):
            queryset = queryset.filter(created_on__lte=filters["end_date"])
        if filters.get("name"):
            queryset = queryset.filter(name__icontains=filters["name"])
        if filters.get("id") is not None:
            queryset = queryset.filter(id=filters["id"])

        return (
            queryset.select_related("created_by")
            .prefetch_related("groups", Prefetch("statistics", queryset=BroadcastStatistics.objects.order_by("pk")))
            .order_by("-created_on", "-id")
        )

    def get_templates_by_id(self, broadcasts, using: str) -> dict:
        template_ids = {b.template_id for b in broadcasts if b.template_id}
        if not template_ids:
            return {}

        templates = Template.objects.using(using).filter(org=self.get_org(), id__in=template_ids)
        return {t.id: t for t in templates}

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Broadcasts Statistics",
            "url": reverse("api.v2.broadcasts_statistics"),
            "slug": "broadcasts-statistics-list",
            "params": [
                {"name": "id", "required": False, "help": "A broadcast ID to filter by, ex: 123456"},
                {"name": "name", "required": False, "help": "A broadcast name to filter by (contains), ex: Black"},
                {
                    "name": "start_date",
                    "required": False,
                    "help": "Only return broadcasts created on or after this date, ex: 2026-10-01T00:00:00Z",
                },
                {
                    "name": "end_date",
                    "required": False,
                    "help": "Only return broadcasts created on or before this date, ex: 2026-10-31T23:59:59Z",
                },
                {
                    "name": "limit",
                    "required": False,
                    "help": "The number of broadcasts to return, default 10, max 100",
                },
                {"name": "offset", "required": False, "help": "The number of broadcasts to skip, default 0"},
            ],
        }
