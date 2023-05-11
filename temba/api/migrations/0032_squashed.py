# Generated by Django 2.2.10 on 2020-12-04 17:21

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("contacts", "0128_squashed"),
        ("api", "0031_squashed"),
    ]

    operations = [
        migrations.AddField(
            model_name="webhookresult",
            name="contact",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="webhook_results",
                to="contacts.Contact",
            ),
        ),
    ]
