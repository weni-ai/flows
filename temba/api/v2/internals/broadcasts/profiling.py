"""
Optional TraceForest profiling for selected broadcast endpoints.

Enable with env ``WHATSAPP_BROADCAST_TRACEFOREST=true`` (see ``settings_common``).
The name is WhatsApp-centric but the same flag gates ``BroadcastsEndpoint`` (``/api/v2/broadcasts``) profiling.

Labels used in staging:

- ``api_v2_broadcasts_endpoint_post`` — POST on ``BroadcastsEndpoint`` (``BroadcastWriteSerializer`` + response).
- ``internal_whatsapp_broadcast_sync`` — internal Django WhatsApp handler (resolve + write + read serializers).
- ``internal_whatsapp_broadcast_async`` — internal deferred enqueue handler.

Verbose call trees: ``WHATSAPP_BROADCAST_TRACEFOREST_VERBOSE=true`` (DEBUG logs; avoid high traffic).
"""

from __future__ import annotations

import io
import logging
import sys
import time
from contextlib import contextmanager
from typing import Generator

from django.conf import settings

logger = logging.getLogger(__name__)


@contextmanager
def traceforest_whatsapp_broadcast(label: str) -> Generator[None, None, None]:
    """
    Wrap a view/handler body to record wall-clock time until the response is built.

    When disabled (default), this is a no-op. When enabled but ``traceforest`` is missing,
    logs a warning once and acts as no-op.
    """
    enabled = getattr(settings, "WHATSAPP_BROADCAST_TRACEFOREST", False)
    if not enabled:
        yield
        return

    try:
        from traceforest import Profiler
        from traceforest.exporters.shell_exporter import ShellExporter
    except ImportError:
        logger.warning("WHATSAPP_BROADCAST_TRACEFOREST is on but traceforest is not installed.")
        yield
        return

    profiler = Profiler()
    t0 = time.perf_counter()
    profiler.start()
    err: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        err = exc
        raise
    finally:
        profiler.stop()
        wall_ms = (time.perf_counter() - t0) * 1000.0

        status = "exception" if err else "ok"
        logger.info(
            "whatsapp_broadcast_traceforest label=%s wall_ms=%.2f status=%s",
            label,
            wall_ms,
            status,
        )

        verbose = getattr(settings, "WHATSAPP_BROADCAST_TRACEFOREST_VERBOSE", False)
        if verbose:
            buf = io.StringIO()
            stdout, sys.stdout = sys.stdout, buf
            try:
                profiler.export(ShellExporter())
            finally:
                sys.stdout = stdout
            logger.debug("whatsapp_broadcast_traceforest label=%s tree:\n%s", label, buf.getvalue())
