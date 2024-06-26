# Generated by Django 2.2.20 on 2021-07-09 19:12

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0038_squashed"),
    ]

    operations = [
        migrations.AlterField(
            model_name="campaign",
            name="group",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="campaigns", to="contacts.ContactGroup"
            ),
        ),
        migrations.AlterField(
            model_name="campaign",
            name="name",
            field=models.CharField(max_length=255),
        ),
    ]
