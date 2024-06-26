# Generated by Django 2.2.10 on 2020-12-10 17:27

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("msgs", "0145_auto_20210101_1559"),
        ("orgs", "0072_squashed"),
    ]

    operations = [
        migrations.AddField(
            model_name="org",
            name="agents",
            field=models.ManyToManyField(related_name="org_agents", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="org",
            name="administrators",
            field=models.ManyToManyField(related_name="org_admins", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="org",
            name="editors",
            field=models.ManyToManyField(related_name="org_editors", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="org",
            name="surveyors",
            field=models.ManyToManyField(related_name="org_surveyors", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="org",
            name="viewers",
            field=models.ManyToManyField(related_name="org_viewers", to=settings.AUTH_USER_MODEL),
        ),
    ]
