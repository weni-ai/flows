# Generated by Django 3.2.9 on 2022-01-17 20:36

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("flows", "0266_auto_20220113_1706"),
        ("contacts", "0143_auto_20210908_2224"),
    ]

    operations = [
        migrations.AddField(
            model_name="contact",
            name="current_flow",
            field=models.ForeignKey(
                db_index=False, null=True, on_delete=django.db.models.deletion.PROTECT, to="flows.flow"
            ),
        ),
    ]