from django.db import migrations

# Prevent success-path status regressions (e.g. D -> S from out-of-order DLRs) on
# broadcast outbound messages, and guard sent/delivered/cost so each message is
# counted at most once per stage (same semantics as processed/read).

STATUS_RANK_FUNCTION = """
CREATE OR REPLACE FUNCTION msg_success_status_rank(s char) RETURNS int AS $$
BEGIN
    RETURN CASE s
        WHEN 'W' THEN 2
        WHEN 'S' THEN 3
        WHEN 'D' THEN 4
        WHEN 'V' THEN 5
        ELSE 0
    END;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
"""

MONOTONIC_STATUS_FUNCTION = """
CREATE OR REPLACE FUNCTION enforce_broadcast_msg_status_monotonicity()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.broadcast_id IS NULL OR NEW.direction <> 'O' THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE'
       AND OLD.status IN ('W', 'S', 'D', 'V')
       AND NEW.status IN ('W', 'S', 'D', 'V')
       AND msg_success_status_rank(NEW.status) < msg_success_status_rank(OLD.status) THEN
        NEW.status := OLD.status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

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
        -- count S on first reach, plus skip-paths for providers that omit S
        sent = sent + CASE
            WHEN NEW.status = 'S'
                 AND (TG_OP = 'INSERT' OR OLD.status NOT IN ('S', 'D', 'V')) THEN 1
            WHEN TG_OP = 'UPDATE' AND NEW.status = 'D' AND OLD.status IN ('Q', 'W') THEN 1
            WHEN TG_OP = 'UPDATE' AND NEW.status = 'V' AND OLD.status IN ('Q', 'W') THEN 1
            WHEN TG_OP = 'INSERT' AND NEW.status = 'V' THEN 1
            ELSE 0
        END,
        -- delivered on first reach of D, plus skip-paths when read arrives first
        delivered = delivered + CASE
            WHEN NEW.status = 'D'
                 AND (TG_OP = 'INSERT' OR OLD.status NOT IN ('D', 'V')) THEN 1
            WHEN TG_OP = 'UPDATE' AND NEW.status = 'V' AND OLD.status IN ('Q', 'W', 'S') THEN 1
            WHEN TG_OP = 'INSERT' AND NEW.status = 'V' THEN 1
            ELSE 0
        END,
        failed = failed + CASE WHEN NEW.status = 'F' THEN 1 ELSE 0 END,
        read = read + CASE
            WHEN NEW.status = 'V' AND TG_OP = 'INSERT' THEN 1
            WHEN NEW.status = 'V' AND TG_OP = 'UPDATE' AND (OLD.status IS DISTINCT FROM 'V') THEN 1
            ELSE 0
        END,
        processed = processed + CASE
            WHEN TG_OP = 'UPDATE' AND OLD.status = 'Q' AND NEW.status IN ('W', 'S', 'D', 'F', 'V') THEN 1
            WHEN TG_OP = 'INSERT' AND NEW.status IN ('W', 'S', 'D', 'F', 'V') THEN 1
            ELSE 0
        END,
        cost = COALESCE(cost, 0) + CASE
            WHEN NEW.status = 'S'
                 AND (TG_OP = 'INSERT' OR OLD.status NOT IN ('S', 'D', 'V'))
            THEN COALESCE(template_price, 0)
            ELSE 0
        END,
        modified_on = CASE
            WHEN TG_OP = 'UPDATE' AND OLD.status = 'Q' AND NEW.status IN ('W', 'S', 'D', 'F', 'V') THEN NOW()
            WHEN TG_OP = 'INSERT' AND NEW.status IN ('W', 'S', 'D', 'F', 'V') THEN NOW()
            ELSE modified_on
        END
    WHERE s.broadcast_id = NEW.broadcast_id;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

CREATE_MONOTONIC_TRIGGER = """
CREATE TRIGGER trg_enforce_broadcast_msg_status_monotonicity
BEFORE UPDATE OF status ON msgs_msg
FOR EACH ROW
WHEN (
    NEW.broadcast_id IS NOT NULL
    AND NEW.direction = 'O'
    AND OLD.status IS DISTINCT FROM NEW.status
)
EXECUTE FUNCTION enforce_broadcast_msg_status_monotonicity();
"""

RECREATE_STATISTICS_TRIGGERS = """
DROP TRIGGER IF EXISTS trg_update_broadcast_statistics_on_msg_status ON msgs_msg;
DROP TRIGGER IF EXISTS trg_update_broadcast_statistics_on_msg_status_insert ON msgs_msg;
CREATE TRIGGER trg_update_broadcast_statistics_on_msg_status
AFTER UPDATE OF status ON msgs_msg
FOR EACH ROW
WHEN (
    NEW.broadcast_id IS NOT NULL
    AND OLD.status IS DISTINCT FROM NEW.status
    AND NEW.status IN ('S', 'D', 'F', 'W', 'V')
)
EXECUTE FUNCTION update_broadcast_statistics_on_msg_status();

CREATE TRIGGER trg_update_broadcast_statistics_on_msg_status_insert
AFTER INSERT ON msgs_msg
FOR EACH ROW
WHEN (
    NEW.broadcast_id IS NOT NULL
    AND NEW.status IN ('S', 'D', 'F', 'W', 'V')
)
EXECUTE FUNCTION update_broadcast_statistics_on_msg_status();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS trg_enforce_broadcast_msg_status_monotonicity ON msgs_msg;
DROP FUNCTION IF EXISTS enforce_broadcast_msg_status_monotonicity();
DROP FUNCTION IF EXISTS msg_success_status_rank(char);
"""


class Migration(migrations.Migration):

    dependencies = [
        ("msgs", "0172_ensure_read_on_update_to_v"),
    ]

    operations = [
        migrations.RunSQL(STATUS_RANK_FUNCTION, reverse_sql=REVERSE_SQL),
        migrations.RunSQL(MONOTONIC_STATUS_FUNCTION),
        migrations.RunSQL(UPDATED_TRIGGER_FUNCTION),
        migrations.RunSQL(CREATE_MONOTONIC_TRIGGER),
        migrations.RunSQL(RECREATE_STATISTICS_TRIGGERS),
    ]
