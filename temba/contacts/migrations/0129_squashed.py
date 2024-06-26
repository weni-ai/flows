# Generated by Django 2.2.10 on 2020-12-04 17:21

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("contacts", "0128_squashed"),
        ("channels", "0124_squashed"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orgs", "0072_squashed"),
    ]

    operations = [
        migrations.AddField(
            model_name="exportcontactstask",
            name="org",
            field=models.ForeignKey(
                help_text="The organization of the user.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="exportcontactstasks",
                to="orgs.Org",
            ),
        ),
        migrations.AddField(
            model_name="contacturn",
            name="channel",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="urns", to="channels.Channel"
            ),
        ),
        migrations.AddField(
            model_name="contacturn",
            name="contact",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="urns", to="contacts.Contact"
            ),
        ),
        migrations.AddField(
            model_name="contacturn",
            name="org",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="urns", to="orgs.Org"),
        ),
        migrations.AddField(
            model_name="contactimportbatch",
            name="contact_import",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="batches", to="contacts.ContactImport"
            ),
        ),
        migrations.AddField(
            model_name="contactimport",
            name="created_by",
            field=models.ForeignKey(
                help_text="The user which originally created this item",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contacts_contactimport_creations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="contactimport",
            name="group",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="imports",
                to="contacts.ContactGroup",
            ),
        ),
        migrations.AddField(
            model_name="contactimport",
            name="modified_by",
            field=models.ForeignKey(
                help_text="The user which last modified this item",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contacts_contactimport_modifications",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="contactimport",
            name="org",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="contact_imports", to="orgs.Org"
            ),
        ),
        migrations.AddField(
            model_name="contactgroupcount",
            name="group",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="counts", to="contacts.ContactGroup"
            ),
        ),
        migrations.AddField(
            model_name="contactgroup",
            name="contacts",
            field=models.ManyToManyField(related_name="all_groups", to="contacts.Contact"),
        ),
        migrations.AddField(
            model_name="contactgroup",
            name="created_by",
            field=models.ForeignKey(
                help_text="The user which originally created this item",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contacts_contactgroup_creations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="contactgroup",
            name="modified_by",
            field=models.ForeignKey(
                help_text="The user which last modified this item",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contacts_contactgroup_modifications",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="contactgroup",
            name="org",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="all_groups", to="orgs.Org"
            ),
        ),
        migrations.AddField(
            model_name="contactgroup", name="query_fields", field=models.ManyToManyField(to="contacts.ContactField")
        ),
        migrations.AddField(
            model_name="contactfield",
            name="created_by",
            field=models.ForeignKey(
                help_text="The user which originally created this item",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contacts_contactfield_creations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="contactfield",
            name="modified_by",
            field=models.ForeignKey(
                help_text="The user which last modified this item",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contacts_contactfield_modifications",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="contactfield",
            name="org",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="contactfields", to="orgs.Org"
            ),
        ),
        migrations.AddField(
            model_name="contact",
            name="created_by",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contacts_contact_creations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="contact",
            name="modified_by",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contacts_contact_modifications",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="contact",
            name="org",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="contacts", to="orgs.Org"
            ),
        ),
        migrations.AlterUniqueTogether(name="contacturn", unique_together={("identity", "org")}),
    ]
