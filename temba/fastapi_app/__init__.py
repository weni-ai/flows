# isort:skip_file
"""
FastAPI prototypes for benchmarking and optional dedicated processes.

Importing this package eagerly initializes Django so submodules can import
ORM/serializers normally at the top of the file. ``django.setup()`` is
idempotent, so re-running it inside the test runner is a no-op.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "temba.settings")

import django  # noqa: E402

django.setup()
