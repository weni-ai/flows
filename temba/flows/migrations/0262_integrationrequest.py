# Generated by Django 3.2.17 on 2023-08-24 14:29

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('internal', '0002_project'),
        ('flows', '0261_alter_flowrun_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='IntegrationRequest',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('integration_uuid', models.UUIDField()),
                ('name', models.CharField(max_length=50)),
                ('repository', models.UUIDField(null=True)),
                ('flow', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='integrations_requests', to='flows.flow')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='integrations_requests', to='internal.project')),
            ],
        ),
    ]
