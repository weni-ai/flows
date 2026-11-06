import json
import uuid
from unittest.mock import Mock, patch

from weni.eda.events import Event
from weni.eda.messages import Message

from temba.channels.consumers.channel_migrated_consumer import ChannelMigratedConsumer
from temba.channels.usecases.exceptions import ChannelNotFoundError
from temba.tests.base import TembaTest


class TestChannelMigratedConsumer(TembaTest):
    EVENT_TYPE = "integrations.channel.migrated"

    def _create_message(self, data, event_type=None, event_id=None):
        channel = Mock()
        envelope = Event.build(event_type or self.EVENT_TYPE, data).to_dict()
        if event_id is not None:
            envelope["event_id"] = event_id
        message = Message(
            body=json.dumps(envelope, default=str).encode(),
            delivery_tag="test-delivery-tag",
            channel=channel,
        )
        return message, channel

    @patch("temba.channels.consumers.channel_migrated_consumer.IntegrationsInternalClient")
    @patch("temba.channels.consumers.channel_migrated_consumer.MigrateChannelUseCase")
    def test_consume_success_reports_status_and_acks(
        self,
        mock_use_case_cls,
        mock_client_cls,
    ):
        mock_use_case = Mock()
        mock_use_case_cls.return_value = mock_use_case
        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        event_id = str(uuid.uuid4())
        channel_uuid = str(uuid.uuid4())
        data = {
            "uuid": channel_uuid,
            "app_uuid": str(uuid.uuid4()),
            "project": {
                "from": str(uuid.uuid4()),
                "to": str(uuid.uuid4()),
            },
        }
        message, channel = self._create_message(data, event_id=event_id)
        consumer = ChannelMigratedConsumer()
        consumer._message = message

        consumer.consume(message)

        mock_use_case.execute.assert_called_once_with(
            channel_uuid=channel_uuid,
            project_from=data["project"]["from"],
            project_to=data["project"]["to"],
        )
        mock_client.report_app_migration_status.assert_called_once_with(
            event_id=event_id,
            status="success",
            error=None,
        )
        channel.basic_ack.assert_called_once_with(message.delivery_tag)

    @patch("temba.channels.consumers.channel_migrated_consumer.IntegrationsInternalClient")
    @patch("temba.channels.consumers.channel_migrated_consumer.MigrateChannelUseCase")
    def test_consume_domain_error_reports_error_and_acks(
        self,
        mock_use_case_cls,
        mock_client_cls,
    ):
        mock_use_case = Mock()
        mock_use_case.execute.side_effect = ChannelNotFoundError("missing-channel")
        mock_use_case_cls.return_value = mock_use_case
        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        event_id = str(uuid.uuid4())
        data = {
            "uuid": "missing-channel",
            "app_uuid": str(uuid.uuid4()),
            "project": {
                "from": str(uuid.uuid4()),
                "to": str(uuid.uuid4()),
            },
        }
        message, channel = self._create_message(data, event_id=event_id)
        consumer = ChannelMigratedConsumer()
        consumer._message = message

        consumer.consume(message)

        mock_client.report_app_migration_status.assert_called_once_with(
            event_id=event_id,
            status="error",
            error="Channel not found: missing-channel",
        )
        channel.basic_ack.assert_called_once_with(message.delivery_tag)

    @patch("temba.channels.consumers.channel_migrated_consumer.IntegrationsInternalClient")
    @patch("temba.channels.consumers.channel_migrated_consumer.MigrateChannelUseCase")
    def test_consume_ignores_unsupported_event_type(
        self,
        mock_use_case_cls,
        mock_client_cls,
    ):
        data = {
            "uuid": str(uuid.uuid4()),
            "project": {"from": str(uuid.uuid4()), "to": str(uuid.uuid4())},
        }
        message, channel = self._create_message(data, event_type="project.created")
        consumer = ChannelMigratedConsumer()
        consumer._message = message

        consumer.consume(message)

        mock_use_case_cls.return_value.execute.assert_not_called()
        mock_client_cls.return_value.report_app_migration_status.assert_not_called()
        channel.basic_ack.assert_called_once_with(message.delivery_tag)

    @patch("temba.channels.consumers.channel_migrated_consumer.capture_exception")
    @patch("temba.channels.consumers.channel_migrated_consumer.IntegrationsInternalClient")
    @patch("temba.channels.consumers.channel_migrated_consumer.MigrateChannelUseCase")
    def test_consume_unexpected_error_reports_and_reraises(
        self,
        mock_use_case_cls,
        mock_client_cls,
        mock_capture_exception,
    ):
        mock_use_case = Mock()
        mock_use_case.execute.side_effect = RuntimeError("boom")
        mock_use_case_cls.return_value = mock_use_case
        mock_client = Mock()
        mock_client_cls.return_value = mock_client

        event_id = str(uuid.uuid4())
        data = {
            "uuid": str(uuid.uuid4()),
            "app_uuid": str(uuid.uuid4()),
            "project": {
                "from": str(uuid.uuid4()),
                "to": str(uuid.uuid4()),
            },
        }
        message, channel = self._create_message(data, event_id=event_id)
        consumer = ChannelMigratedConsumer()
        consumer._message = message

        with self.assertRaises(RuntimeError):
            consumer.consume(message)

        mock_client.report_app_migration_status.assert_called_once_with(
            event_id=event_id,
            status="error",
            error="boom",
        )
        channel.basic_ack.assert_not_called()
        mock_capture_exception.assert_called_once()
