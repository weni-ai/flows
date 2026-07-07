import os

from .settings_ci import *  # noqa

# -----------------------------------------------------------------------------------
# Mirrors settings_ci (tests run against a real PostGIS database, reused as the test
# database) but resolves the database and Redis hosts from the environment so the test
# runner can reach the service containers defined in docker/docker-compose.test.yml
# instead of the hardcoded "localhost".
# -----------------------------------------------------------------------------------
_db = DATABASES["default"]
_db["HOST"] = os.environ.get("POSTGRES_HOST", "database")
_db["PORT"] = os.environ.get("POSTGRES_PORT", "5432")
_db["NAME"] = os.environ.get("POSTGRES_DB", "temba")
_db["USER"] = os.environ.get("POSTGRES_USER", "temba")
_db["PASSWORD"] = os.environ.get("POSTGRES_PASSWORD", "temba")
_db["TEST"] = {"NAME": _db["NAME"]}

DATABASES = {"default": _db, "readonly": _db.copy()}

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

_redis_url = "redis://%s:%s/%s" % (REDIS_HOST, REDIS_PORT, REDIS_DB)  # noqa: F405
CACHES["default"]["LOCATION"] = _redis_url  # noqa: F405
CELERY_BROKER_URL = _redis_url
