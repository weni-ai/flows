from temba.projects.usecases.channel_creation import is_hidden_from_ui
from temba.tests.base import TembaTest


class ChannelCreationTestCase(TembaTest):
    def test_is_hidden_from_ui_for_preview_channel(self):
        channel = self.create_channel("WWC", "Weni Web Chat - Preview", "preview", config={"preview": True})

        self.assertTrue(is_hidden_from_ui(channel))

    def test_is_hidden_from_ui_for_copilot_channel(self):
        channel = self.create_channel(
            "WWC",
            "Weni Web Chat - Copilot",
            "copilot",
            config={"is_live_desk_copilot": True},
        )

        self.assertTrue(is_hidden_from_ui(channel))

    def test_is_hidden_from_ui_for_regular_channel(self):
        channel = self.create_channel("TG", "Telegram", "telegram")

        self.assertFalse(is_hidden_from_ui(channel))
