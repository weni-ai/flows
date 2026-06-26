from unittest.mock import patch

from rest_framework import status

from django.db import IntegrityError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from temba.templates.views import TemplateViewSet
from temba.tests import TembaTest

from .models import Template, TemplateLastDispatch, TemplateTranslation


class TemplateTest(TembaTest):
    def test_templates(self):
        tt1 = TemplateTranslation.get_or_create(
            self.channel,
            "hello",
            "eng",
            "US",
            "Hello {{1}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "1234",
            "",
            "AUTHENTICATION",
        )
        tt2 = TemplateTranslation.get_or_create(
            self.channel,
            "hello",
            "fra",
            "FR",
            "Bonjour {{1}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "5678",
            "",
            "AUTHENTICATION",
        )

        self.assertEqual(tt1.template, tt2.template)
        modified_on = tt1.template.modified_on

        tt3 = TemplateTranslation.get_or_create(
            self.channel,
            "hello",
            "fra",
            "FR",
            "Salut {{1}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "5678",
            "foo_namespace",
            "AUTHENTICATION",
        )

        self.assertTrue(tt3.template.modified_on > modified_on)
        self.assertEqual(tt3.namespace, "foo_namespace")
        self.assertEqual(1, Template.objects.filter(org=self.org).count())
        self.assertEqual(2, TemplateTranslation.objects.filter(channel=self.channel).count())

        # trim them
        TemplateTranslation.trim(self.channel, [tt1])

    def test_get_or_create_updates_category_on_existing_translation(self):
        tt = TemplateTranslation.get_or_create(
            self.channel,
            "hello",
            "eng",
            "US",
            "Hello {{1}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "1234",
            "",
            "UTILITY",
        )
        self.assertEqual(tt.template.category, "UTILITY")

        tt_updated = TemplateTranslation.get_or_create(
            self.channel,
            "hello",
            "eng",
            "US",
            "Hello {{1}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "1234",
            "",
            "MARKETING",
        )

        self.assertEqual(tt.id, tt_updated.id)
        tt_updated.template.refresh_from_db()
        self.assertEqual(tt_updated.template.category, "MARKETING")

    def test_get_or_create_category_only_change_triggers_update(self):
        tt = TemplateTranslation.get_or_create(
            self.channel,
            "promo",
            "eng",
            "US",
            "Buy now {{1}}",
            1,
            TemplateTranslation.STATUS_APPROVED,
            "cat-only-1",
            "",
            "UTILITY",
        )
        original_modified_on = tt.template.modified_on

        tt_updated = TemplateTranslation.get_or_create(
            self.channel,
            "promo",
            "eng",
            "US",
            "Buy now {{1}}",
            1,
            TemplateTranslation.STATUS_APPROVED,
            "cat-only-1",
            "",
            "MARKETING",
        )

        tt_updated.template.refresh_from_db()
        self.assertEqual(tt_updated.template.category, "MARKETING")
        self.assertTrue(tt_updated.template.modified_on > original_modified_on)

    def test_get_or_create_updates_body_and_footer(self):
        # create initial translation with body and footer
        tt = TemplateTranslation.get_or_create(
            self.channel,
            "hello",
            "eng",
            "US",
            "Hello {{1}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "ext-1",
            "",
            "AUTHENTICATION",
            body="Body v1",
            footer="Foot v1",
        )

        self.assertEqual(tt.body, "Body v1")
        self.assertEqual(tt.footer, "Foot v1")

        # call again with updated body and footer to exercise update branches
        tt_updated = TemplateTranslation.get_or_create(
            self.channel,
            "hello",
            "eng",
            "US",
            "Hello {{1}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "ext-1",
            "",
            "AUTHENTICATION",
            body="Body v2",
            footer="Foot v2",
        )

        self.assertEqual(tt.id, tt_updated.id)

        refreshed = TemplateTranslation.objects.get(id=tt.id)
        self.assertEqual(refreshed.body, "Body v2")
        self.assertEqual(refreshed.footer, "Foot v2")


class TemplateLastDispatchTest(TembaTest):
    def test_create_template_last_dispatch(self):
        fired_on = timezone.now()
        template_uuid = "44019537-9afe-4898-9626-a5c724d169ef"

        record = TemplateLastDispatch.objects.create(
            org=self.org,
            template_uuid=template_uuid,
            name="hello",
            meta_template_id="123456789",
            last_fired_on=fired_on,
        )

        self.assertEqual(record.org, self.org)
        self.assertEqual(str(record.template_uuid), template_uuid)
        self.assertIsNone(record.template)
        self.assertEqual(record.name, "hello")
        self.assertEqual(record.meta_template_id, "123456789")
        self.assertEqual(record.last_fired_on, fired_on)

    def test_link_to_template(self):
        translation = TemplateTranslation.get_or_create(
            self.channel,
            "hello",
            "eng",
            "US",
            "Hello {{1}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "123456789",
            "",
            "AUTHENTICATION",
        )
        template = translation.template

        record = TemplateLastDispatch.objects.create(
            org=self.org,
            template=template,
            template_uuid=template.uuid,
            name=template.name,
            meta_template_id="123456789",
            last_fired_on=timezone.now(),
        )

        self.assertEqual(record.template, template)
        self.assertEqual(record.template_uuid, template.uuid)
        self.assertEqual(template.last_dispatches.get(), record)

    def test_unique_together_org_and_meta_template_id(self):
        TemplateLastDispatch.objects.create(
            org=self.org,
            template_uuid="44019537-9afe-4898-9626-a5c724d169ef",
            name="hello",
            meta_template_id="123456789",
            last_fired_on=timezone.now(),
        )

        with self.assertRaises(IntegrityError):
            TemplateLastDispatch.objects.create(
                org=self.org,
                template_uuid="44019537-9afe-4898-9626-a5c724d169ef",
                name="hello",
                meta_template_id="123456789",
                last_fired_on=timezone.now(),
            )

    def test_same_meta_template_id_allowed_for_different_orgs(self):
        TemplateLastDispatch.objects.create(
            org=self.org,
            template_uuid="44019537-9afe-4898-9626-a5c724d169ef",
            name="hello",
            meta_template_id="123456789",
            last_fired_on=timezone.now(),
        )
        TemplateLastDispatch.objects.create(
            org=self.org2,
            template_uuid="44019537-9afe-4898-9626-a5c724d169ef",
            name="hello",
            meta_template_id="123456789",
            last_fired_on=timezone.now(),
        )

        self.assertEqual(1, TemplateLastDispatch.objects.filter(org=self.org).count())
        self.assertEqual(1, TemplateLastDispatch.objects.filter(org=self.org2).count())

    def test_str(self):
        record = TemplateLastDispatch.objects.create(
            org=self.org,
            template_uuid="44019537-9afe-4898-9626-a5c724d169ef",
            name="hello",
            meta_template_id="123456789",
            last_fired_on=timezone.now(),
        )

        self.assertEqual(str(record), "hello (44019537-9afe-4898-9626-a5c724d169ef)")


class TemplateViewSetTests(TembaTest):
    view_class = TemplateViewSet
    view_class.permission_classes = []

    @override_settings(OIDC_OP_TOKEN_ENDPOINT="ExampleEndpointToken")
    @override_settings(OIDC_OP_USER_ENDPOINT="ExampleUser")
    @override_settings(OIDC_RP_CLIENT_ID="ExampleID")
    @override_settings(OIDC_RP_CLIENT_SECRET="ExampleSecret")
    def test_partial_update(self):
        url = reverse("template-detail", args=[self.channel.uuid])
        self.login(self.admin)

        with patch("temba.utils.whatsapp.tasks.update_local_templates") as mock_update_local_templates:
            mock_update_local_templates.return_value = None

            data = {
                "data": [
                    {
                        "name": "model body",
                        "previous_category": "OTP",
                        "components": [
                            {"type": "BODY", "text": "A normal body: {{1}}.", "example": {"body_text": [["12345"]]}}
                        ],
                        "language": "pt_PT",
                        "status": "APPROVED",
                        "category": "AUTHENTICATION",
                        "id": "123456",
                    }
                ]
            }
            response = self.client.patch(url, data, content_type="application/json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
