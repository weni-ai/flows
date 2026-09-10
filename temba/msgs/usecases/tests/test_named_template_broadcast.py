from django.test import TestCase

from temba.msgs.usecases.named_template_broadcast import (
    NamedTemplateBroadcastError,
    resolve_named_recipients,
)
from temba.templates.models import Template, TemplateTranslation
from temba.templates.parameter_format import (
    extract_parameter_names,
    has_placeholders,
    normalize_parameter_format,
)
from temba.tests import TembaTest


class ParameterFormatHelpersTest(TestCase):
    def test_normalize_parameter_format(self):
        self.assertEqual("named", normalize_parameter_format("NAMED"))
        self.assertEqual("named", normalize_parameter_format("named"))
        self.assertEqual("positional", normalize_parameter_format("POSITIONAL"))
        self.assertEqual("positional", normalize_parameter_format(None))
        self.assertEqual("positional", normalize_parameter_format("unexpected"))

    def test_extract_parameter_names(self):
        self.assertEqual(
            ["nome", "cota", "data"],
            extract_parameter_names("Olá {{nome}}, sua cota {{cota}} vence em {{data}}"),
        )
        self.assertEqual(["nome"], extract_parameter_names("Olá {{nome}}, ainda {{nome}}"))
        self.assertEqual([], extract_parameter_names("Hello {{1}}"))

    def test_has_placeholders(self):
        self.assertTrue(has_placeholders("Hi {{nome}}"))
        self.assertTrue(has_placeholders("Hi {{1}}"))
        self.assertFalse(has_placeholders("Hi there"))


class NamedTemplateBroadcastTest(TembaTest):
    def _named_template(self, names=None):
        channel = self.create_channel("WAC", "WA Cloud", "1234")
        template = Template.objects.create(
            org=self.org,
            name="cobranca_bf4",
            parameter_format="named",
        )
        TemplateTranslation.objects.create(
            template=template,
            channel=channel,
            content="Olá {{nome}}, sua cota {{cota}}",
            body="Olá {{nome}}, sua cota {{cota}}",
            variable_count=2,
            status=TemplateTranslation.STATUS_APPROVED,
            language="por",
            external_id="named-1",
            parameter_names=names or ["nome", "cota"],
        )
        return template, channel

    def test_holds_back_missing_required_parameter(self):
        template, _ = self._named_template()
        result = resolve_named_recipients(
            self.org,
            template,
            [
                {"urn": "whatsapp:5511999999999", "variables": {"nome": "João", "cota": "045"}},
                {"urn": "whatsapp:5511888888888", "variables": {"nome": "Ana"}},
            ],
            {},
        )
        self.assertEqual(1, result["accepted_count"])
        self.assertEqual(1, result["rejected_count"])
        self.assertEqual("whatsapp:5511999999999", result["accepted_urns"][0])
        self.assertEqual("cota", result["rejected"][0]["parameter"])
        self.assertNotIn("whatsapp:5511888888888", result["recipient_variables"])
        self.assertEqual("045", result["recipient_variables"]["whatsapp:5511999999999"]["cota"])

    def test_rejects_when_every_recipient_is_held_back(self):
        template, _ = self._named_template()
        with self.assertRaises(NamedTemplateBroadcastError):
            resolve_named_recipients(
                self.org,
                template,
                [{"urn": "whatsapp:5511888888888", "variables": {"nome": "Ana"}}],
                {},
            )

    def test_optional_parameter_uses_default(self):
        template, _ = self._named_template()
        template.parameter_policies = {"cota": {"required": False, "default": "não informado"}}
        template.save(update_fields=["parameter_policies"])
        result = resolve_named_recipients(
            self.org,
            template,
            [{"urn": "whatsapp:5511888888888", "variables": {"nome": "Ana"}}],
            {},
        )
        self.assertEqual(1, result["accepted_count"])
        self.assertEqual("não informado", result["recipient_variables"]["whatsapp:5511888888888"]["cota"])
