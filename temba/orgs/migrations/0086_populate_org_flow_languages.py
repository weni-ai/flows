# Generated by Django 2.2.20 on 2021-06-12 15:11

from django.db import migrations
from django.db.models import Prefetch


def populate_flow_languages(apps, schema_editor):  # pragma: no cover
    Org = apps.get_model("orgs", "Org")
    Language = apps.get_model("orgs", "Language")

    orgs = (
        Org.objects.filter(is_active=True, flow_languages__len=0)
        .select_related("primary_language")
        .prefetch_related(Prefetch("languages", Language.objects.order_by("id")))
    )

    for org in orgs:
        primary = []
        other = [lang.iso_code for lang in org.languages.all()]

        if org.primary_language:
            primary = [org.primary_language.iso_code]
            other.remove(org.primary_language.iso_code)

        org.flow_languages = primary + other
        org.save(update_fields=("flow_languages",))


def reverse(apps, schema_editor):  # pragma: no cover
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("orgs", "0085_org_flow_languages"),
    ]

    operations = [migrations.RunPython(populate_flow_languages, reverse)]
