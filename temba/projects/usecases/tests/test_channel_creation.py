from django.conf import settings

from temba.projects.usecases.channel_creation import _build_default_wwc_config, is_hidden_from_ui
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

    def test_build_default_wwc_config_includes_voice_mode_for_preview(self):
        config = _build_default_wwc_config(preview=True)

        self.assertTrue(config["preview"])
        self.assertEqual(
            config["voice_mode"],
            {
                "enabled": True,
                "elevenLabs": {
                    "apiKey": settings.WENI_VOICE_TOKEN,
                    "voiceId": settings.WENI_ELEVENLABS_VOICE_ID,
                },
            },
        )

    def test_build_default_wwc_config_excludes_voice_mode_for_copilot(self):
        config = _build_default_wwc_config(is_live_desk_copilot=True)

        self.assertTrue(config["is_live_desk_copilot"])
        self.assertNotIn("voice_mode", config)
