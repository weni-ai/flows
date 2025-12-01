from rest_framework.exceptions import NotFound

from django.core import exceptions as django_exceptions
from django.shortcuts import _get_queryset


def get_object_or_404(klass, field_error_name: str, *args, **kwargs):
    """
    Use get() to return an object, or raise a Http404 exception if the object
    does not exist.

    klass may be a Model, Manager, or QuerySet object. All other passed
    arguments and keyword arguments are used in the get() query.

    Like with QuerySet.get(), MultipleObjectsReturned is raised if more than
    one object is found.
    """
    queryset = _get_queryset(klass)
    if not hasattr(queryset, "get"):
        klass__name = klass.__name__ if isinstance(klass, type) else klass.__class__.__name__
        raise ValueError(
            "First argument to get_object_or_404() must be a Model, Manager, " "or QuerySet, not '%s'." % klass__name
        )
    try:
        return queryset.get(*args, **kwargs)
    except (queryset.model.DoesNotExist, django_exceptions.ValidationError):
        raise NotFound({field_error_name: f"{field_error_name} not found"})
