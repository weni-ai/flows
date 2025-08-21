from rest_framework import serializers

from temba.templates.models import TemplateTranslation


class TemplateHeaderSerializer(serializers.Serializer):
    type = serializers.CharField()
    text = serializers.CharField(allow_null=True)


class TemplateButtonSerializer(serializers.Serializer):
    type = serializers.CharField()
    text = serializers.CharField(allow_null=True)
    country_code = serializers.IntegerField(allow_null=True)
    phone_number = serializers.CharField(allow_null=True)
    url = serializers.CharField(allow_null=True)


class TemplateTranslationDetailsSerializer(serializers.Serializer):
    name = serializers.CharField()
    uuid = serializers.CharField()
    category = serializers.CharField(allow_null=True)
    created_on = serializers.DateTimeField(required=False)
    language = serializers.CharField()
    header = TemplateHeaderSerializer(allow_null=True)
    body = serializers.DictField()
    footer = serializers.DictField(allow_null=True)
    buttons = TemplateButtonSerializer(many=True)

    def to_representation(self, instance: TemplateTranslation):
        header_obj = None
        if hasattr(instance, "headers"):
            header = next(iter(instance.headers.all()), None)
            if header:
                header_obj = dict(type=header.type, text=header.text)

        body_obj = dict(text=instance.body or "")
        footer_obj = dict(text=instance.footer) if instance.footer else None

        buttons = []
        for b in instance.buttons.all():
            buttons.append(
                dict(
                    type=b.type,
                    text=b.text,
                    country_code=b.country_code,
                    phone_number=b.phone_number,
                    url=b.url,
                )
            )

        return dict(
            name=instance.template.name,
            uuid=str(instance.template.uuid),
            category=instance.template.category,
            created_on=instance.template.created_on,
            language=instance.language,
            header=header_obj,
            body=body_obj,
            footer=footer_obj,
            buttons=buttons,
        )
