import json
from unittest.mock import MagicMock, patch

import amqp
from weni_datalake_sdk.paths import MsgPath

from django.test import TestCase

from temba.msgs.consumers.msg_consumer import MsgConsumer


class MsgConsumerTest(TestCase):
    def setUp(self):
        self.consumer = MsgConsumer()
        self.mock_message = MagicMock(spec=amqp.Message)
        self.mock_message.body = json.dumps({"test": "data"}).encode()
        self.mock_message.delivery_tag = "test-tag"
        self.mock_message.channel = MagicMock()

    @patch("temba.msgs.consumers.msg_consumer.send_data")
    def test_consume_success(self, mock_send_data):
        self.consumer.consume(self.mock_message)

        mock_send_data.assert_called_once_with(MsgPath, {"test": "data"})

        self.mock_message.channel.basic_ack.assert_called_once_with("test-tag")

        self.mock_message.channel.basic_reject.assert_not_called()

    @patch("temba.msgs.consumers.msg_consumer.send_data")
    @patch("temba.msgs.consumers.msg_consumer.capture_exception")
    def test_consume_failure(self, mock_capture_exception, mock_send_data):
        mock_send_data.side_effect = Exception("Test error")

        self.consumer.consume(self.mock_message)

        mock_capture_exception.assert_called_once()

        self.mock_message.channel.basic_reject.assert_called_once_with("test-tag", requeue=False)

        self.mock_message.channel.basic_ack.assert_not_called()

    @patch("temba.msgs.consumers.msg_consumer.send_data")
    def test_consume_invalid_json(self, mock_send_data):
        invalid_message = MagicMock(spec=amqp.Message)
        invalid_message.body = b"invalid json"
        invalid_message.delivery_tag = "test-tag"
        invalid_message.channel = MagicMock()

        self.consumer.consume(invalid_message)

        mock_send_data.assert_not_called()

        invalid_message.channel.basic_reject.assert_called_once_with("test-tag", requeue=False)
