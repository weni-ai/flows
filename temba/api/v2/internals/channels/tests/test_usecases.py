import uuid

from temba.api.v2.internals.channels.usecases import (
    ChannelNotFoundError,
    ElevenLabsApiKeyNotFoundError,
    GetElevenLabsApiKeyUseCase,
)
from temba.tests import TembaTest


class GetElevenLabsApiKeyUseCaseTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.usecase = GetElevenLabsApiKeyUseCase()

    def test_raises_channel_not_found_for_nonexistent_uuid(self):
        with self.assertRaises(ChannelNotFoundError):
            self.usecase.execute(str(uuid.uuid4()))

    def test_raises_api_key_not_found_when_no_voice_mode(self):
        channel = self.create_channel("TG", "Test Channel", "test")
        with self.assertRaises(ElevenLabsApiKeyNotFoundError):
            self.usecase.execute(str(channel.uuid))

    def test_raises_api_key_not_found_when_no_elevenlabs_config(self):
        channel = self.create_channel("TG", "Test Channel", "test", config={"voice_mode": {"otherProvider": {}}})
        with self.assertRaises(ElevenLabsApiKeyNotFoundError):
            self.usecase.execute(str(channel.uuid))

    def test_raises_api_key_not_found_when_elevenlabs_has_no_key(self):
        channel = self.create_channel("TG", "Test Channel", "test", config={"voice_mode": {"elevenLabs": {}}})
        with self.assertRaises(ElevenLabsApiKeyNotFoundError):
            self.usecase.execute(str(channel.uuid))

    def test_returns_api_key_for_valid_config(self):
        channel = self.create_channel(
            "TG",
            "Test Channel",
            "test",
            config={"voice_mode": {"elevenLabs": {"apiKey": "sk-test-key-123"}}},
        )
        result = self.usecase.execute(str(channel.uuid))
        self.assertEqual(result, "sk-test-key-123")
