from temba.channels.types.whatsapp_cloud.usecases import UpdateWhatsAppCloudWabaUseCase, WabaChannelNotFound
from temba.tests import TembaTest


class UpdateWhatsAppCloudWabaUseCaseTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.usecase = UpdateWhatsAppCloudWabaUseCase()

    def test_raises_when_no_matching_channel(self):
        with self.assertRaises(WabaChannelNotFound):
            self.usecase.execute(old_waba_id="old-waba", new_waba_id="new-waba")

    def test_updates_channel_config(self):
        channel = self.create_channel(
            "WAC",
            "WAC Channel",
            "phone-number-id-1",
            config={
                "wa_waba_id": "old-waba",
                "wa_currency": "USD",
                "wa_message_template_namespace": "old-namespace",
            },
        )

        results = self.usecase.execute(old_waba_id="old-waba", new_waba_id="new-waba")

        channel.refresh_from_db()
        self.assertEqual(len(results), 1)
        self.assertEqual(channel.config["wa_waba_id"], "new-waba")
        self.assertEqual(channel.config["wa_previous_waba_id"], "old-waba")
        self.assertEqual(channel.config["wa_currency"], "BRL")
        self.assertEqual(channel.config["wa_message_template_namespace"], "old-namespace")
        self.assertEqual(channel.address, "phone-number-id-1")

    def test_dry_run_does_not_save(self):
        channel = self.create_channel(
            "WAC",
            "WAC Channel",
            "phone-number-id-1",
            config={"wa_waba_id": "old-waba", "wa_currency": "USD"},
        )

        results = self.usecase.execute(old_waba_id="old-waba", new_waba_id="new-waba", dry_run=True)

        channel.refresh_from_db()
        self.assertTrue(results[0]["dry_run"])
        self.assertEqual(channel.config["wa_waba_id"], "old-waba")
        self.assertNotIn("wa_previous_waba_id", channel.config)

    def test_updates_all_channels_with_same_waba(self):
        channel_a = self.create_channel(
            "WAC",
            "WAC A",
            "phone-number-id-1",
            config={"wa_waba_id": "old-waba", "wa_currency": "USD"},
        )
        channel_b = self.create_channel(
            "WAC",
            "WAC B",
            "phone-number-id-2",
            config={"wa_waba_id": "old-waba", "wa_currency": "USD"},
        )

        results = self.usecase.execute(old_waba_id="old-waba", new_waba_id="new-waba")

        channel_a.refresh_from_db()
        channel_b.refresh_from_db()

        self.assertEqual(len(results), 2)
        self.assertEqual(channel_a.config["wa_waba_id"], "new-waba")
        self.assertEqual(channel_b.config["wa_waba_id"], "new-waba")
