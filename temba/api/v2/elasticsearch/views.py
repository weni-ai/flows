from elasticsearch import Elasticsearch
from elasticsearch_dsl import Q, Search
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.clients.base import BaseInternalClient
from weni.internal.models import Project

from django.conf import settings
from django.urls import reverse


class ContactsElasticSearchEndpoint(APIView, BaseInternalClient):
    """
    This endpoint allows you to list the intelligences of the project.

    ## Listing Intelligences

    A `GET` returns the intelligences for your organization with the following fields.

      * **intelligence_name** - the name of the intelligences (string)
      * **content_bases** - the content bases of a specific intelligence (list)
      * **uuid** - the uuid of content_base (string)
      * **content_base_name** - the name of content base (string)

    Example:

        GET /api/v2/intelligences.json

    Response is a list of the intelligences on your account

        {
            {
                "intelligence_name": "name",
                "content_bases": [
                    {"uuid": <uuid>, "content_base_name": "1234"},
                    {"uuid": <uuid>, "content_base_name": "4321"}
                ]
            },
            {
                "intelligence_name": "name 2",
                "content_bases": [
                    {"uuid": <uuid>, "content_base_name": "12345"},
                    {"uuid": <uuid>, "content_base_name": "43215"}
                ]
            },
            ...
        }
    """

    def get(self, request, *args, **kwargs):
        params = request.query_params
        project_uuid = params.get("project_uuid")

        org_id = Project.objects.get(project_uuid=project_uuid).org.id
        name = params.get("name")
        number = params.get("number", "")

        base_url = settings.ELASTICSEARCH_URL
        client = Elasticsearch(f"{base_url}", timeout=settings.ELASTICSEARCH_TIMEOUT_REQUEST)
        filte = [Q("match", org_id=org_id)]
        index = "contacts"
        if name:
            filte.append(Q("match_phrase", name=name))
        if number:
            filte.append(
                Q(
                    "nested",
                    path="urns",
                    query=Q(
                        "bool",
                        must=[
                            Q(
                                "match_phrase",
                                **{"urns.path": number},
                            )
                        ],
                    ),
                ),
            )
        qs = Q("bool", must=filte)
        contacts = Search(using=client, index=index).query(qs)
        response = list(contacts.scan())

        page_number = int(params.get("page_number", 1))
        page_size = int(params.get("page_size", 10))
        start = (page_number - 1) * page_size
        end = page_number * page_size
        results = [hit.to_dict() for hit in response[start:end]]
        return Response(results, status=status.HTTP_200_OK)

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List ElasticSearch contacts",
            "url": reverse("api.v2.contacts_elastic"),
            "slug": "contacts-elastic-list",
            "params": [],
        }
