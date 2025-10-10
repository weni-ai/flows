from unittest.mock import patch

from rest_framework.authentication import SessionAuthentication

from django.test import override_settings

from temba.flows.models import Flow
from temba.tests.base import TembaTest
from temba.tests.mailroom import mock_mailroom
from temba.utils.uuid import uuid4


class TestFlowImportView(TembaTest):
    def setUp(self):
        super().setUp()
        # garantir proj_uuid para lookup por projeto
        self.org.proj_uuid = self.org.proj_uuid or uuid4()
        self.org.save(update_fields=["proj_uuid"])

        self.url = "/api/v2/internals/flows/import"
        self.inspect_response = {
            Flow.INSPECT_ISSUES: [],
            Flow.INSPECT_RESULTS: {},
            Flow.INSPECT_DEPENDENCIES: {},
            Flow.INSPECT_WAITING_EXITS: [],
            Flow.INSPECT_PARENT_REFS: [],
        }

    def build_export_definition(self, flow_name: str) -> dict:
        return {
            "version": str(self.org.CURRENT_EXPORT_VERSION),
            "site": "https://app.rapidpro.io",
            "flows": [
                {
                    "uuid": str(uuid4()),
                    "name": flow_name,
                    "spec_version": Flow.CURRENT_SPEC_VERSION,
                    "language": "eng",
                    "type": "messaging",
                    "nodes": [],
                }
            ],
        }

    def post_import(self, export_definition: dict):
        body = {"project_uuid": str(self.org.proj_uuid), "definition": export_definition}
        with override_settings(INTERNAL_USER_EMAIL=self.user.email):
            self.client.force_login(self.user)
            with patch(
                "temba.mailroom.client.MailroomClient.flow_migrate",
                side_effect=lambda definition, to_version: definition,
            ), patch(
                "temba.mailroom.client.MailroomClient.flow_inspect",
                return_value=self.inspect_response,
            ):
                return self.client.post(self.url, data=body, content_type="application/json")

    @patch("temba.api.v2.internals.flows.views.FlowImportView.authentication_classes", [SessionAuthentication])
    @patch("temba.api.v2.internals.flows.views.FlowImportView.permission_classes", [])
    @mock_mailroom()
    def test_import_flows_success(self, mr_mocks):
        export_definition = self.build_export_definition("Imported Flow")
        resp = self.post_import(export_definition)

        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 1)
        self.assertIn("uuid", data["results"][0])
        self.assertIn("name", data["results"][0])
        # response should include at least uuid and name

        # verificar se o flow realmente existe
        self.assertTrue(Flow.objects.filter(org=self.org, name="Imported Flow", is_active=True).exists())

    @patch("temba.api.v2.internals.flows.views.FlowImportView.authentication_classes", [SessionAuthentication])
    @patch("temba.api.v2.internals.flows.views.FlowImportView.permission_classes", [])
    def test_import_flows_missing_project_uuid(self):
        url = self.url
        body = {"definition": {"version": Flow.CURRENT_SPEC_VERSION, "site": "x", "flows": []}}

        self.client.force_login(self.user)
        resp = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(resp.status_code, 400)

    @patch("temba.api.v2.internals.flows.views.FlowImportView.authentication_classes", [SessionAuthentication])
    @patch("temba.api.v2.internals.flows.views.FlowImportView.permission_classes", [])
    @mock_mailroom()
    def test_import_flows_has_issues_flag(self, mr_mocks):
        export_definition = self.build_export_definition("Flow With Issues")
        resp = self.post_import(export_definition)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 1)
        # response includes at least uuid and name
