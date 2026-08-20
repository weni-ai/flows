import logging
from typing import Optional

from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.messages import Message

from temba.channels.clients.integrations import (
    IntegrationsInternalClient,
    STATUS_ERROR,
    STATUS_SUCCESS,
)
from temba.channels.usecases.channel_migration import MigrateChannelUseCase
from temba.channels.usecases.exceptions import ChannelMigrationError


logger = logging.getLogger(__name__)


class ChannelMigratedConsumer(EDAConsumer):
    EVENT_TYPE = "integrations.channel.migrated"

    def consume(self, message: Message):  # pragma: no cover
        event = None
        try:
            event = message.event()
            if event.event_type != self.EVENT_TYPE:
                self.ack()
                return

            data = event.data
            project = data.get("project") or {}

            MigrateChannelUseCase().execute(
                channel_uuid=data["uuid"],
                project_from=project.get("from"),
                project_to=project["to"],
            )
            self._report_status(event.event_id, STATUS_SUCCESS)
            self.ack()
        except ChannelMigrationError as exception:
            if event:
                self._report_status(event.event_id, STATUS_ERROR, str(exception))
            self.ack()
        except Exception as exception:
            capture_exception(exception)
            if event:
                try:
                    self._report_status(event.event_id, STATUS_ERROR, str(exception))
                except Exception as callback_exception:
                    capture_exception(callback_exception)
            raise

    def _report_status(
        self,
        event_id,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        IntegrationsInternalClient().report_app_migration_status(
            event_id=event_id,
            status=status,
            error=error,
        )
