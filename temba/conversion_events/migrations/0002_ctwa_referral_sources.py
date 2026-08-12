# Generated manually for CTWA referral sources and expanded conversion events

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def backfill_ctwa_referral_sources(apps, schema_editor):
    CTWA = apps.get_model("conversion_events", "CTWA")
    CtwaReferralSource = apps.get_model("conversion_events", "CtwaReferralSource")

    for ctwa in CTWA.objects.filter(referral_source_id__isnull=True).iterator():
        source, _ = CtwaReferralSource.objects.get_or_create(
            source_id=f"legacy-{ctwa.id}",
            source_type="ad",
        )
        CTWA.objects.filter(id=ctwa.id).update(referral_source_id=source.id)


class Migration(migrations.Migration):

    dependencies = [
        ("conversion_events", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CtwaReferralSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_id", models.CharField(max_length=64)),
                ("source_type", models.CharField(choices=[("ad", "Ad"), ("post", "Post")], max_length=16)),
                ("source_url", models.TextField(blank=True, null=True)),
                ("headline", models.TextField(blank=True, null=True)),
                ("body", models.TextField(blank=True, null=True)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "ctwa_referral_sources",
            },
        ),
        migrations.AddConstraint(
            model_name="ctwareferralsource",
            constraint=models.UniqueConstraint(fields=("source_id", "source_type"), name="uq_ctwa_referral_source"),
        ),
        migrations.AddConstraint(
            model_name="ctwareferralsource",
            constraint=models.CheckConstraint(
                check=models.Q(source_type__in=["ad", "post"]),
                name="chk_ctwa_referral_source_type",
            ),
        ),
        migrations.AddIndex(
            model_name="ctwareferralsource",
            index=models.Index(fields=["source_id"], name="idx_ctwa_referral_sources_source_id"),
        ),
        migrations.AddIndex(
            model_name="ctwareferralsource",
            index=models.Index(fields=["-last_seen_at"], name="idx_ctwa_referral_sources_last_seen"),
        ),
        migrations.AddField(
            model_name="ctwa",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="ctwa",
            name="phone_number_id",
            field=models.CharField(blank=True, help_text="Phone number ID from webhook metadata", max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="ctwa",
            name="message_id",
            field=models.CharField(blank=True, help_text="WhatsApp message ID (wamid)", max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="ctwa",
            name="referral_source",
            field=models.ForeignKey(
                blank=True,
                db_column="referral_source_id",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="conversion_events",
                to="conversion_events.ctwareferralsource",
            ),
        ),
        migrations.AlterField(
            model_name="ctwa",
            name="ctwa_clid",
            field=models.CharField(
                blank=True,
                help_text="Click to WhatsApp Click ID",
                max_length=512,
                null=True,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="ctwa",
            name="timestamp",
            field=models.DateTimeField(help_text="Event timestamp from the webhook"),
        ),
        migrations.AlterField(
            model_name="ctwa",
            name="channel_uuid",
            field=models.UUIDField(help_text="Channel UUID"),
        ),
        migrations.RunPython(backfill_ctwa_referral_sources, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="ctwa",
            name="referral_source",
            field=models.ForeignKey(
                db_column="referral_source_id",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="conversion_events",
                to="conversion_events.ctwareferralsource",
            ),
        ),
        migrations.AddIndex(
            model_name="ctwa",
            index=models.Index(
                fields=["channel_uuid", "contact_urn", "-timestamp"],
                name="idx_conversion_events_ctwa_lookup",
            ),
        ),
        migrations.AddIndex(
            model_name="ctwa",
            index=models.Index(fields=["referral_source"], name="idx_conversion_events_ctwa_referral_source"),
        ),
        migrations.AddIndex(
            model_name="ctwa",
            index=models.Index(fields=["waba", "-timestamp"], name="idx_conversion_events_ctwa_waba"),
        ),
        migrations.RunSQL(
            sql="""
                CREATE INDEX idx_conversion_events_ctwa_clid
                ON conversion_events_ctwa (ctwa_clid)
                WHERE ctwa_clid IS NOT NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_conversion_events_ctwa_clid;",
        ),
    ]
