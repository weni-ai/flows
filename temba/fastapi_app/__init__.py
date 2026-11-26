# isort:skip_file
"""
FastAPI prototypes for benchmarking and optional dedicated processes.

Importing this package initializes Django when nothing has done it yet, so submodules can import ORM/serializers
normally at the top of the file. ``django.setup()`` is skipped when Django is already set up (the test runner, or any
process that imported Django first): it re-applies ``LOGGING``, whose ``disable_existing_loggers`` disables every
logger created so far.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "temba.settings")

import django  # noqa: E402
from django.apps import apps  # noqa: E402

if not apps.ready:
    django.setup()
