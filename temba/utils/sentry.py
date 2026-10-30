import sentry_sdk


def remove_request_body_and_frame_vars(event, hint):
    """
    Sentry event processor that removes everything that can carry data submitted by the client: the request body and
    the local variables of every stack frame
    """
    event.get("request", {}).pop("data", None)

    for exception in event.get("exception", {}).get("values", []):
        for frame in (exception.get("stacktrace") or {}).get("frames", []):
            frame.pop("vars", None)

    return event


def scrub_events_for_current_request():
    """
    Removes the request body and frame variables from every Sentry event raised while the current request is handled.
    The Django integration gives each request its own scope, so this applies to nothing outside the request.
    """
    with sentry_sdk.configure_scope() as scope:
        scope.add_event_processor(remove_request_body_and_frame_vars)
