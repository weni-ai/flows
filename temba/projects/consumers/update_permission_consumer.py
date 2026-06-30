import logging

import amqp
from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

from temba.projects.usecases.permission_update import update_permission

logger = logging.getLogger(__name__)


class UpdatePermissionConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            logger.info("[UpdatePermissionConsumer] Received message")
            body = JSONParser.parse(message.body)

            logger.info(
                "[UpdatePermissionConsumer] Processing project_uuid=%s action=%s user_email=%s role=%s",
                body.get("project"),
                body.get("action"),
                body.get("user"),
                body.get("role"),
            )

            update_permission(
                project_uuid=body.get("project"),  # project_uuid
                action=body.get("action"),
                user_email=body.get("user"),  # user_email
                role=body.get("role"),
            )

            self.ack()
            logger.info(
                "[UpdatePermissionConsumer] Message processed successfully project_uuid=%s action=%s",
                body.get("project"),
                body.get("action"),
            )
        except Exception as exception:
            logger.exception("[UpdatePermissionConsumer] Failed to process message")
            capture_exception(exception)
            raise
