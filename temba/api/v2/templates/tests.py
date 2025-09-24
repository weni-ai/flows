from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

from rest_framework.test import APIRequestFactory

from django.urls import reverse
from django.utils import timezone

from temba.api.v2.templates.serializers import TemplateTranslationDetailsSerializer
from temba.api.v2.templates.views import TemplateByIdEndpoint
from temba.templates.models import Template, TemplateButton, TemplateHeader, TemplateTranslation
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

    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.permission_classes", [])
    def test_filter_by_category(self):
        self.login(self.admin)

        t_marketing = Template.objects.create(org=self.org, name="promo", category="MARKETING")
        t_utility = Template.objects.create(org=self.org, name="notice", category="UTILITY")

        TemplateTranslation.objects.create(
            template=t_marketing,
            channel=self.channel,
            content="Hi",
            body="Hi",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="cat-1",
        )
        TemplateTranslation.objects.create(
            template=t_utility,
            channel=self.channel,
            content="Util",
            body="Util",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="cat-2",
        )

        # pass lowercase to exercise .upper() branch
        url = self._url({"project_uuid": str(self.org.proj_uuid), "category": "marketing"})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        names = [r["name"] for r in resp.json()["results"]]
        self.assertIn("promo", names)
        self.assertNotIn("notice", names)

    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.permission_classes", [])
    def test_filter_by_name_contains(self):
        self.login(self.admin)

        t1 = Template.objects.create(org=self.org, name="Welcome Offer")
        t2 = Template.objects.create(org=self.org, name="Alert")

        TemplateTranslation.objects.create(
            template=t1,
            channel=self.channel,
            content="c1",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="name-1",
        )
        TemplateTranslation.objects.create(
            template=t2,
            channel=self.channel,
            content="c2",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="name-2",
        )

        url = self._url({"project_uuid": str(self.org.proj_uuid), "name": "welcome"})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        names = [r["name"] for r in resp.json()["results"]]
        self.assertEqual(names, ["Welcome Offer"])

    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.permission_classes", [])
    def test_filter_by_channel_and_language(self):
        self.login(self.admin)

        t = Template.objects.create(org=self.org, name="multi-lang")
        TemplateTranslation.objects.create(
            template=t,
            channel=self.channel,
            content="hello",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="lang-1",
        )
        TemplateTranslation.objects.create(
            template=t,
            channel=self.channel,
            content="bonjour",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="fra",
            external_id="lang-2",
        )

        params = {
            "project_uuid": str(self.org.proj_uuid),
            "channel": str(self.channel.uuid),
            "language": "ENg",  # case-insensitive match
        }
        resp = self.client.get(self._url(params))
        self.assertEqual(resp.status_code, 200)
        results = resp.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["language"], "eng")

    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.permission_classes", [])
    def test_ordering_by_name_and_desc(self):
        self.login(self.admin)

        t_a = Template.objects.create(org=self.org, name="A")
        t_b = Template.objects.create(org=self.org, name="B")

        TemplateTranslation.objects.create(
            template=t_a,
            channel=self.channel,
            content="a",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="ord-1",
        )
        TemplateTranslation.objects.create(
            template=t_b,
            channel=self.channel,
            content="b",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="ord-2",
        )

        # name ascending
        url = self._url({"project_uuid": str(self.org.proj_uuid), "order_by": "name"})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        names = [r["name"] for r in resp.json()["results"]]
        self.assertEqual(names, ["A", "B"])

        # name descending
        url = self._url({"project_uuid": str(self.org.proj_uuid), "order_by": "-name"})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        names = [r["name"] for r in resp.json()["results"]]
        self.assertEqual(names, ["B", "A"])

    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplatesTranslationsEndpoint.permission_classes", [])
    def test_ordering_by_created_on_and_default(self):
        self.login(self.admin)

        t_old = Template.objects.create(org=self.org, name="old")
        t_new = Template.objects.create(org=self.org, name="new")

        # ensure distinct created_on values
        t_old.created_on = timezone.now()
        t_old.save(update_fields=["created_on"])
        t_new.created_on = timezone.now() + timezone.timedelta(seconds=1)
        t_new.save(update_fields=["created_on"])

        TemplateTranslation.objects.create(
            template=t_old,
            channel=self.channel,
            content="o",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="cre-1",
        )
        TemplateTranslation.objects.create(
            template=t_new,
            channel=self.channel,
            content="n",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="cre-2",
        )

        # created_on ascending
        url = self._url({"project_uuid": str(self.org.proj_uuid), "order_by": "created_on"})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        names = [r["name"] for r in resp.json()["results"]]
        self.assertEqual(names, ["old", "new"])

        # default (-created_on)
        url = self._url({"project_uuid": str(self.org.proj_uuid)})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        names = [r["name"] for r in resp.json()["results"]]
        self.assertEqual(names, ["new", "old"])

    # duplicate of the test in TemplatesTranslationsEndpointTests; removing to avoid NoReverseMatch


class TemplateByIdEndpointTests(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid4()
        self.org.save()

    def _url(self, template_id, params=None):
        base = reverse("api.v2.templates_translation_by_id", args=[template_id])
        if params:
            return f"{base}?{urlencode(params)}"
        return base

    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.permission_classes", [])
    def test_missing_project_uuid(self):
        self.login(self.admin)
        # template id won't be resolved without project uuid, but endpoint still executes
        template = Template.objects.create(org=self.org, name="t")
        resp = self.client.get(self._url(template.id))
        self.assertEqual(resp.status_code, 401)

    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.permission_classes", [])
    def test_invalid_project_uuid(self):
        self.login(self.admin)
        template = Template.objects.create(org=self.org, name="t")
        resp = self.client.get(self._url(template.id, {"project_uuid": str(uuid4())}))
        self.assertEqual(resp.status_code, 404)

    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.permission_classes", [])
    def test_template_not_found(self):
        self.login(self.admin)
        resp = self.client.get(self._url(99999, {"project_uuid": str(self.org.proj_uuid)}))
        self.assertEqual(resp.status_code, 404)

    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.permission_classes", [])
    def test_no_active_translations(self):
        self.login(self.admin)
        template = Template.objects.create(org=self.org, name="empty")
        resp = self.client.get(self._url(template.id, {"project_uuid": str(self.org.proj_uuid)}))
        self.assertEqual(resp.status_code, 404)

    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.permission_classes", [])
    def test_language_not_found(self):
        self.login(self.admin)
        template = Template.objects.create(org=self.org, name="t")
        TemplateTranslation.objects.create(
            template=template,
            channel=self.channel,
            content="hello",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="byid-1",
        )
        params = {"project_uuid": str(self.org.proj_uuid), "language": "fra"}
        resp = self.client.get(self._url(template.id, params))
        self.assertEqual(resp.status_code, 404)

    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.permission_classes", [])
    def test_success(self):
        self.login(self.admin)
        template = Template.objects.create(org=self.org, name="t")
        TemplateTranslation.objects.create(
            template=template,
            channel=self.channel,
            content="hello",
            body="Body",
            footer="Foot",
            variable_count=0,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="byid-2",
        )
        resp = self.client.get(self._url(template.id, {"project_uuid": str(self.org.proj_uuid), "language": "ENg"}))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], template.name)
        self.assertEqual(data["language"], "eng")

    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.authentication_classes", [])
    @patch("temba.api.v2.templates.views.TemplateByIdEndpoint.permission_classes", [])
    def test_template_id_must_be_integer(self):
        factory = APIRequestFactory()
        request = factory.get("/api/v2/templates/translations/notint", {"project_uuid": str(self.org.proj_uuid)})
        response = TemplateByIdEndpoint.as_view()(request, template_id="notint")
        self.assertEqual(response.status_code, 400)


class TemplateSerializationTests(TembaTest):
    def setUp(self):
        super().setUp()

    def test_serializer_includes_header_and_buttons(self):
        template = Template.objects.create(org=self.org, name="serialize_components")
        tt = TemplateTranslation.objects.create(
            template=template,
            channel=self.channel,
            content="Hello {{1}}",
            body="Body text",
            footer="Footer text",
            variable_count=1,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="ser-hb",
        )
        TemplateHeader.objects.create(translation=tt, type="TEXT", text="Header text")
        TemplateButton.objects.create(translation=tt, type="QUICK_REPLY", text="Yes")

        data = TemplateTranslationDetailsSerializer(tt).data
        self.assertEqual(data["header"]["type"], "TEXT")
        self.assertEqual(data["header"]["text"], "Header text")
        self.assertTrue(data["buttons"])  # non-empty
        self.assertEqual(data["buttons"][0]["type"], "QUICK_REPLY")
        self.assertEqual(data["buttons"][0]["text"], "Yes")
