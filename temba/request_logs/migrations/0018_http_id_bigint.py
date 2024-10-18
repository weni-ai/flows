from django.db import migrations

SQL = """
ALTER TABLE public.request_logs_httplog ADD COLUMN new_id BIGINT;

CREATE FUNCTION set_new_id() RETURNS TRIGGER AS
$BODY$
BEGIN
    NEW.new_id := NEW.id;
    RETURN NEW;
END
$BODY$ LANGUAGE PLPGSQL;

CREATE TRIGGER set_new_id_trigger
BEFORE INSERT OR UPDATE ON public.request_logs_httplog
FOR EACH ROW EXECUTE PROCEDURE set_new_id();

DO $$
DECLARE
    batch_size INTEGER := 10000;   -- Define o tamanho do batch
    min_id BIGINT;                 -- Armazena o menor valor de id no batch atual
    max_id BIGINT;                 -- Armazena o maior valor de id na tabela
    rows_updated INTEGER;          -- Contador de linhas atualizadas em cada batch
BEGIN

    SELECT MIN(id) INTO min_id FROM public.request_logs_httplog;

    SELECT MAX(id) INTO max_id FROM public.request_logs_httplog;

    WHILE min_id <= max_id LOOP

        UPDATE public.request_logs_httplog
        SET new_id = id
        WHERE id >= min_id AND id < min_id + batch_size
        AND new_id IS DISTINCT FROM id;

        GET DIAGNOSTICS rows_updated = ROW_COUNT;

        IF rows_updated = 0 THEN
            EXIT;
        END IF;

        min_id := min_id + batch_size;

        PERFORM pg_sleep(0.1);
    END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS new_id_unique ON public.request_logs_httplog(new_id);

ALTER TABLE public.request_logs_httplog ADD CONSTRAINT new_id_not_null CHECK (new_id IS NOT NULL) NOT VALID;

ALTER TABLE public.request_logs_httplog VALIDATE CONSTRAINT new_id_not_null;

BEGIN TRANSACTION;

LOCK TABLE public.request_logs_httplog IN EXCLUSIVE MODE;

ALTER TABLE public.request_logs_httplog
DROP CONSTRAINT request_logs_httplog_pkey,
ADD CONSTRAINT request_logs_httplog_pkey PRIMARY KEY USING INDEX new_id_unique;

ALTER SEQUENCE public.request_logs_httplog_id_seq OWNED BY public.request_logs_httplog.new_id;

ALTER TABLE public.request_logs_httplog ALTER COLUMN new_id SET DEFAULT nextval('public.request_logs_httplog_id_seq');

ALTER TABLE public.request_logs_httplog DROP COLUMN id;

ALTER TABLE public.request_logs_httplog RENAME COLUMN new_id TO id;

DROP TRIGGER IF EXISTS set_new_id_trigger ON public.request_logs_httplog;
DROP FUNCTION IF EXISTS set_new_id();

COMMIT;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("request_logs", "0017_httplog_contact"),
    ]

    operations = [migrations.RunSQL(SQL)]
