from unittest.mock import patch

from rest_framework import status

from django.urls import reverse

from temba.templates.views import TemplateViewSet
from temba.tests import TembaTest

from .models import Template, TemplateTranslation


class TemplateTest(TembaTest):
    def test_templates(self):
        tt1 = TemplateTranslation.get_or_create(
            self.channel, "hello", "eng", "US", "Hello {{1}}", 1, TemplateTranslation.STATUS_PENDING, "1234", ""
        )
        tt2 = TemplateTranslation.get_or_create(
            self.channel, "hello", "fra", "FR", "Bonjour {{1}}", 1, TemplateTranslation.STATUS_PENDING, "5678", ""
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
        )

        self.assertTrue(tt3.template.modified_on > modified_on)
        self.assertEqual(tt3.namespace, "foo_namespace")
        self.assertEqual(1, Template.objects.filter(org=self.org).count())
        self.assertEqual(2, TemplateTranslation.objects.filter(channel=self.channel).count())

        # trim them
        TemplateTranslation.trim(self.channel, [tt1])

        # tt2 should be inactive now
        tt2.refresh_from_db()
        self.assertFalse(tt2.is_active)


class TemplateViewSetTests(TembaTest):
    view_class = TemplateViewSet
    view_class.permission_classes = []

    def test_partial_update(self):
        # client = APIClient()
        url = reverse("template-detail", args=[self.channel.uuid])
        # client.force_login(self.admin)
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
