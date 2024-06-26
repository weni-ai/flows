# Generated by Django 2.2.10 on 2020-12-04 17:21

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("campaigns", "0037_squashed"),
        ("orgs", "0072_squashed"),
    ]

    operations = [
        migrations.AddField(
            model_name="campaign",
            name="org",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="campaigns", to="orgs.Org"
            ),
        ),
    ]
