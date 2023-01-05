from collections import OrderedDict

from django.conf import settings
from django.utils.module_loading import import_string

TYPES = OrderedDict({})

def register_external_service_type(type_class):
    """
    Registers a external_service type
    """
    global TYPES

    if not type_class.slug:
        type_class.slug = type_class.__module__.split(".")[-2]

    assert type_class.slug not in TYPES, f"external_service type slug {type_class.slug} already taken"

    TYPES[type_class.slug] = type_class()


def reload_external_service_types():
    """
    Re-loads the dynamic external_service types
    """
    global TYPES

    TYPES = OrderedDict({})
    for class_name in settings.EXTERNALSERVICE_TYPES:
        register_external_service_type(import_string(class_name))


reload_external_service_types()