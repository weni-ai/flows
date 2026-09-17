from django import forms
from django.utils.translation import ugettext_lazy as _

from temba.tickets.models import Ticketer
from temba.tickets.views import BaseConnectView
from temba.utils.uuid import uuid4


class ConnectView(BaseConnectView):
    class Form(BaseConnectView.Form):
        base_url = forms.URLField(label=_("Base URL"), help_text=_("The base URL of the generic ticketing service"))
        api_token = forms.CharField(
            label=_("API token"), help_text=_("The API token of the generic ticketing service")
        )
        webhook_secret = forms.CharField(
            label=_("Webhook secret"), help_text=_("The webhook secret of the generic ticketing service")
        )
        project_uuid = forms.UUIDField(
            label=_("Project UUID"), help_text=_("The project UUID of the generic ticketing service")
        )
        project_name = forms.CharField(
            label=_("Project name"), help_text=_("The project name of the generic ticketing service")
        )
        route_open = forms.CharField(
            label=_("Open route"), help_text=_("The open route of the generic ticketing service")
        )
        route_forward = forms.CharField(
            label=_("Forward route"), help_text=_("The forward route of the generic ticketing service")
        )
        route_close = forms.CharField(
            label=_("Close route"), help_text=_("The close route of the generic ticketing service")
        )
        route_reopen = forms.CharField(
            label=_("Reopen route"), help_text=_("The reopen route of the generic ticketing service")
        )
        route_history = forms.CharField(
            label=_("History route"), help_text=_("The history route of the generic ticketing service")
        )

        def clean(self):
            return self.cleaned_data

    def form_valid(self, form):
        from .type import GenericType

        base_url = form.cleaned_data["base_url"]
        api_token = form.cleaned_data["api_token"]
        webhook_secret = form.cleaned_data["webhook_secret"]
        project_uuid = form.cleaned_data["project_uuid"]
        project_name = form.cleaned_data["project_name"]
        route_open = form.cleaned_data["route_open"]
        route_forward = form.cleaned_data["route_forward"]
        route_close = form.cleaned_data["route_close"]
        route_reopen = form.cleaned_data["route_reopen"]
        route_history = form.cleaned_data["route_history"]

        config = {
            GenericType.CONFIG_BASE_URL: base_url,
            GenericType.CONFIG_API_TOKEN: api_token,
            GenericType.CONFIG_WEBHOOK_SECRET: webhook_secret,
            GenericType.CONFIG_PROJECT_UUID: str(project_uuid),
            GenericType.CONFIG_PROJECT_NAME: project_name,
            GenericType.CONFIG_ROUTE_OPEN: route_open,
            GenericType.CONFIG_ROUTE_FORWARD: route_forward,
            GenericType.CONFIG_ROUTE_CLOSE: route_close,
            GenericType.CONFIG_ROUTE_REOPEN: route_reopen,
            GenericType.CONFIG_ROUTE_HISTORY: route_history,
        }

        self.object = Ticketer(
            uuid=uuid4(),
            org=self.org,
            ticketer_type=GenericType.slug,
            config=config,
            name=project_name,
            created_by=self.request.user,
            modified_by=self.request.user,
        )
        self.object.save()
        return super().form_valid(form)

    form_class = Form
    template_name = "tickets/types/generic/connect.haml"
