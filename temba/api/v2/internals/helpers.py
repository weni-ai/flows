from rest_framework.exceptions import NotFound

from django.core import exceptions as django_exceptions
from django.db.models import Model
from django.shortcuts import _get_queryset


def get_object_or_404(cls: Model, field_error_name: str, *args, **kwargs):
    """
    Use get() to return an object, or raise a NotFound 404 exception if the object
    does not exist.

    cls may be a Model, Manager, or QuerySet object. All other passed
    arguments and keyword arguments are used in the get() query.

    Like with QuerySet.get(), MultipleObjectsReturned is raised if more than
    one object is found.
    """
    queryset = _get_queryset(cls)
    if not hasattr(queryset, "get"):
        cls__name = cls.__name__ if isinstance(cls, type) else cls.__cls__.__name__
        raise ValueError(
            "First argument to get_object_or_404() must be a Model, Manager, " "or QuerySet, not '%s'." % cls__name
        )
    try:
        return queryset.get(*args, **kwargs)
    except (queryset.model.DoesNotExist, django_exceptions.ValidationError):
        raise NotFound({field_error_name: f"{field_error_name} not found"})
