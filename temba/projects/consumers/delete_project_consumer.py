import amqp
from sentry_sdk import capture_exception

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers.json_parser import JSONParser
from temba.projects.usecases.project_delete import delete_project


class DeleteProjectConsumer(EDAConsumer):
    """
    Consumer for handling project deletion events.

    Handles messages from update-projects.topic exchange with routing key:
    - project.deleted
    """

    def consume(self, message: amqp.Message):  # pragma: no cover
        print(f"[DeleteProjectConsumer] - Consuming a message. Body: {message.body}")
        try:
            body = JSONParser.parse(message.body)

            project_uuid = body.get("project_uuid")
            user_email = body.get("user_email")

            if not project_uuid:
                raise ValueError("Missing required field: project_uuid")

            if not user_email:
                raise ValueError("Missing required field: user_email")

            action = body.get("action")
            if action != "deleted":
                raise ValueError(f"Invalid action for DeleteProjectConsumer: {action}")

            org = delete_project(
                project_uuid=project_uuid,
                user_email=user_email,
            )

            if org:
                print(f"[DeleteProjectConsumer] - Successfully deleted project '{org.name}' ({project_uuid})")
            else:
                print(f"[DeleteProjectConsumer] - Project {project_uuid} not found")

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[DeleteProjectConsumer] - Message rejected by: {exception}")

