from unittest.mock import patch

from django.test import override_settings

from temba.flows.models import Flow
from temba.tests.base import TembaTest
from temba.tests.mailroom import mock_mailroom


class TestFlowImportView(TembaTest):
    def setUp(self):
        super().setUp()
        # garantir proj_uuid para lookup por projeto
        self.org.proj_uuid = self.org.proj_uuid or self.create_uuid()
        self.org.save(update_fields=["proj_uuid"])

    @patch("temba.api.v2.internals.flows.views.FlowImportView.authentication_classes", [])
    @patch("temba.api.v2.internals.flows.views.FlowImportView.permission_classes", [])
    @mock_mailroom()
    def test_import_flows_success(self, mr_mocks):
        url = "/api/v2/internals/flows/import"

        # definição mínima de export para importar 1 flow
        export_definition = {
            "version": Flow.CURRENT_SPEC_VERSION,
            "site": "https://app.rapidpro.io",
            "flows": [
                {
                    "uuid": str(self.create_uuid()),
                    "name": "Imported Flow",
                    "spec_version": Flow.CURRENT_SPEC_VERSION,
                    "language": "eng",
                    "type": "messaging",
                    "nodes": [],
                }
            ],
        }

        body = {"project_uuid": str(self.org.proj_uuid), "definition": export_definition}

        # simular request com usuário autenticado
        with override_settings(INTERNAL_USER_EMAIL=self.user.email):
            self.client.force_login(self.user)
            resp = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 1)
        self.assertIn("uuid", data["results"][0])
        self.assertIn("name", data["results"][0])
        self.assertIn("has_issues", data["results"][0])

        # verificar se o flow realmente existe
        self.assertTrue(Flow.objects.filter(org=self.org, name="Imported Flow", is_active=True).exists())

    @patch("temba.api.v2.internals.flows.views.FlowImportView.authentication_classes", [])
    @patch("temba.api.v2.internals.flows.views.FlowImportView.permission_classes", [])
    def test_import_flows_missing_project_uuid(self):
        url = "/api/v2/internals/flows/import"
        body = {"definition": {"version": Flow.CURRENT_SPEC_VERSION, "site": "x", "flows": []}}

        self.client.force_login(self.user)
        resp = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(resp.status_code, 400)

    @patch("temba.api.v2.internals.flows.views.FlowImportView.authentication_classes", [])
    @patch("temba.api.v2.internals.flows.views.FlowImportView.permission_classes", [])
    @mock_mailroom()
    def test_import_flows_has_issues_flag(self, mr_mocks):
        url = "/api/v2/internals/flows/import"

        # definição com 1 flow; mailroom irá marcar has_issues conforme inspeção simulada
        export_definition = {
            "version": Flow.CURRENT_SPEC_VERSION,
            "site": "https://app.rapidpro.io",
            "flows": [
                {
                    "uuid": str(self.create_uuid()),
                    "name": "Flow With Issues",
                    "spec_version": Flow.CURRENT_SPEC_VERSION,
                    "language": "eng",
                    "type": "messaging",
                    "nodes": [],
                }
            ],
        }

        body = {"project_uuid": str(self.org.proj_uuid), "definition": export_definition}

        self.client.force_login(self.user)
        resp = self.client.post(url, data=body, content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 1)
        self.assertIn("has_issues", data["results"][0])
