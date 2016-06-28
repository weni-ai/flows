# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('orgs', '0019_org_surveyor_password'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AirtimeEvent',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('is_active', models.BooleanField(default=True, help_text='Whether this item is active, use this instead of deleting')),
                ('created_on', models.DateTimeField(help_text='When this item was originally created', auto_now_add=True)),
                ('modified_on', models.DateTimeField(help_text='When this item was last modified', auto_now=True)),
                ('phone_number', models.CharField(max_length=64)),
                ('amount', models.FloatField()),
                ('denomination', models.CharField(max_length=32, null=True, blank=True)),
                ('dump_content', models.TextField(null=True, blank=True)),
                ('data_json', models.TextField(null=True, blank=True)),
                ('created_by', models.ForeignKey(related_name='events_airtimeevent_creations', to=settings.AUTH_USER_MODEL, help_text='The user which originally created this item')),
                ('modified_by', models.ForeignKey(related_name='events_airtimeevent_modifications', to=settings.AUTH_USER_MODEL, help_text='The user which last modified this item')),
                ('org', models.ForeignKey(to='orgs.Org')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='TransferAirtime',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('is_active', models.BooleanField(default=True, help_text='Whether this item is active, use this instead of deleting')),
                ('created_on', models.DateTimeField(help_text='When this item was originally created', auto_now_add=True)),
                ('modified_on', models.DateTimeField(help_text='When this item was last modified', auto_now=True)),
                ('transaction_id', models.CharField(max_length=256)),
                ('error_code', models.CharField(max_length=64, null=True, blank=True)),
                ('error_txt', models.CharField(max_length=512, null=True, blank=True)),
                ('reference_operator', models.CharField(max_length=64, null=True, blank=True)),
                ('airtime_amount', models.CharField(max_length=32, null=True, blank=True)),
                ('dump_content', models.TextField(null=True, blank=True)),
                ('data_json', models.TextField(null=True, blank=True)),
                ('created_by', models.ForeignKey(related_name='events_transferairtime_creations', to=settings.AUTH_USER_MODEL, help_text='The user which originally created this item')),
                ('event', models.ForeignKey(to='events.AirtimeEvent')),
                ('modified_by', models.ForeignKey(related_name='events_transferairtime_modifications', to=settings.AUTH_USER_MODEL, help_text='The user which last modified this item')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
