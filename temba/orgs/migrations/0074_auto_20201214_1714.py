# Generated by Django 2.2.10 on 2020-12-14 17:14

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orgs", "0073_auto_20201210_1727"),
    ]

    operations = [
        migrations.AlterField(model_name="invitation", name="email", field=models.EmailField(max_length=254)),
        migrations.AlterField(
            model_name="invitation",
            name="org",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="invitations", to="orgs.Org"
            ),
        ),
        migrations.AlterField(
            model_name="invitation", name="secret", field=models.CharField(max_length=64, unique=True)
        ),
        migrations.AlterField(
            model_name="invitation",
            name="user_group",
            field=models.CharField(
                choices=[("A", "Administrator"), ("E", "Editor"), ("V", "Viewer"), ("T", "Agent"), ("S", "Surveyor")],
                default="V",
                max_length=1,
            ),
        ),
    ]
