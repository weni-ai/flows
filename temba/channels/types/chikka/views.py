from django import forms
from django.utils.translation import ugettext_lazy as _

from temba.channels.views import ALL_COUNTRIES, AuthenticatedExternalClaimView, ClaimViewMixin
from temba.utils.fields import SelectWidget


class ClaimView(AuthenticatedExternalClaimView):
    class ChikkaForm(ClaimViewMixin.Form):
        country = forms.ChoiceField(
            choices=ALL_COUNTRIES,
            widget=SelectWidget(attrs={"searchable": True}),
            label=_("Country"),
            help_text=_("The country this phone number is used in"),
        )
        number = forms.CharField(
            max_length=14, min_length=4, label=_("Number"), help_text=_("The short code you're connecting")
        )
        username = forms.CharField(
            label=_("Client ID"), help_text=_("The client ID found on your Chikka API credentials page")
        )
        password = forms.CharField(
            label=_("Secret key"), help_text=_("The secret key found on your Chikka API credentials page")
        )

    form_class = ChikkaForm

    def get_country(self, obj):
        return "Philippines"

    def get_submitted_country(self, data):
        return "PH"
