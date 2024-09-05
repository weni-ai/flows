from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404

from temba.flows.models import Flow

User = get_user_model()


def get_or_create_user_by_email(email: str) -> tuple:  # pragma: no cover
    return User.objects.get_or_create(email=email, username=email)


def delete_feature_template(features_flow, user_email=None):  # pragma: no cover
    user, _ = get_or_create_user_by_email(user_email)

    for flow_uuid in features_flow:
        flow_object = get_object_or_404(Flow, uuid=flow_uuid)
        flow_object.release(user)
    return True
