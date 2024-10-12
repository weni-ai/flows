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
CREATE TRIGGER set_new_id_trigger BEFORE INSERT OR UPDATE ON public.request_logs_httplog
FOR EACH ROW EXECUTE PROCEDURE set_new_id();

UPDATE public.request_logs_httplog SET new_id = id;

CREATE UNIQUE INDEX IF NOT EXISTS new_id_unique ON public.request_logs_httplog(new_id);

ALTER TABLE public.request_logs_httplog ADD CONSTRAINT new_id_not_null CHECK (new_id IS NOT NULL) NOT VALID;

ALTER TABLE public.request_logs_httplog VALIDATE CONSTRAINT new_id_not_null;


BEGIN TRANSACTION;

-- explicitly lock the table against other changes (safety)
LOCK TABLE public.request_logs_httplog IN EXCLUSIVE MODE;

-- drop and create the PK using existing index
ALTER TABLE public.request_logs_httplog DROP CONSTRAINT request_logs_httplog_pkey, ADD CONSTRAINT request_logs_httplog_pkey PRIMARY KEY USING INDEX new_id_unique;

-- transfer the sequence
ALTER SEQUENCE public.request_logs_httplog_id_seq OWNED BY public.request_logs_httplog.new_id;
ALTER TABLE public.request_logs_httplog ALTER COLUMN new_id SET DEFAULT nextval('public.request_logs_httplog_id_seq');

-- drop and rename the columns
ALTER TABLE public.request_logs_httplog DROP COLUMN id;
ALTER TABLE public.request_logs_httplog RENAME COLUMN new_id TO id;

-- drop the temporary trigger and procedure
DROP TRIGGER IF EXISTS set_new_id_trigger ON public.request_logs_httplog;
DROP FUNCTION IF EXISTS set_new_id();

COMMIT;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("request_logs", "0017_httplog_contact"),
    ]

    operations = [migrations.RunSQL(SQL)]
