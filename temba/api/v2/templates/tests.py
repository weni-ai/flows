from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

from django.urls import reverse

from temba.templates.models import Template, TemplateTranslation
from temba.tests import TembaTest


class TemplatesTranslationsEndpointTests(TembaTest):
    def setUp(self):
        super().setUp()
        # ensure project uuid is present for org
        self.org.proj_uuid = uuid4()
        self.org.save()

    def _url(self, params=None):
        base = reverse("api.v2.templates_translations")
        if params:
            return f"{base}?{urlencode(params)}"
        return base

    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.permission_classes", [])
    def test_missing_project_uuid(self):
        self.login(self.admin)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 401)

    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.permission_classes", [])
    def test_invalid_project_uuid(self):
        self.login(self.admin)
        resp = self.client.get(self._url({"project_uuid": str(uuid4())}))
        self.assertEqual(resp.status_code, 404)

    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.permission_classes", [])
    def test_list_translations_success_with_pagination(self):
        self.login(self.admin)

        # create active template + translations
        template = Template.objects.create(org=self.org, name="welcome_message")
        TemplateTranslation.objects.create(
            template=template,
            channel=self.channel,
            content="Hello {{1}}",
            body="Hello {{1}}",
            footer="Bye",
            variable_count=1,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="id-1",
        )

        # inactive template should not appear
        template_inactive = Template.objects.create(org=self.org, name="inactive_template", is_active=False)
        TemplateTranslation.objects.create(
            template=template_inactive,
            channel=self.channel,
            content="Inactive",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="id-2",
            is_active=True,
        )

        # inactive translation should not appear
        TemplateTranslation.objects.create(
            template=template,
            channel=self.channel,
            content="Bonjour",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="fra",
            external_id="id-3",
            is_active=False,
        )

        url = self._url({"project_uuid": str(self.org.proj_uuid), "limit": 1})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 1)

        item = data["results"][0]
        self.assertEqual(item["name"], template.name)
        self.assertEqual(item["uuid"], str(template.uuid))
        self.assertEqual(item["category"], template.category)
        self.assertEqual(item["language"], "eng")
        self.assertIn("header", item)
        self.assertIn("body", item)
        self.assertIn("footer", item)
        self.assertIn("buttons", item)

        # follow pagination if present
        next_url = data.get("next")
        if next_url:
            resp2 = self.client.get(next_url)
            self.assertEqual(resp2.status_code, 200)
