from django.utils import timezone

from temba.channels.models import Channel


class WabaChannelNotFound(Exception):
    pass


class UpdateWhatsAppCloudWabaUseCase:
    """
    Update WAC channel config after WABA currency migration.

    Only persists local channel data from the provided WABA IDs.
    Does not call Meta APIs.
    """

    def execute(self, *, old_waba_id: str, new_waba_id: str, dry_run=False):
        channels = [
            channel
            for channel in Channel.objects.filter(channel_type="WAC")
            if (channel.config or {}).get("wa_waba_id") == old_waba_id
        ]
        if not channels:
            raise WabaChannelNotFound()

        migration_date = timezone.now().isoformat()
        wa_currency = "BRL"
        results = []

        for channel in channels:
            config = dict(channel.config or {})
            updated_config = {
                **config,
                "wa_previous_waba_id": old_waba_id,
                "wa_migration_date": migration_date,
                "wa_waba_id": new_waba_id,
                "wa_currency": wa_currency,
            }

            result = {
                "channel_uuid": str(channel.uuid),
                "org_id": channel.org_id,
                "dry_run": dry_run,
                "before": {
                    "wa_waba_id": config.get("wa_waba_id"),
                    "wa_currency": config.get("wa_currency"),
                },
                "after": {
                    "wa_waba_id": new_waba_id,
                    "wa_previous_waba_id": old_waba_id,
                    "wa_migration_date": migration_date,
                    "wa_currency": wa_currency,
                },
            }

            if not dry_run:
                channel.config = updated_config
                channel.save(update_fields=["config"])

            results.append(result)

        return results
