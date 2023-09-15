from django.db import close_old_connections, reset_queries  # pragma: no cover
from django.dispatch import Signal  # pragma: no cover

message_started = Signal()  # pragma: no cover
message_finished = Signal()  # pragma: no cover

# db connection state managed similarly to the wsgi handler
message_started.connect(reset_queries)  # pragma: no cover
message_started.connect(close_old_connections)  # pragma: no cover
message_finished.connect(close_old_connections)  # pragma: no cover
