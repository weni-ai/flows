from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase

from temba.api.v2.serializers import TemplateReadSerializer, WhatsappBroadcastWriteSerializer
from temba.api.v2.templates.serializers import TemplateTranslationDetailsSerializer
from temba.msgs.models import Broadcast
from temba.msgs.usecases.named_template_broadcast import (
    NamedTemplateBroadcastError,
    assert_named_template_ready,
    declared_parameter_names,
    resolve_named_recipients,
)
from temba.templates.models import Template, TemplateTranslation
from temba.templates.parameter_format import (
    extract_parameter_names,
    extract_parameter_names_from_components,
    has_placeholders,
    is_named_format,
    is_provided_value,
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

    def test_is_named_format(self):
        self.assertTrue(is_named_format("NAMED"))
        self.assertFalse(is_named_format("positional"))
        self.assertFalse(is_named_format(None))

    def test_is_provided_value(self):
        self.assertTrue(is_provided_value("João"))
        self.assertFalse(is_provided_value(None))
        self.assertFalse(is_provided_value(""))
        self.assertFalse(is_provided_value("   "))

    def test_extract_parameter_names(self):
        self.assertEqual(
            ["nome", "cota", "data"],
            extract_parameter_names("Olá {{nome}}, sua cota {{cota}} vence em {{data}}"),
        )
        self.assertEqual(["nome"], extract_parameter_names("Olá {{nome}}, ainda {{nome}}"))
        self.assertEqual([], extract_parameter_names("Hello {{1}}"))
        self.assertEqual([], extract_parameter_names("{{ }}"))
        self.assertEqual([], extract_parameter_names("{{9nome}}"))
        self.assertEqual(["vencimento"], extract_parameter_names("vence em {{ vencimento }}"))
        self.assertEqual([], extract_parameter_names(None))

    def test_extract_parameter_names_from_components(self):
        self.assertEqual([], extract_parameter_names_from_components(None))
        self.assertEqual(
            ["nome", "cota", "extra"],
            extract_parameter_names_from_components(
                [
                    {"type": "HEADER", "text": "Hi {{ignored}}"},
                    {
                        "type": "body",
                        "text": "Olá {{nome}} {{extra}}",
                        "example": {
                            "body_text_named_params": [
                                {"param_name": "nome"},
                                None,
                                {"param_name": "cota"},
                                {"param_name": "nome"},
                            ]
                        },
                    },
                ]
            ),
        )
        self.assertEqual(
            ["data"],
            extract_parameter_names_from_components([{"type": "BODY", "text": "vence {{data}}"}]),
        )

    def test_has_placeholders(self):
        self.assertTrue(has_placeholders("Hi {{nome}}"))
        self.assertTrue(has_placeholders("Hi {{1}}"))
        self.assertFalse(has_placeholders("Hi there"))


class NamedTemplateBroadcastTest(TembaTest):
    def _named_template(self, names=None, channel_type="WAC"):
        suffix = uuid4().hex[:8]
        channel = self.create_channel(channel_type, f"WA {suffix}", suffix)
        template = Template.objects.create(
            org=self.org,
            name=f"cobranca_{suffix}",
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
            external_id=f"named-{suffix}",
            parameter_names=names if names is not None else ["nome", "cota"],
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

    def test_optional_parameter_uses_filler_without_default(self):
        template, _ = self._named_template()
        template.parameter_policies = {"cota": {"required": False}}
        template.save(update_fields=["parameter_policies"])
        result = resolve_named_recipients(
            self.org,
            template,
            [{"urn": "whatsapp:5511888888888", "variables": {"nome": "Ana"}}],
            {},
        )
        self.assertEqual(" ", result["recipient_variables"]["whatsapp:5511888888888"]["cota"])

    def test_batch_and_extra_urns_and_ignored_names(self):
        template, _ = self._named_template()
        result = resolve_named_recipients(
            self.org,
            template,
            [{"urn": "whatsapp:5511999999999", "variables": {"campanha": "BF4", "nome": "João"}}],
            {"nome": "Padrão", "cota": "045"},
            extra_urns=["whatsapp:5511777777777"],
        )
        self.assertEqual(2, result["accepted_count"])
        self.assertEqual("045", result["recipient_variables"]["whatsapp:5511999999999"]["cota"])
        self.assertEqual("João", result["recipient_variables"]["whatsapp:5511999999999"]["nome"])
        self.assertNotIn("campanha", result["recipient_variables"]["whatsapp:5511999999999"])
        self.assertEqual("Padrão", result["recipient_variables"]["whatsapp:5511777777777"]["nome"])
        self.assertEqual("045", result["recipient_variables"]["whatsapp:5511777777777"]["cota"])

    def test_whitespace_value_is_not_provided(self):
        template, _ = self._named_template()
        with self.assertRaises(NamedTemplateBroadcastError):
            resolve_named_recipients(
                self.org,
                template,
                [{"urn": "whatsapp:5511888888888", "variables": {"nome": "Ana", "cota": "  "}}],
                {},
            )

    def test_duplicate_recipient_is_rejected(self):
        template, _ = self._named_template()
        with self.assertRaises(NamedTemplateBroadcastError) as ctx:
            resolve_named_recipients(
                self.org,
                template,
                [
                    {"urn": "whatsapp:5511999999999", "variables": {"nome": "A", "cota": "1"}},
                    {"urn": "whatsapp:5511999999999", "variables": {"nome": "B", "cota": "2"}},
                ],
                {},
            )
        self.assertIn("repeated", str(ctx.exception))

    def test_not_ready_without_parameter_names(self):
        template, _ = self._named_template(names=[])
        with self.assertRaises(NamedTemplateBroadcastError):
            resolve_named_recipients(self.org, template, [], {})

    def test_contact_field_fallback(self):
        template, _ = self._named_template()
        template.parameter_policies = {"cota": {"required": True, "contact_field": "cota"}}
        template.save(update_fields=["parameter_policies"])
        field = self.create_field("cota", "Cota")
        contact = self.create_contact("João", urns=["whatsapp:5511999999999"])
        self.set_contact_field(contact, "cota", "045")
        contact.refresh_from_db()
        self.assertEqual("045", contact.get_field_display(field))

        result = resolve_named_recipients(
            self.org,
            template,
            [{"urn": "whatsapp:5511999999999", "variables": {"nome": "João"}}],
            {},
        )
        self.assertEqual("045", result["recipient_variables"]["whatsapp:5511999999999"]["cota"])

    def test_required_null_in_policy_defaults_to_required(self):
        template, _ = self._named_template()
        template.parameter_policies = {"cota": {"required": None}}
        template.save(update_fields=["parameter_policies"])
        with self.assertRaises(NamedTemplateBroadcastError):
            resolve_named_recipients(
                self.org,
                template,
                [{"urn": "whatsapp:5511888888888", "variables": {"nome": "Ana"}}],
                {},
            )

    def test_declared_parameter_names_empty_and_disagreement(self):
        template = Template.objects.create(org=self.org, name="empty", parameter_format="named")
        self.assertEqual([], declared_parameter_names(template))

        template, channel = self._named_template()
        other = self.create_channel("WAC", "WA Cloud 2", "5678")
        TemplateTranslation.objects.create(
            template=template,
            channel=other,
            content="Olá {{nome}}",
            body="Olá {{nome}}",
            variable_count=1,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="named-2",
            parameter_names=["nome"],
        )
        with self.assertRaises(NamedTemplateBroadcastError) as ctx:
            declared_parameter_names(template)
        self.assertIn("eng", str(ctx.exception))

    def test_assert_named_template_ready(self):
        positional = Template.objects.create(org=self.org, name="pos", parameter_format="positional")
        self.assertIsNone(assert_named_template_ready(positional))

        template, channel = self._named_template()
        self.assertEqual(["nome", "cota"], assert_named_template_ready(template, channel=channel))

        template.parameter_format = "named"
        template.save(update_fields=["parameter_format"])
        TemplateTranslation.objects.filter(template=template).update(parameter_names=[])
        with self.assertRaises(NamedTemplateBroadcastError):
            assert_named_template_ready(template)

        template, channel = self._named_template()
        wwc = self.create_channel("WWC", "Chat", "chat-1")
        with self.assertRaises(NamedTemplateBroadcastError) as ctx:
            assert_named_template_ready(template, channel=wwc)
        self.assertIn(str(wwc.uuid), str(ctx.exception))

        wwc_template, _ = self._named_template(channel_type="WWC")
        with self.assertRaises(NamedTemplateBroadcastError):
            assert_named_template_ready(wwc_template, channel=None)


class NamedTemplateGetOrCreateTest(TembaTest):
    def test_preserves_names_when_caller_omits_them(self):
        channel = self.create_channel("WAC", "WA Cloud", "1234")
        created = TemplateTranslation.get_or_create(
            channel,
            "named_tpl",
            "por",
            "BR",
            "Olá {{nome}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "ext-named",
            "",
            "UTILITY",
            body="Olá {{nome}}",
            parameter_format="named",
            parameter_names=["nome"],
        )
        self.assertEqual("named", created.template.parameter_format)
        self.assertEqual(["nome"], created.parameter_names)

        updated = TemplateTranslation.get_or_create(
            channel,
            "named_tpl",
            "por",
            "BR",
            "Olá {{nome}}",
            1,
            TemplateTranslation.STATUS_APPROVED,
            "ext-named",
            "",
            "UTILITY",
            body="Olá {{nome}}",
        )
        updated.refresh_from_db()
        updated.template.refresh_from_db()
        self.assertEqual(TemplateTranslation.STATUS_APPROVED, updated.status)
        self.assertEqual("named", updated.template.parameter_format)
        self.assertEqual(["nome"], updated.parameter_names)

        updated = TemplateTranslation.get_or_create(
            channel,
            "named_tpl",
            "por",
            "BR",
            "Olá {{nome}} {{cota}}",
            2,
            TemplateTranslation.STATUS_APPROVED,
            "ext-named",
            "",
            "UTILITY",
            body="Olá {{nome}} {{cota}}",
            parameter_format="named",
            parameter_names=["nome", "cota"],
        )
        updated.refresh_from_db()
        self.assertEqual(["nome", "cota"], updated.parameter_names)


class NamedTemplateWriteSerializerTest(TembaTest):
    def _named_template(self):
        suffix = uuid4().hex[:8]
        channel = self.create_channel("WAC", f"WA {suffix}", suffix)
        template = Template.objects.create(org=self.org, name=f"cobranca_{suffix}", parameter_format="named")
        TemplateTranslation.objects.create(
            template=template,
            channel=channel,
            content="Olá {{nome}}, sua cota {{cota}}",
            body="Olá {{nome}}, sua cota {{cota}}",
            variable_count=2,
            status=TemplateTranslation.STATUS_APPROVED,
            language="por",
            external_id=f"named-ser-{suffix}",
            parameter_names=["nome", "cota"],
        )
        return template, channel

    def _serializer(self, data):
        return WhatsappBroadcastWriteSerializer(data=data, context={"org": self.org, "user": self.admin})

    def test_rejects_mixed_and_mismatched_shapes(self):
        template, channel = self._named_template()
        ser = self._serializer(
            {
                "channel": str(channel.uuid),
                "urns": ["whatsapp:5511999999999"],
                "msg": {
                    "template": {
                        "uuid": str(template.uuid),
                        "variables": ["João"],
                        "named_variables": {"nome": "João"},
                    }
                },
            }
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("named_variables and variables cannot be used together", str(ser.errors))

        ser = self._serializer(
            {
                "channel": str(channel.uuid),
                "urns": ["whatsapp:5511999999999"],
                "msg": {"template": {"uuid": str(template.uuid), "variables": ["João", "045"]}},
            }
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("expects named parameters", str(ser.errors))

        positional = Template.objects.create(org=self.org, name="pos", parameter_format="positional")
        TemplateTranslation.objects.create(
            template=positional,
            channel=channel,
            content="Hello {{1}}",
            body="Hello {{1}}",
            variable_count=1,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="pos-1",
        )
        ser = self._serializer(
            {
                "channel": str(channel.uuid),
                "urns": ["whatsapp:5511999999999"],
                "msg": {"template": {"uuid": str(positional.uuid), "named_variables": {"nome": "João"}}},
            }
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("expects positional variables", str(ser.errors))

    def test_validates_recipients_payload(self):
        template, channel = self._named_template()
        base = {
            "channel": str(channel.uuid),
            "msg": {"template": {"uuid": str(template.uuid), "named_variables": {"nome": "João", "cota": "1"}}},
        }

        ser = self._serializer({**base, "recipients": ["whatsapp:5511999999999"]})
        self.assertFalse(ser.is_valid())

        ser = self._serializer({**base, "recipients": [{"variables": {"nome": "João"}}]})
        self.assertFalse(ser.is_valid())

        ser = self._serializer(
            {
                **base,
                "recipients": [
                    {"urn": "whatsapp:5511999999999", "variables": {"nome": "A", "cota": "1"}},
                    {"urn": "whatsapp:5511999999999", "variables": {"nome": "B", "cota": "2"}},
                ],
            }
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("repeated", str(ser.errors))

        ser = self._serializer({**base, "recipients": [{"urn": "whatsapp:5511999999999", "variables": ["x"]}]})
        self.assertFalse(ser.is_valid())

        ser = self._serializer(
            {**base, "recipients": [{"urn": "whatsapp:5511999999999", "variables": {str(i): "v" for i in range(101)}}]}
        )
        self.assertFalse(ser.is_valid())

        ser = self._serializer(
            {
                "channel": str(channel.uuid),
                "urns": ["whatsapp:5511999999999"],
                "msg": {"template": {"uuid": str(template.uuid), "named_variables": ["João"]}},
            }
        )
        self.assertFalse(ser.is_valid())

    def test_rejects_unsupported_channel_and_unready_template(self):
        wwc = self.create_channel("WWC", "Chat", "chat-1")
        template, _ = self._named_template()
        TemplateTranslation.objects.create(
            template=template,
            channel=wwc,
            content="Olá {{nome}}, sua cota {{cota}}",
            body="Olá {{nome}}, sua cota {{cota}}",
            variable_count=2,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id="named-wwc",
            parameter_names=["nome", "cota"],
        )
        ser = self._serializer(
            {
                "channel": str(wwc.uuid),
                "urns": ["whatsapp:5511999999999"],
                "msg": {"template": {"uuid": str(template.uuid), "named_variables": {"nome": "João", "cota": "1"}}},
            }
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("does not support named parameters", str(ser.errors))

        unready, channel = self._named_template()
        TemplateTranslation.objects.filter(template=unready).update(parameter_names=[])
        ser = self._serializer(
            {
                "channel": str(channel.uuid),
                "urns": ["whatsapp:5511999999999"],
                "msg": {"template": {"uuid": str(unready.uuid), "named_variables": {"nome": "João"}}},
            }
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("not ready", str(ser.errors))

    @patch("temba.msgs.models.Broadcast.send_async")
    def test_named_broadcast_saves_recipient_variables_and_report(self, mock_send):
        template, channel = self._named_template()
        ser = self._serializer(
            {
                "channel": str(channel.uuid),
                "urns": ["whatsapp:5511777777777"],
                "msg": {"template": {"uuid": str(template.uuid), "named_variables": {"cota": "045"}}},
                "recipients": [
                    {"urn": "whatsapp:5511999999999", "variables": {"nome": "João", "campanha": "BF4"}},
                    {"urn": "whatsapp:5511888888888", "variables": {"nome": "Ana"}},
                ],
            }
        )
        self.assertTrue(ser.is_valid(), ser.errors)
        broadcast = ser.save()
        mock_send.assert_called_once()
        self.assertIsInstance(broadcast, Broadcast)
        metadata = broadcast.metadata
        self.assertEqual("named", metadata["template"]["parameter_format"])
        self.assertEqual("045", metadata["template"]["named_variables"]["cota"])
        self.assertEqual("João", metadata["template"]["recipient_variables"]["whatsapp:5511999999999"]["nome"])
        self.assertNotIn("campanha", metadata["template"]["recipient_variables"]["whatsapp:5511999999999"])
        self.assertEqual(2, metadata["named_parameters"]["accepted_count"])
        self.assertEqual(1, metadata["named_parameters"]["rejected_count"])
        self.assertEqual("nome", metadata["named_parameters"]["rejected"][0]["parameter"])
        self.assertEqual(["whatsapp:5511999999999", "whatsapp:5511888888888"], broadcast.raw_urns)

    def test_all_held_back_is_a_contract_error(self):
        template, channel = self._named_template()
        ser = self._serializer(
            {
                "channel": str(channel.uuid),
                "recipients": [{"urn": "whatsapp:5511888888888", "variables": {"nome": "Ana"}}],
                "msg": {"template": {"uuid": str(template.uuid)}},
            }
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("All recipients were held back", str(ser.errors))

    def test_read_serializers_publish_format_and_names(self):
        template, channel = self._named_template()
        translation = template.translations.get()
        read = TemplateReadSerializer(template).data
        self.assertEqual("named", read["parameter_format"])
        self.assertEqual(["nome", "cota"], read["translations"][0]["parameter_names"])

        details = TemplateTranslationDetailsSerializer(translation).data
        self.assertEqual("named", details["parameter_format"])
        self.assertEqual([{"name": "nome"}, {"name": "cota"}], details["parameters"])
        self.assertEqual(str(channel.uuid), details["channel"])
