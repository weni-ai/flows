from django.db import migrations

TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION update_broadcast_statistics_on_msg_status()
RETURNS TRIGGER AS $$
BEGIN
    -- Only process if broadcast_id is not null and status changed
    IF NEW.broadcast_id IS NOT NULL AND NEW.status IS DISTINCT FROM OLD.status THEN
        -- Increment the sent field if status changed to 'S'
        IF NEW.status = 'S' THEN
            UPDATE msgs_broadcaststatistics
            SET sent = sent + 1
            WHERE broadcast_id = NEW.broadcast_id;
        END IF;

        -- Increment the delivered field if status changed to 'D'
        IF NEW.status = 'D' THEN
            UPDATE msgs_broadcaststatistics
            SET delivered = delivered + 1
            WHERE broadcast_id = NEW.broadcast_id;
        END IF;

        -- Increment the failed field if status changed to 'F'
        IF NEW.status = 'F' THEN
            UPDATE msgs_broadcaststatistics
            SET failed = failed + 1
            WHERE broadcast_id = NEW.broadcast_id;
        END IF;

        -- Increment the processed field if status changed to 'Q'
        IF NEW.status = 'Q' THEN
            UPDATE msgs_broadcaststatistics
            SET processed = processed + 1
            WHERE broadcast_id = NEW.broadcast_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER trg_update_broadcast_statistics_on_msg_status
AFTER INSERT OR UPDATE OF status ON msgs_msg
FOR EACH ROW
EXECUTE FUNCTION update_broadcast_statistics_on_msg_status();
"""

DROP_TRIGGER = """
DROP TRIGGER IF EXISTS trg_update_broadcast_statistics_on_msg_status ON msgs_msg;
DROP FUNCTION IF EXISTS update_broadcast_statistics_on_msg_status();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("msgs", "0168_broadcaststatistics"),
    ]

    operations = [
        migrations.RunSQL(TRIGGER_FUNCTION, DROP_TRIGGER),
        migrations.RunSQL(TRIGGER, DROP_TRIGGER),
    ]
