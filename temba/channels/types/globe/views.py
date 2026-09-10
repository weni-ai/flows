from django import forms
from django.utils.translation import ugettext_lazy as _

from temba.channels.models import Channel
from temba.channels.views import AuthenticatedExternalClaimView, ClaimViewMixin


class ClaimView(AuthenticatedExternalClaimView):
    class GlobeClaimForm(ClaimViewMixin.Form):
        number = forms.CharField(
            max_length=14,
            min_length=1,
            label=_("Number"),
            help_text=_("The short code you have been assigned by Globe Labs. Example: 15543"),
        )
        app_id = forms.CharField(label=_("Application ID"), help_text=_("The ID of your Globe Labs application"))
        app_secret = forms.CharField(
            label=_("Application secret"), help_text=_("The secret assigned to your Globe Labs application")
        )
        passphrase = forms.CharField(
            label=_("Passphrase"), help_text=_("The passphrase assigned to you by Globe Labs to support sending")
        )

    form_class = GlobeClaimForm

    def get_submitted_country(self, data):  # pragma: needs cover
        return "PH"

    def form_valid(self, form):
        org = self.request.user.get_org()

        data = form.cleaned_data
        self.object = Channel.add_config_external_channel(
            org,
            self.request.user,
            "PH",
            data["number"],
            self.channel_type,
            dict(app_id=data["app_id"], app_secret=data["app_secret"], passphrase=data["passphrase"]),
            role=Channel.ROLE_SEND + Channel.ROLE_RECEIVE,
        )

        return super(AuthenticatedExternalClaimView, self).form_valid(form)
