from amqp.channel import Channel  # pragma: no cover

from temba.classifiers.handle import handle_consumers as classifier_handle_consumers  # pragma: no cover
from temba.features.handle import handle_consumers as feature_handle_consumers  # pragma: no cover
from temba.msgs.handle import handle_consumers as msgs_handle_consumers  # pragma: no cover
from temba.projects.handle import handle_consumers as project_handle_consumers  # pragma: no cover
from temba.tickets.handle import handle_consumers as ticketer_handle_consumers  # pragma: no cover


def handle_consumers(channel: Channel) -> None:  # pragma: no cover
    project_handle_consumers(channel)
    classifier_handle_consumers(channel)
    ticketer_handle_consumers(channel)
    feature_handle_consumers(channel)
    msgs_handle_consumers(channel)
