# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.

# -----------------------------------------------------------------------------
# Python 3.10+ compatibility shim for legacy dependencies.
#
# Some older libraries (e.g. python-telegram-bot 11.x vendored urllib3) import
# Mapping / MutableMapping / Sequence from `collections`, which was moved to
# `collections.abc` in Python 3.10.
# We provide these aliases early in the import graph to avoid import errors.
# -----------------------------------------------------------------------------
import collections
import collections.abc

from .temba_celery import app as celery_app  # noqa

for _name in ("Mapping", "MutableMapping", "Sequence"):
    if not hasattr(collections, _name):
        setattr(collections, _name, getattr(collections.abc, _name))

