# Generated by Django 2.2.20 on 2021-07-27 17:16

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0015_auto_20210726_1923"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticketevent",
            name="note",
            field=models.TextField(max_length=4096, null=True),
        ),
    ]
