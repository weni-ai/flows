import requests
from rest_framework.response import Response
from weni.internal.clients.base import BaseInternalClient

from django.conf import settings
from django.urls import reverse

from temba.api.v2.views_base import BaseAPIView


class IntelligencesEndpoint(BaseAPIView, BaseInternalClient):
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
        org = self.request.user.get_org()
        project_uuid = org.project.project_uuid

        headers = {
            "Content-Type": "application/json; charset: utf-8",
            "Authorization": "Bearer " + settings.INTELLIGENCES_TOKEN,
        }

        self.base_url = settings.NEXUS_BASE_URL

        response = requests.get(
            self.get_url(f"/api/v1/intelligences/content_bases/{project_uuid}"),
            headers=headers,
        )

        if response.status_code >= 400:
            return Response({"results": []})

        intelligences = response.json()

        results = []
        for intelligence in intelligences:
            for content_base in intelligence.get("content_bases", []):
                results.append(
                    {
                        "id": content_base.get("uuid"),
                        "name": content_base.get("content_base_name"),
                        "intelligence": intelligence.get("intelligence_name"),
                    }
                )

        return Response({"results": results})

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "List Intelligences",
            "url": reverse("api.v2.intelligences"),
            "slug": "intelligences-list",
            "params": [],
        }
