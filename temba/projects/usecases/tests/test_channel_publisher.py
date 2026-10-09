from unittest.mock import patch

from temba.projects.usecases.channel_publisher import publish_channel_event
from temba.tests.base import TembaTest


class ChannelPublisherTestCase(TembaTest):
    @patch("temba.projects.usecases.channel_publisher.RabbitmqPublisher")
    def test_publish_channel_event(self, mock_rabbitmq_publisher):
        channel = self.create_channel(
            "WWC",
            "Weni Web Chat - Preview",
            "project-address",
            config={"preview": True},
        )

        publish_channel_event(channel, "create")

        mock_rabbitmq_publisher.return_value.send_message.assert_called_once_with(
            body={
                "action": "create",
                "uuid": str(channel.uuid),
                "project_uuid": str(channel.org.proj_uuid),
                "channel_type": "WWC",
                "is_live_desk_copilot": False,
            },
            exchange="channel-events.topic",
            routing_key="wwc-create",
        )

    @patch("temba.projects.usecases.channel_publisher.RabbitmqPublisher")
    def test_publish_channel_event_with_live_desk_copilot(self, mock_rabbitmq_publisher):
        channel = self.create_channel(
            "WWC",
            "Weni Web Chat - Copilot",
            "project-address-copilot",
            config={"is_live_desk_copilot": True},
        )

        publish_channel_event(channel, "create")

        mock_rabbitmq_publisher.return_value.send_message.assert_called_once_with(
            body={
                "action": "create",
                "uuid": str(channel.uuid),
                "project_uuid": str(channel.org.proj_uuid),
                "channel_type": "WWC",
                "is_live_desk_copilot": True,
            },
            exchange="channel-events.topic",
            routing_key="wwc-create",
        )
