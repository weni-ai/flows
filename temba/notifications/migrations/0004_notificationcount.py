# Generated by Django 3.2.7 on 2021-09-14 16:22

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def delete_all_notifications(apps, schema_editor):  # pragma: no cover
    apps.get_model("notifications", "Notification").objects.all().delete()


SQL = """
----------------------------------------------------------------------
-- Inserts a new notificationcount row with the given values
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION temba_insert_notificationcount(_org_id INT, _user_id INT, _count INT) RETURNS VOID AS $$
BEGIN
  INSERT INTO notifications_notificationcount("org_id", "user_id", "count", "is_squashed")
  VALUES(_org_id, _user_id, _count, FALSE);
END;
$$ LANGUAGE plpgsql;

----------------------------------------------------------------------
-- Trigger procedure to notification counts on notification changes
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION temba_notification_on_change() RETURNS TRIGGER AS $$
BEGIN
  IF TG_OP = 'INSERT' AND NOT NEW.is_seen THEN -- new notification inserted
    PERFORM temba_insert_notificationcount(NEW.org_id, NEW.user_id, 1);
  ELSIF TG_OP = 'UPDATE' THEN -- existing notification updated
    IF OLD.is_seen AND NOT NEW.is_seen THEN -- becoming unseen again
      PERFORM temba_insert_notificationcount(NEW.org_id, NEW.user_id, 1);
    ELSIF NOT OLD.is_seen AND NEW.is_seen THEN -- becoming seen
      PERFORM temba_insert_notificationcount(NEW.org_id, NEW.user_id, -1);
    END IF;
  ELSIF TG_OP = 'DELETE' AND NOT OLD.is_seen THEN -- existing notification deleted
    PERFORM temba_insert_notificationcount(OLD.org_id, OLD.user_id, -1);
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER temba_notifications_update_notificationcount
  AFTER INSERT OR UPDATE OF is_seen OR DELETE
  ON notifications_notification
  FOR EACH ROW EXECUTE PROCEDURE temba_notification_on_change();
"""


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orgs", "0088_auto_20210715_1825"),
        ("notifications", "0003_delete_log"),
    ]

    operations = [
        migrations.RunPython(delete_all_notifications),
        migrations.CreateModel(
            name="NotificationCount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("is_squashed", models.BooleanField(default=False)),
                ("count", models.IntegerField(default=0)),
                (
                    "org",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="notification_counts", to="orgs.org"
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="notification_counts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.RunSQL(SQL),
    ]
