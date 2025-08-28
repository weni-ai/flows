from django.contrib.auth.models import User

from temba.flows.models import Flow
from temba.orgs.models import Org
from temba.triggers.models import Trigger


def create_catchall_trigger(*, org: Org, user: User, flow: Flow, groups=None):
    groups = groups or []
    return Trigger.create(org, user, Trigger.TYPE_CATCH_ALL, flow, groups=groups)
