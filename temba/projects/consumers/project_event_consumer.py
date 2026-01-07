import amqp
from sentry_sdk import capture_exception

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers.json_parser import JSONParser
from temba.projects.usecases.project_delete import delete_project
from temba.projects.usecases.project_status_update import update_project_status
from temba.projects.usecases.project_update import update_project_config


class ProjectEventConsumer(EDAConsumer):
    """
    Consumer for handling project events (update, delete, and status update).

    Handles messages from update-projects.topic exchange.
    Events are differentiated by the 'action' field:
    - action: "deleted" -> calls delete_project
    - action: "updated" -> calls update_project_config
    - action: "status_updated" -> calls update_project_status
    """

    def consume(self, message: amqp.Message):  # pragma: no cover
        print(f"[ProjectEventConsumer] - Consuming a message. Body: {message.body}")
        try:
            body = JSONParser.parse(message.body)

            self._validate_message(body)

            project_uuid = body.get("project_uuid")
            user_email = body.get("user_email")
            action = body.get("action")

            # Process based on action
            self._process_event(project_uuid, user_email, action, body)

            message.channel.basic_ack(message.delivery_tag)
            print(f"[ProjectEventConsumer] - Successfully processed {action} for project {project_uuid}")

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[ProjectEventConsumer] - Message rejected by: {exception}")

    def _validate_message(self, body):
        """Validate that all required fields are present in the message."""
        required_fields = ["project_uuid", "action", "user_email"]

        for field in required_fields:
            if not body.get(field):
                raise ValueError(f"Missing required field: {field}")

        action = body.get("action")
        if action not in ["deleted", "updated", "status_updated"]:
            raise ValueError(f"Invalid action: {action}. Must be 'deleted', 'updated', or 'status_updated'")

        # Validate status field for status_updated action
        if action == "status_updated":
            status = body.get("status")
            if not status:
                raise ValueError("Missing required field 'status' for status_updated action")
            if status not in ["ACTIVE", "IN_TEST", "INACTIVE"]:
                raise ValueError(f"Invalid status: {status}. Must be 'ACTIVE', 'IN_TEST', or 'INACTIVE'")

    def _process_event(self, project_uuid: str, user_email: str, action: str, body: dict):
        """
        Process the project event based on action.

        Args:
            project_uuid: UUID of the project
            user_email: Email of the user performing the action
            action: Action to perform ('deleted', 'updated', or 'status_updated')
            body: Full message body
        """
        try:
            if action == "deleted":
                org = delete_project(
                    project_uuid=project_uuid,
                    user_email=user_email,
                )

                if org:
                    print(f"[ProjectEventConsumer] - Successfully deleted project '{org.name}' ({project_uuid})")
                else:
                    print(f"[ProjectEventConsumer] - Project {project_uuid} not found for deletion")

            elif action == "updated":
                org = update_project_config(
                    project_uuid=project_uuid,
                    user_email=user_email,
                    name=body.get("name"),
                    description=body.get("description"),
                    language=body.get("language"),
                )

                if org:
                    print(f"[ProjectEventConsumer] - Successfully updated project '{org.name}' ({project_uuid})")
                else:
                    print(f"[ProjectEventConsumer] - Project {project_uuid} not found for update")

            elif action == "status_updated":
                status = body.get("status")
                org = update_project_status(
                    project_uuid=project_uuid,
                    status=status,
                    user_email=user_email,
                )

                if org:
                    print(
                        f"[ProjectEventConsumer] - Successfully updated project '{org.name}' ({project_uuid}) "
                        f"status to {status} (is_active={org.is_active})"
                    )
                else:
                    print(f"[ProjectEventConsumer] - Project {project_uuid} not found for status update")

            else:
                raise ValueError(f"Unknown action: {action}")

        except Exception as e:
            print(f"[ProjectEventConsumer] - Error processing {action} for project {project_uuid}: {e}")
            raise
