from smartmin.views import SmartFormView

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from ...models import Channel
from ...views import ClaimViewMixin


class ClaimView(ClaimViewMixin, SmartFormView):
    class Form(ClaimViewMixin.Form):
        user_name = forms.CharField(label=_("User name"), required=False)
        password = forms.CharField(label=_("Password"), required=False)
        smtp_host = forms.CharField(label=_("smtp_host"), required=False)
        smtp_port = forms.IntegerField(label=_("smtp_port"), required=False)
        imap_host = forms.CharField(label=_("imap_host"), required=False)
        imap_port = forms.IntegerField(label=_("imap_port"), required=False)
        token = forms.CharField(label=_("token"), required=False)
        refresh_token = forms.CharField(label=_("refresh_token"), required=False)

    form_class = Form

    def form_valid(self, form):
        org = self.request.user.get_org()
        cleaned_data = form.cleaned_data

        config = {key: value for key, value in cleaned_data.items() if value is not None}
        config[Channel.CONFIG_CALLBACK_DOMAIN] = settings.HOSTNAME

        self.object = Channel.create(
            org,
            self.request.user,
            None,
            self.channel_type,
            name=cleaned_data["user_name"],
            address=cleaned_data["user_name"],
            config=config,
        )

        return super().form_valid(form)
