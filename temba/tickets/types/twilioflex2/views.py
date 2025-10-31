import requests

from django import forms
from django.forms import ValidationError
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
            help_text=_("SID of the Flex 2.x instance (e.g. FXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)."),
        )
        flex_workspace_sid = forms.CharField(
            label=_("Workspace SID"), help_text=_("SID of a TaskRouter Workspace (e.g. WSxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx).")
        )
        flex_workflow_sid = forms.CharField(
            label=_("Workflow SID"), help_text=_("SID of a TaskRouter Workflow (e.g. WWxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx).")
        )
        conversation_service_sid = forms.CharField(
            label=_("Conversation Service SID"), help_text=_("SID of a Conversation Service (e.g. ISxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx).")
        )

        def _validate_taskrouter(self, account_sid: str, auth_token: str, workspace_sid: str, workflow_sid: str):
            ws_resp = requests.get(
                f"https://taskrouter.twilio.com/v1/Workspaces/{workspace_sid}",
                auth=(account_sid, auth_token),
                timeout=10,
            )
            ws_resp.raise_for_status()

            wf_resp = requests.get(
                f"https://taskrouter.twilio.com/v1/Workspaces/{workspace_sid}/Workflows/{workflow_sid}",
                auth=(account_sid, auth_token),
                timeout=10,
            )
            wf_resp.raise_for_status()

        def _validate_flex_instance(self, account_sid: str, auth_token: str, flex_instance_sid: str):
            try:
                resp = requests.get(
                    f"https://flex-api.twilio.com/v2/FlexInstances/{flex_instance_sid}",
                    auth=(account_sid, auth_token),
                    timeout=10,
                )
                if resp.status_code not in (200, 204, 403):
                    resp.raise_for_status()
            except Exception:
                pass

        def clean(self):
            account_sid = self.cleaned_data["account_sid"]
            auth_token = self.cleaned_data["auth_token"]
            flex_instance_sid = self.cleaned_data["flex_instance_sid"]
            flex_workspace_sid = self.cleaned_data["flex_workspace_sid"]
            flex_workflow_sid = self.cleaned_data["flex_workflow_sid"]
            conversation_service_sid = self.cleaned_data["conversation_service_sid"]

            try:
                self._validate_taskrouter(
                    account_sid=account_sid,
                    auth_token=auth_token,
                    workspace_sid=flex_workspace_sid,
                    workflow_sid=flex_workflow_sid,
                )
                self._validate_flex_instance(
                    account_sid=account_sid,
                    auth_token=auth_token,
                    flex_instance_sid=flex_instance_sid,
                )
            except Exception:
                raise ValidationError(
                    _(
                        "Unable to validate Twilio configuration. Please check your credentials and SIDs then try again."
                    )
                )
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
