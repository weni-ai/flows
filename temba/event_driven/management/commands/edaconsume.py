from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.module_loading import import_string


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--consumer-group",
            dest="consumer_group",
            default="default",
            help="Specify the consumer group to run (default, template, all)",
        )

    def handle(self, *args, **options):
        consumer_group = options["consumer_group"]

        if consumer_group == "template":
            handler_path = "temba.event_driven.handle.handle_template_consumers"
        elif consumer_group == "default":
            handler_path = "temba.event_driven.handle.handle_default_consumers"
        elif consumer_group == "all":
            handler_path = settings.EDA_CONSUMERS_HANDLE
        else:
            self.stderr.write(self.style.ERROR(f"Invalid consumer group: {consumer_group}"))
            return

        handle_consumers_function = import_string(handler_path)
        connection_backend = import_string(settings.EDA_CONNECTION_BACKEND)(handle_consumers_function)

        connection_params = dict(
            host=settings.EDA_BROKER_HOST,
            port=settings.EDA_BROKER_PORT,
            userid=settings.EDA_BROKER_USER,
            password=settings.EDA_BROKER_PASSWORD,
            virtual_host=settings.EDA_VIRTUAL_HOST,
        )

        connection_backend.start_consuming(connection_params)
