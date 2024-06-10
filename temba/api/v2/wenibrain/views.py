import requests
from rest_framework.response import Response
from weni.internal.clients.base import BaseInternalClient

from django.conf import settings
from django.urls import reverse

from temba.api.v2.views_base import BaseAPIView


class BrainInfoEndpoint(BaseAPIView, BaseInternalClient):
    """
    This endpoint allows you to get Weni Brain Agent information.

    ## Getting Weni Brain Agent Information

    A `GET` returns the name and occupation of your organization's brain agent with the following fields.

      * **name** - the agent's name (string)
      * **occupation** - the agent's occupation (string)

    Example:

        GET /api/v2/brain_info.json

    Response is an object with the agent's name and occupation

        {
            "name": "Agent Name",
            "occupation": "Agent Occupation"
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
            self.get_url(f"/api/{project_uuid}/customization/"),
            headers=headers,
        )

        if response.status_code >= 400:
            return Response({"name": "", "occupation": ""})
        
        agent = response.json().get("agent", None)

        if not agent:
            return Response({"name": "", "occupation": ""})

        return Response({"name": agent.get("name", ""), "occupation": agent.get("role", "")})

    @classmethod
    def get_read_explorer(cls):
        return {
            "method": "GET",
            "title": "Weni Brain Info",
            "url": reverse("api.v2.brain_info"),
            "slug": "brain-info",
            "params": [],
        }
