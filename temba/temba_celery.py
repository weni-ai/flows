import os

from django.conf import settings

import celery

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "temba.settings")

app = celery.Celery("temba")

app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)
app.autodiscover_tasks(
    (
        "temba.channels.types.jiochat",
        "temba.channels.types.twitter",
        "temba.channels.types.wechat",
        "temba.channels.types.whatsapp",
        "temba.channels.types.teams",
    )
)

# TODO: Move logic to settings.py.prod or rapidpro-apps
app.conf.task_routes = {
    "create_recent_activity": {"queue": "async"},
}
