import logging
from typing import Optional, Union
from uuid import UUID

import requests

from django.conf import settings
from weni.internal.clients.base import BaseInternalClient

logger = logging.getLogger(__name__)

MODULE_FLOWS = "flows"
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"


class IntegrationsInternalClient(BaseInternalClient):
    def __init__(self, base_url=None, authenticator=None):
        base_url = base_url or getattr(settings, "INTEGRATIONS_BASE_URL", None)
        super().__init__(base_url=base_url, authenticator=authenticator)

    def report_app_migration_status(
        self,
        event_id: Union[UUID, str],
        status: str,
        error: Optional[str] = None,
    ) -> None:
        if not self.base_url:
            logger.warning("INTEGRATIONS_BASE_URL is not configured; skipping app migration status callback")
            return

        payload = {
            "module": MODULE_FLOWS,
            "status": status,
        }
        if error is not None:
            payload["error"] = error

        response = requests.post(
            self.get_url(f"/internals/app-migrations/{event_id}/status"),
            headers=self.authenticator.headers,
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
