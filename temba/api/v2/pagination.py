from rest_framework.pagination import BasePagination, CursorPagination, LimitOffsetPagination


class FlowsCursorPagination(CursorPagination):
    page_size_query_param = "limit"
    max_page_size = 250
    offset_cutoff = 1000000

    def get_ordering(self, request, queryset, view):
        return view.get_ordering()


class FlowsLimitOffsetPagination(LimitOffsetPagination):
    default_limit = 250
    max_limit = 250


class FlowsPagination(BasePagination):
    """
    Uses cursor pagination by default, switching to limit/offset pagination when an offset param is provided
    """

    def __init__(self):
        self.paginator = FlowsCursorPagination()

    @property
    def display_page_controls(self):
        return getattr(self.paginator, "display_page_controls", False)

    def paginate_queryset(self, queryset, request, view=None):
        if "offset" in request.query_params:
            self.paginator = FlowsLimitOffsetPagination()

        return self.paginator.paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        return self.paginator.get_paginated_response(data)

    def get_paginated_response_schema(self, schema):
        return self.paginator.get_paginated_response_schema(schema)

    def to_html(self):
        return self.paginator.to_html()

    def get_schema_fields(self, view):
        return self.paginator.get_schema_fields(view)

    def get_schema_operation_parameters(self, view):
        return self.paginator.get_schema_operation_parameters(view)
