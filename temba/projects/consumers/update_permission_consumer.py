import amqp
from sentry_sdk import capture_exception

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers.json_parser import JSONParser
from temba.projects.usecases.permission_update import update_permission


class UpdatePermissionConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        print(f"[UpdatePermission] - Consuming a message. Body: {message.body}")
        try:
            body = JSONParser.parse(message.body)
            print(body)
            for data in body:
                print("BODYS")
                print(data)
                update_permission(
                    project_uuid=data.get("project"),  # project_uuid
                    action=data.get("action"),
                    user_email=data.get("user"),  # user_email
                    role=data.get("role"),
                )

                message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[UpdatePermission] - Message rejected by: {exception}")
