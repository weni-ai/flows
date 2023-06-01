from django import forms
from django.utils.translation import ugettext_lazy as _

from temba.externals.models import ExternalService
from temba.externals.views import BaseConnectView
from temba.utils.uuid import uuid4
from .type import ChatGPTType


class ConnectView(BaseConnectView):
    class Form(BaseConnectView.Form):
        name = forms.CharField(max_length=256, label=_("Name"), help_text=_("Name"))
        api_key = forms.CharField(
            label=_("ChatGPT API Key"), help_text=_("ChatGPT API Key")
        )
        rules = forms.CharField(label=_("Rules"), help_text=_("Rules"))
        knowledge_base = forms.ChaField(
            label=("Knowledge Base"), help_text=_("Knowledge Base")
        )
        ai_model = forms.ChoiceField(
            label=("A.I Model"),
            help_text=_("A.I Model"),
            choices=ChatGPTType.AI_MODEL,
            initial="gpt-3.5-turbo",
        )

        def clean(self):
            api_key = self.cleaned_data.get("api_key")
            if not api_key:
                raise forms.ValidationError(_("Invalid API Key"))

    def form_valid(self, form):
        name = form.cleaned_data["name"]
        api_key = form.cleaned_data["api_key"]
        rules = form.cleaned_data["rules"]
        knowledge_base = form.cleaned_data["knowledge_base"]
        ai_model = form.cleaned_data["ai_model"]

        config = {
            ChatGPTType.CONFIG_API_KEY: api_key,
            ChatGPTType.CONFIG_AI_MODEL: ai_model,
            ChatGPTType.CONFIG_RULES: rules,
            ChatGPTType.CONFIG_KNOWLEDGE_BASE: knowledge_base,
        }

        self.object = ExternalService(
            uuid=uuid4(),
            org=self.org,
            external_service_type=ChatGPTType.slug,
            config=config,
            name=name,
            created_by=self.request.user,
            modified_by=self.request.user,
        )

        self.object.save()
        return super().form_valid(form)

    form_class = Form
    template_name = "external_services/types/chatgpt/connect.haml"
