from unittest.mock import patch
from uuid import uuid4

from django.urls import reverse

from temba.flows.models import Flow
from temba.tests.base import TembaTest


class TestInternalFlowsAPIView(TembaTest):
    def setUp(self):
        super().setUp()
        # ensure project has a proj_uuid for lookups
        self.org.proj_uuid = uuid4()
        self.org.save(update_fields=["proj_uuid"])

    @patch("temba.api.v2.flows.views.InternalFlowsAPIView.authentication_classes", [])
    @patch("temba.api.v2.flows.views.InternalFlowsAPIView.permission_classes", [])
    def test_list_flows_success(self):
        # create some flows
        flow1 = Flow.create(self.org, self.user, name="Flow One")
        Flow.create(self.org, self.user, name="Flow Two")
        Flow.create(self.org, self.user, name="Flow Three")

        url = f"{reverse('api.v2.internal_flows')}?project_uuid={self.org.proj_uuid}&limit=2"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # paginated response shape
        self.assertIn("results", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)

        # only uuid and name returned
        self.assertEqual(len(data["results"][0].keys()), 2)
        self.assertIn("uuid", data["results"][0])
        self.assertIn("name", data["results"][0])

        # ordering should be newest first (flow3, flow2, ...)
        self.assertEqual({r["name"] for r in data["results"]}, {"Flow Three", "Flow Two"})
        self.assertIsNotNone(data["next"])  # has more pages

        # follow next page
        next_url = data["next"]
        resp = self.client.get(next_url)
        self.assertEqual(resp.status_code, 200)
        data2 = resp.json()
        self.assertEqual(len(data2["results"]), 1)
        self.assertEqual(data2["results"][0]["name"], flow1.name)

    @patch("temba.api.v2.flows.views.InternalFlowsAPIView.authentication_classes", [])
    @patch("temba.api.v2.flows.views.InternalFlowsAPIView.permission_classes", [])
    def test_missing_project_uuid(self):
        resp = self.client.get(reverse("api.v2.internal_flows"))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "project_uuid is required"})

    @patch("temba.api.v2.flows.views.InternalFlowsAPIView.authentication_classes", [])
    @patch("temba.api.v2.flows.views.InternalFlowsAPIView.permission_classes", [])
    def test_invalid_project_uuid(self):
        url = f"{reverse('api.v2.internal_flows')}?project_uuid={uuid4()}&limit=1"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "Project not found"})

    @patch("temba.api.v2.flows.views.InternalFlowsAPIView.authentication_classes", [])
    @patch("temba.api.v2.flows.views.InternalFlowsAPIView.permission_classes", [])
    def test_pagination_limit(self):
        # create more flows than the limit
        for i in range(12):
            Flow.create(self.org, self.user, name=f"Flow {i}")

        url = f"{reverse('api.v2.internal_flows')}?project_uuid={self.org.proj_uuid}&limit=5"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["results"]), 5)
        self.assertIsNotNone(data.get("next"))


