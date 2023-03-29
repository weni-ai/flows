from smartmin.views import SmartCRUDL, SmartFormView, SmartReadView, SmartTemplateView

from django import forms
from django.utils.html import mark_safe
from django.utils.translation import ugettext_lazy as _
from django.urls import reverse
from rest_framework.decorators import action
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.renderers import JSONRenderer

from temba.utils.views import ComponentFormMixin
from temba.orgs.views import DependencyDeleteModal, OrgObjPermsMixin, OrgPermsMixin

from .models import ExternalService


class BaseConnectView(ComponentFormMixin, OrgPermsMixin, SmartFormView):
    class Form(forms.Form):
        def __init__(self, **kwargs):
            self.request = kwargs.pop("request")
            self.external_service_type = kwargs.pop("external_service_type")

            super().__init__(**kwargs)

    submit_button_name = _("Connect")
    permission = "tickets.ticketer_connect"
    external_service_type = None
    form_blurb = ""
    success_url = "@orgs.org_home"

    def __init__(self, external_service_type):
        self.external_service_type = external_service_type

        super().__init__()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        kwargs["external_service_type"] = self.external_service_type
        return kwargs

    def get_template_names(self):
        return (
            "externals/types/%s/connect.html" % self.external_service_type.slug,
            "external_services/external_service_connect_form.html",
        )

    def derive_title(self):
        return _("Connect %(external_service)s") % {"external_service": self.external_service_type.name}

    def get_form_blurb(self):
        return self.form_blurb

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form_blurb"] = mark_safe(self.get_form_blurb())


class ExternalServiceCRUDL(SmartCRUDL):
    model = ExternalService
    actions = ("connect", "read", "delete")

    class Connect(OrgPermsMixin, SmartTemplateView):
        def get_gear_links(self):
            return [dict(title=_("Home"), style="button-light", href=reverse("orgs.org_home"))]

        def get_context_data(self, **kwargs):
            context = super().get_context_data(**kwargs)
            context["external_service_types"] = [
                est for est in ExternalService.get_types() if est.is_available_to(self.get_user())
            ]
            print(context)
            return context

    class Read(OrgObjPermsMixin, SmartReadView):
        slug_url_kwarg = "uuid"

    class Delete(DependencyDeleteModal):
        cancel_url = "@orgs.org_home"
        success_url = "@orgs.org_home"
        success_message = _("Your external service has been deleted.")


class GetExternalTypes(APIView):
    authentication_classes = []
    permission_classes = []
    pagination_class = None
    renderer_classes = [JSONRenderer]
    throttle_classes = []

    def get(self, request, slug=None):
        from temba.externals.types import TYPES

        external_type = TYPES.get(slug)
        
        if external_type is None:
            return Response (status=status.HTTP_404_NOT_FOUND)

        actions = external_type.get_actions()
        return Response(actions, status=status.HTTP_200_OK)
