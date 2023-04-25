# Generated by Django 2.2.10 on 2021-03-10 16:07

from django.db import migrations

import temba.utils.json
import temba.utils.models


class Migration(migrations.Migration):
    dependencies = [
        ("orgs", "0078_auto_20210208_1937"),
    ]

    operations = [
        migrations.AddField(
            model_name="org",
            name="limits",
            field=temba.utils.models.JSONField(default=dict, encoder=temba.utils.json.TembaEncoder),
        ),
    ]
