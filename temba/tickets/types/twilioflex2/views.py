from django import forms
from django.utils.translation import ugettext_lazy as _

from temba.tickets.models import Ticketer
from temba.tickets.views import BaseConnectView
from temba.utils.uuid import uuid4


class ConnectView(BaseConnectView):
    class Form(BaseConnectView.Form):
        ticketer_name = forms.CharField(
            label=_("Ticketer Name"),
            help_text=_("A name to help identify your ticketer"),
        )
        account_sid = forms.CharField(
            label=_("Authentication User"),
            help_text=_("Account SID or API Key SID of a Twilio account."),
        )
        auth_token = forms.CharField(
            label=_("Authentication Password"),
            help_text=_("Auth Token or API Key Secret of a Twilio account."),
        )
        flex_instance_sid = forms.CharField(
            label=_("Flex Instance SID"),
            help_text=_("SID of the Flex 2.x instance (e.g. GOxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)."),
        )
        flex_workspace_sid = forms.CharField(
            label=_("Workspace SID"),
            help_text=_("SID of a TaskRouter Workspace (e.g. WSxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)."),
        )
        flex_workflow_sid = forms.CharField(
            label=_("Workflow SID"),
            help_text=_("SID of a TaskRouter Workflow (e.g. WWxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)."),
        )
        conversation_service_sid = forms.CharField(
            label=_("Conversation Service SID"),
            help_text=_("SID of a Conversation Service (e.g. ISxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)."),
        )

        def clean(self):
            return self.cleaned_data

    def form_valid(self, form):
        from .type import TwilioFlex2Type

        ticketer_name = form.cleaned_data["ticketer_name"]
        account_sid = form.cleaned_data["account_sid"]
        auth_token = form.cleaned_data["auth_token"]
        flex_instance_sid = form.cleaned_data["flex_instance_sid"]
        flex_workspace_sid = form.cleaned_data["flex_workspace_sid"]
        flex_workflow_sid = form.cleaned_data["flex_workflow_sid"]
        conversation_service_sid = form.cleaned_data["conversation_service_sid"]

        config = {
            TwilioFlex2Type.CONFIG_ACCOUNT_SID: account_sid,
            TwilioFlex2Type.CONFIG_AUTH_TOKEN: auth_token,
            TwilioFlex2Type.CONFIG_FLEX_INSTANCE_SID: flex_instance_sid,
            TwilioFlex2Type.CONFIG_FLEX_WORKSPACE_SID: flex_workspace_sid,
            TwilioFlex2Type.CONFIG_FLEX_WORKFLOW_SID: flex_workflow_sid,
            TwilioFlex2Type.CONFIG_CONVERSATION_SERVICE_SID: conversation_service_sid,
        }

        self.object = Ticketer(
            uuid=uuid4(),
            org=self.org,
            ticketer_type=TwilioFlex2Type.slug,
            config=config,
            name=ticketer_name,
            created_by=self.request.user,
            modified_by=self.request.user,
        )
        self.object.save()
        return super().form_valid(form)

    form_class = Form
    template_name = "tickets/types/twilioflex2/connect.haml"
