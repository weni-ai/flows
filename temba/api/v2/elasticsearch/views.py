from elasticsearch import Elasticsearch
from elasticsearch_dsl import Q, Search
from mozilla_django_oidc.contrib.drf import OIDCAuthentication
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.models import Project

from django.conf import settings
from django.urls import reverse

from temba.api.v2.elasticsearch.serializers import GetContactsSerializer
from temba.contacts.models import Contact


def get_pagination_links(base_url, page_number, total_pages):
    links = {}
    if page_number < total_pages:
        links["next"] = f"{base_url}?page_number={page_number + 1}"
    if page_number > 1:
        links["previous"] = f"{base_url}?page_number={page_number - 1}"
    return links


class ContactsElasticSearchEndpoint(APIView):
    """
    This endpoint allows you to list the contacts of the project by elasticsearch.

    Example:

        GET /api/v2/contacts_elastic.json

    """

    authentication_classes = [OIDCAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = None
    renderer_classes = [JSONRenderer]
    throttle_classes = []

    def get(self, request, *args, **kwargs):  # pragma: no cover
        params = request.query_params
        project_uuid = params.get("project_uuid")

        project = Project.objects.get(project_uuid=project_uuid)
        if not project.get_users().filter(id=request.user.id).exists():
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        org_id = project.org.id

        name = params.get("name")
        number = params.get("number", "")

        if name or number:
            base_url = settings.ELASTICSEARCH_URL
            client = Elasticsearch(f"{base_url}", timeout=settings.ELASTICSEARCH_TIMEOUT_REQUEST)
            filte = [Q("match", org_id=org_id)]
            index = "contacts"
            if name:
                filte.append(Q("match_phrase", name=name))
                filte.append(Q("exists", field="name"))
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
                                ),
                                Q("exists", field="urns.path"),
                            ],
                        ),
                    ),
                )
            qs = Q("bool", must=filte)

            page_number = int(params.get("page_number", 1))
            page_size = int(params.get("page_size", 10))

            contacts = (
                Search(using=client, index=index).query(qs).params(size=page_size, from_=(page_number - 1) * page_size)
            )
            response = list(contacts.scan())

            results = [hit.to_dict() for hit in response]

            total_pages = (contacts.count() + page_size - 1) // page_size

            pagination_links = get_pagination_links(base_url, page_number, total_pages)

            data = {
                "results": results,
                "pagination": {
                    "page_number": page_number,
                    "page_size": page_size,
                    "total_pages": total_pages,
                    "links": pagination_links,
                },
            }

            return Response(data, status=status.HTTP_200_OK)

        queryset = Contact.objects.filter(org=project.org).order_by("-modified_on")[:10]
        serializer = GetContactsSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List ElasticSearch contacts",
            "url": reverse("api.v2.contacts_elastic"),
            "slug": "contacts-elastic-list",
            "params": [
                {
                    "name": "project_uuid",
                    "required": True,
                    "help": "Return objects from a project, ex: project_uuid=09d23a05-47fe-11e4-bfe9-b8f6b119e9ab",
                },
                {
                    "name": "name",
                    "required": False,
                    "help": "Only return contacts with this name, ex: name=John",
                },
                {
                    "name": "number",
                    "required": False,
                    "help": "Return contacts with part or literal number, ex: number=12345",
                },
                {
                    "name": "page_size",
                    "required": False,
                    "help": "Only return number of contacts with this page size, ex: page_size=10",
                },
                {
                    "name": "page_number",
                    "required": False,
                    "help": "Return the number of the page, ex: page_number=1",
                },
            ],
        }
