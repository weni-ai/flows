from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test.utils import override_settings

from temba.channels.channel_events import (
    ChannelEventType,
    build_channel_event_data,
    build_channel_event_routing_key,
    publish_channel_deleted,
)
from temba.channels.models import Channel
from temba.channels.tasks import task_publish_channel_event
from temba.event_driven.publisher.channel_event_publisher import CHANNEL_EVENT_PRODUCER, ChannelEventPublisher
from temba.tests import TembaTest, mock_mailroom


class ChannelEventPayloadTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid4()
        self.org.save(update_fields=["proj_uuid"])

    def test_whatsapp_cloud_payload_is_a_whitelist(self):
        channel = self.create_channel(
            "WAC",
            "WhatsApp Cloud",
            "123123123",
            config={
                "wa_number": "+5511999999999",
                "wa_waba_id": "waba-1",
                "wa_user_token": "secret-token",
            },
        )
        channel.is_active = False
        channel.save(update_fields=["is_active"])

        data = build_channel_event_data(channel)

        self.assertEqual(
            {
                "channel_uuid": str(channel.uuid),
                "project_uuid": str(self.org.proj_uuid),
                "channel_type": "WAC",
                "address": "123123123",
                "is_active": False,
                "occurred_at": channel.modified_on.isoformat(),
                "whatsapp": {
                    "phone_number": "+5511999999999",
                    "phone_number_id": "123123123",
                    "waba_id": "waba-1",
                },
            },
            data,
        )
        self.assertNotIn("secret-token", str(data))

    def test_non_whatsapp_payload_omits_whatsapp_block(self):
        channel = self.create_channel("TG", "Telegram", "telegram-bot")

        data = build_channel_event_data(channel)

        self.assertNotIn("whatsapp", data)
        self.assertEqual("TG", data["channel_type"])

    def test_routing_key_uses_action_and_channel_type(self):
        self.assertEqual(
            "channel.deleted.wac",
            build_channel_event_routing_key(ChannelEventType.DELETED.value, "WAC"),
        )


class PublishChannelDeletedTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid4()
        self.org.save(update_fields=["proj_uuid"])
        self.channel = self.create_channel("WAC", "WhatsApp Cloud", "123")

    @patch("temba.channels.tasks.task_publish_channel_event.delay")
    def test_skips_when_publishing_is_disabled(self, mock_delay):
        publish_channel_deleted(self.channel)

        mock_delay.assert_not_called()

    @override_settings(
        CHANNEL_EVENTS_PUBLISH_ENABLED=True, CELERY_TASK_ALWAYS_EAGER=True
    )
    @patch("temba.channels.tasks.task_publish_channel_event.delay")
    def test_enqueues_after_commit_when_enabled(self, mock_delay):
        publish_channel_deleted(self.channel)

        mock_delay.assert_called_once_with(
            "channel.deleted",
            build_channel_event_data(self.channel),
            "channel.deleted.wac",
        )

    @override_settings(
        CHANNEL_EVENTS_PUBLISH_ENABLED=True, CELERY_TASK_ALWAYS_EAGER=True
    )
    @patch("temba.channels.tasks.task_publish_channel_event.delay")
    def test_skips_channel_without_project(self, mock_delay):
        self.org.proj_uuid = None
        self.org.save(update_fields=["proj_uuid"])

        publish_channel_deleted(self.channel)

        mock_delay.assert_not_called()

    @override_settings(
        CHANNEL_EVENTS_PUBLISH_ENABLED=True, CELERY_TASK_ALWAYS_EAGER=True
    )
    @patch("temba.channels.tasks.task_publish_channel_event.delay")
    def test_skips_channel_without_org(self, mock_delay):
        channel = Channel.objects.create(
            org=None,
            channel_type="A",
            name="Android",
            address="1234",
            config={},
            schemes=["tel"],
            created_by=self.admin,
            modified_by=self.admin,
        )

        publish_channel_deleted(channel)

        mock_delay.assert_not_called()


class ChannelReleaseEventTest(TembaTest):
    @mock_mailroom
    @patch("temba.channels.channel_events.publish_channel_deleted")
    def test_release_publishes_deleted_event(self, mock_publish, mr_mocks):
        channel = self.create_channel("WAC", "WhatsApp Cloud", "123")

        channel.release(self.admin)

        mock_publish.assert_called_once_with(channel)
        channel.refresh_from_db()
        self.assertFalse(channel.is_active)


class ChannelEventPublisherTest(TembaTest):
    @override_settings(CHANNEL_EVENTS_EXCHANGE="flows-channel-events.topic")
    def test_publish_sends_envelope_without_double_wrapping(self):
        transport = MagicMock()
        publisher = ChannelEventPublisher(publisher=transport)
        data = {"channel_uuid": "abc", "channel_type": "WAC"}

        publisher.publish("channel.deleted", data, "channel.deleted.wac")

        transport.send_message.assert_called_once()
        sent = transport.send_message.call_args.kwargs
        self.assertEqual("flows-channel-events.topic", sent["exchange"])
        self.assertEqual("channel.deleted.wac", sent["routing_key"])
        self.assertNotIn("event_type", sent)
        body = sent["body"]
        self.assertEqual("channel.deleted", body["event_type"])
        self.assertEqual(CHANNEL_EVENT_PRODUCER, body["producer"])
        self.assertEqual(data, body["data"])
        self.assertTrue(body["event_id"])
        self.assertTrue(body["timestamp"])


class PublishChannelEventTaskTest(TembaTest):
    @patch(
        "temba.event_driven.publisher.channel_event_publisher.ChannelEventPublisher.publish"
    )
    def test_task_delegates_to_publisher(self, mock_publish):
        task_publish_channel_event(
            "channel.deleted", {"channel_uuid": "abc"}, "channel.deleted.wac"
        )

        mock_publish.assert_called_once_with(
            "channel.deleted", {"channel_uuid": "abc"}, "channel.deleted.wac"
        )

    def test_task_retries_publishing_errors(self):
        from weni.eda.exceptions import EDAPublishingError

        self.assertIn(EDAPublishingError, task_publish_channel_event.autoretry_for)
        self.assertEqual(5, task_publish_channel_event.max_retries)
