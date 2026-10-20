from math import ceil
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from elasticsearch import Elasticsearch
from elasticsearch_dsl import Q, Search

from django.conf import settings

from temba.utils.whatsapp.ninth_digit import get_number_search_terms

URNS_PATH = "urns.path"
URNS_SCHEME = "urns.scheme"
CONTACTS_INDEX = "contacts"


def _append_query_params(base_url, **params):
    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items()})
    return urlunparse(parsed._replace(query=urlencode(query)))


def get_pagination_links(base_url, page_number, total_pages, page_size):
    links = {}
    if page_number < total_pages:
        links["next"] = _append_query_params(
            base_url,
            page_number=page_number + 1,
            page_size=page_size,
        )
    if page_number > 1:
        links["previous"] = _append_query_params(
            base_url,
            page_number=page_number - 1,
            page_size=page_size,
        )
    return links


class BuildContactNumberQueryUseCase:
    """
    Builds the nested Elasticsearch query for contact number search.

    The literal number matches any URN scheme, while the no-9 variant is
    restricted to whatsapp URNs (stripping the 9 is a WhatsApp-only rule).
    Returns None when the input has no digits after sanitization.
    """

    def execute(self, number: str):
        terms = get_number_search_terms(number)
        number_queries = []

        if terms["literal"]:
            number_queries.append(Q("match_phrase", **{URNS_PATH: terms["literal"]}))
        if terms["whatsapp_variant"]:
            number_queries.append(
                Q(
                    "bool",
                    must=[
                        Q("match_phrase", **{URNS_PATH: terms["whatsapp_variant"]}),
                        Q("term", **{URNS_SCHEME: "whatsapp"}),
                    ],
                )
            )
        if not number_queries:
            return None

        return Q(
            "nested",
            path="urns",
            query=Q(
                "bool",
                should=number_queries,
                minimum_should_match=1,
                must=[Q("exists", field=URNS_PATH)],
            ),
        )


class SearchContactsElasticUseCase:
    def __init__(self, client=None, number_query_usecase=None):
        self._client = client
        self._number_query_usecase = number_query_usecase or BuildContactNumberQueryUseCase()

    def execute(self, org_id, name=None, number=None, page_number=1, page_size=10, base_url=""):
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        if page_number < 1:
            raise ValueError("page_number must be at least 1")

        client = self._client or self._create_client()
        filters = self._build_filters(org_id, name, number)
        qs = Q("bool", must=filters)

        from_index = (page_number - 1) * page_size
        search = Search(using=client, index=CONTACTS_INDEX).query(qs)
        search = search[from_index : from_index + page_size]
        response = search.execute()

        results = [hit.to_dict() for hit in response]
        total_results = response.hits.total.value
        total_pages = ceil(total_results / page_size)

        return {
            "results": results,
            "pagination": {
                "page_number": page_number,
                "page_size": page_size,
                "total_pages": total_pages,
                "links": get_pagination_links(base_url, page_number, total_pages, page_size),
            },
        }

    def _build_filters(self, org_id, name, number):
        filters = [Q("match", org_id=org_id)]
        if name:
            filters.append(Q("match_phrase", name=name))
            filters.append(Q("exists", field="name"))
        if number:
            number_query = self._number_query_usecase.execute(number)
            if number_query is not None:
                filters.append(number_query)
        return filters

    def _create_client(self):
        base_url = settings.ELASTICSEARCH_URL
        timeout = int(settings.ELASTICSEARCH_TIMEOUT_REQUEST)
        return Elasticsearch(f"{base_url}", timeout=timeout)
