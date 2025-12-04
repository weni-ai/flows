from django.db import migrations

UPDATED_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION update_broadcast_statistics_on_msg_status()
RETURNS TRIGGER AS $$
BEGIN
    -- Guards
    IF NEW.broadcast_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status THEN
        RETURN NEW;
    END IF;

    -- Single UPDATE with CASE expressions; rely on existing stats rows (bulk sends only)
    UPDATE msgs_broadcaststatistics s
    SET
        -- count S normally, and also count Q->D and W->D as a send to cover providers that skip S
        -- also count Q/W -> V as a send (read implies sent when earlier events are skipped)
        sent = sent + CASE
            WHEN NEW.status = 'S' THEN 1
            WHEN TG_OP = 'UPDATE' AND NEW.status = 'D' AND OLD.status IN ('Q','W') THEN 1
            WHEN TG_OP = 'UPDATE' AND NEW.status = 'V' AND OLD.status IN ('Q','W') THEN 1
            WHEN TG_OP = 'INSERT' AND NEW.status = 'V' THEN 1
            ELSE 0
        END,
        -- delivered on D always, and on S/Q/W -> V (read implies delivered if D was skipped)
        delivered = delivered + CASE
            WHEN NEW.status = 'D' THEN 1
            WHEN TG_OP = 'UPDATE' AND NEW.status = 'V' AND OLD.status IN ('Q','W','S') THEN 1
            WHEN TG_OP = 'INSERT' AND NEW.status = 'V' THEN 1
            ELSE 0
        END,
        failed = failed + CASE WHEN NEW.status = 'F' THEN 1 ELSE 0 END,
        read = read + CASE WHEN NEW.status = 'V' THEN 1 ELSE 0 END,
        -- processed should increment exactly once when leaving Q, or if inserted already processed
        processed = processed + CASE
            WHEN TG_OP = 'UPDATE' AND OLD.status = 'Q' AND NEW.status IN ('W','S','D','F','V') THEN 1
            WHEN TG_OP = 'INSERT' AND NEW.status IN ('W','S','D','F','V') THEN 1
            ELSE 0
        END,
        cost = COALESCE(cost, 0) + CASE WHEN NEW.status = 'S' THEN COALESCE(template_price, 0) ELSE 0 END,
        modified_on = CASE
            WHEN TG_OP = 'UPDATE' AND OLD.status = 'Q' AND NEW.status IN ('W','S','D','F','V') THEN NOW()
            WHEN TG_OP = 'INSERT' AND NEW.status IN ('W','S','D','F','V') THEN NOW()
            ELSE modified_on
        END
    WHERE s.broadcast_id = NEW.broadcast_id;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


RECREATE_TRIGGERS = """
DROP TRIGGER IF EXISTS trg_update_broadcast_statistics_on_msg_status ON msgs_msg;
DROP TRIGGER IF EXISTS trg_update_broadcast_statistics_on_msg_status_insert ON msgs_msg;
CREATE TRIGGER trg_update_broadcast_statistics_on_msg_status
AFTER UPDATE OF status ON msgs_msg
FOR EACH ROW
WHEN (
    NEW.broadcast_id IS NOT NULL
    AND OLD.status IS DISTINCT FROM NEW.status
    AND NEW.status IN ('S','D','F','W','V')
)
EXECUTE FUNCTION update_broadcast_statistics_on_msg_status();

CREATE TRIGGER trg_update_broadcast_statistics_on_msg_status_insert
AFTER INSERT ON msgs_msg
FOR EACH ROW
WHEN (
    NEW.broadcast_id IS NOT NULL
    AND NEW.status IN ('S','D','F','W','V')
)
EXECUTE FUNCTION update_broadcast_statistics_on_msg_status();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("msgs", "0170_optimize_broadcast_status_trigger"),
    ]

    operations = [
        migrations.RunSQL(UPDATED_TRIGGER_FUNCTION),
        migrations.RunSQL(RECREATE_TRIGGERS),
    ]
