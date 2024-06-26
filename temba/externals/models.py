import json
import os
import sys
from abc import ABCMeta, abstractproperty

from smartmin.models import SmartModel

from django.db import models
from django.template import Engine

from temba.orgs.models import DependencyMixin, Org
from temba.utils.models import TembaModel
from temba.utils.uuid import uuid4


class ExternalServiceTypeInterface(metaclass=ABCMeta):  # pragma: no cover
    @abstractproperty
    def serializer_class(self):
        pass


class ExternalServiceType(object):
    """
    ExternalServiceType is our abstraction base type for external services.
    """

    name = None
    slug = None
    connect_blurb = None
    external_service = None

    def is_available_to(self, user):
        return True

    def get_connect_blurb(self):
        return Engine.get_default().from_string(str(self.connect_blurb))

    def get_actions(self):
        try:
            path = os.path.dirname(os.path.abspath(sys.modules[self.__class__.__module__].__file__))

            with open(path + "/actions.json", encoding="utf-8") as actions:
                data = json.load(actions)
            return data

        except Exception as e:
            return str(e)


class ExternalService(SmartModel, DependencyMixin):
    """
    A external service that can perform actions
    """

    uuid = models.UUIDField(default=uuid4)
    external_service_type = models.CharField(max_length=16)
    org = models.ForeignKey(Org, on_delete=models.PROTECT, related_name="external_services")
    name = models.CharField(max_length=64)
    config = models.JSONField()

    @classmethod
    def create(cls, org, user, external_service_type: str, name: str, config: dict):
        return cls.objects.create(
            uuid=uuid4(),
            external_service_type=external_service_type,
            name=name,
            config=config,
            org=org,
            created_by=user,
            modified_by=user,
        )

    @classmethod
    def get_types(cls):
        """
        Returns the possible types available for external services
        """
        from temba.externals.types import TYPES

        return TYPES.values()

    @classmethod
    def get_type_from_code(cls, code) -> ExternalServiceType:
        from .types import TYPES

        try:
            return TYPES[code]
        except KeyError:  # pragma: no cover
            raise KeyError("Unrecognized external service type code: %s" % code)

    @property
    def type(self):
        """
        Returns the type instance
        """
        from temba.externals.types import TYPES

        return TYPES[self.external_service_type]

    @property
    def actions(self):
        self.type.external_service = self
        return self.type.get_actions()

    def release(self, user):
        self.is_active = False
        self.modified_by = user
        self.save(update_fields=("is_active", "modified_by", "modified_on"))

    def __str__(self):
        return f"ExternalService[uuid={self.uuid}, name={self.name}]"


class Prompt(TembaModel):
    text = models.TextField()
    chat_gpt_service = models.ForeignKey(ExternalService, on_delete=models.CASCADE)
