----------------------------------------------------------------------
-- Fix temba_insert_flowstartcount to check if start_id exists before inserting
-- This prevents foreign key constraint violations when FlowStarts are deleted
-- while FlowRuns are still being updated by the trim_flow_starts task
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION
  temba_insert_flowstartcount(_start_id INT, _count INT)
RETURNS VOID AS $$
BEGIN
  IF _start_id IS NOT NULL THEN
    -- Verificar se o start_id existe antes de inserir para evitar violação de FK
    IF EXISTS (SELECT 1 FROM flows_flowstart WHERE id = _start_id) THEN
      INSERT INTO flows_flowstartcount("start_id", "count", "is_squashed")
      VALUES(_start_id, _count, FALSE);
    END IF;
  END IF;
END;
$$ LANGUAGE plpgsql;
