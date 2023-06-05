from django import forms
from django.utils.translation import ugettext_lazy as _

from temba.externals.models import ExternalService
from temba.externals.views import BaseConnectView
from temba.utils.uuid import uuid4

AI_MODELS = [
        ("gpt-3.5-turbo", "gpt-3.5-turbo"),
        ("gpt-4", "gpt-4"),
    ]

class ConnectView(BaseConnectView):
    class Form(BaseConnectView.Form):
        service_name = forms.CharField(max_length=256, label=_("Name"), help_text=_("Name"))
        api_key = forms.CharField(
            label=_("ChatGPT API Key"), help_text=_("ChatGPT API Key")
        )
        ai_model = forms.ChoiceField(
            label=("A.I Model"),
            help_text=_("A.I Model"),
            choices=AI_MODELS,
            initial="gpt-3.5-turbo",
        )

        def clean(self):
            api_key = self.cleaned_data.get("api_key")
            if not api_key:
                raise forms.ValidationError(_("Invalid API Key"))

    def form_valid(self, form):
        from .type import ChatGPTType
        
        service_name = form.cleaned_data["service_name"]
        api_key = form.cleaned_data["api_key"]
        ai_model = form.cleaned_data["ai_model"]

        config = {
            ChatGPTType.CONFIG_API_KEY: api_key,
            ChatGPTType.CONFIG_AI_MODEL: ai_model,
        }

        self.object = ExternalService(
            uuid=uuid4(),
            org=self.org,
            external_service_type=ChatGPTType.slug,
            config=config,
            name=service_name,
            created_by=self.request.user,
            modified_by=self.request.user,
        )

        self.object.save()
        return super().form_valid(form)

    form_class = Form

