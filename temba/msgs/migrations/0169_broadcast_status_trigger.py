from django.db import migrations

TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION update_broadcast_statistics_on_msg_status()
RETURNS TRIGGER AS $$
BEGIN
    -- Only process if the broadcast_id or status changed
    IF NEW.broadcast_id IS NULL OR NEW.status IS NOT DISTINCT FROM OLD.status THEN
        RETURN NEW;
    END IF;

    -- Only process for bulk sends
    IF NOT EXISTS (
        SELECT 1 FROM msgs_broadcast b WHERE b.id = NEW.broadcast_id AND b.is_bulk_send
    ) THEN
        RETURN NEW;
    END IF;

    IF NEW.status = 'S' THEN
        UPDATE msgs_broadcaststatistics
        SET sent = sent + 1,
            cost = COALESCE(cost, 0) + COALESCE(template_price, 0)
        WHERE broadcast_id = NEW.broadcast_id;

    ELSIF NEW.status = 'D' THEN
        UPDATE msgs_broadcaststatistics
        SET delivered = delivered + 1
        WHERE broadcast_id = NEW.broadcast_id;

    ELSIF NEW.status = 'F' THEN
        UPDATE msgs_broadcaststatistics
        SET failed = failed + 1
        WHERE broadcast_id = NEW.broadcast_id;

        -- If it failed directly from the queue, consider it as 'processed'
        IF OLD.status = 'Q' THEN
            UPDATE msgs_broadcaststatistics
            SET processed = processed + 1,
                modified_on = NOW()
            WHERE broadcast_id = NEW.broadcast_id;
        END IF;

    ELSIF NEW.status = 'W' THEN
        UPDATE msgs_broadcaststatistics
        SET processed = processed + 1,
            modified_on = NOW()
        WHERE broadcast_id = NEW.broadcast_id;

    ELSIF NEW.status = 'V' THEN
        UPDATE msgs_broadcaststatistics
        SET read = read + 1
        WHERE broadcast_id = NEW.broadcast_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER trg_update_broadcast_statistics_on_msg_status
AFTER UPDATE OF status ON msgs_msg
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
