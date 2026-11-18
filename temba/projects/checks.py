from django.conf import settings
from django.core.checks import Error, register

from temba.projects.consumers.project_events import EventAction

UNKNOWN_LEGACY_ACTION_CHECK_ID = "projects.E001"


@register()
def project_events_legacy_actions(app_configs, **kwargs):
    allowed = [action.value for action in EventAction]
    unknown = [action for action in settings.PROJECT_EVENTS_LEGACY_ACTIONS if action not in allowed]
    if not unknown:
        return []
    return [
        Error(
            f"PROJECT_EVENTS_LEGACY_ACTIONS contains unknown actions: {', '.join(unknown)}",
            hint=f"Allowed actions: {', '.join(allowed)}. Leave it empty to let the AmazonMQ consumer apply all.",
            id=UNKNOWN_LEGACY_ACTION_CHECK_ID,
        )
    ]
