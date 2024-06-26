# Generated by Django 3.2.9 on 2023-08-02 18:59

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="TemplateType",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uuid", models.UUIDField(editable=False, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("setup", models.JSONField(default=dict)),
            ],
        ),
    ]
