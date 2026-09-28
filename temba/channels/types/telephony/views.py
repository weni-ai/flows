import phonenumbers
from smartmin.views import SmartFormView

from django import forms
from django.utils.translation import ugettext_lazy as _

from temba.contacts.models import URN

from ...models import Channel
from ...views import ALL_COUNTRIES, ClaimViewMixin

INVALID_PHONE_NUMBER = _("Invalid phone number")


class ClaimView(ClaimViewMixin, SmartFormView):
    class Form(ClaimViewMixin.Form):
        name = forms.CharField(
            label=_("Name"),
            max_length=64,
            help_text=_("Name for this telephony channel"),
        )
        country = forms.ChoiceField(
            choices=ALL_COUNTRIES,
            label=_("Country"),
            help_text=_("Country of the telephone number"),
        )
        phone_number = forms.CharField(
            label=_("Telephone number (DID)"),
            help_text=_("The inbound number callers dial, in E.164 format (e.g. +12065551212)"),
        )

        def clean_phone_number(self):
            number = self.cleaned_data["phone_number"]
            country = self.data.get("country")

            normalized = URN.normalize_number(number, country)
            if not URN.validate(URN.from_parts(URN.TEL_SCHEME, normalized), country):
                raise forms.ValidationError(INVALID_PHONE_NUMBER)

            try:
                parsed = phonenumbers.parse(normalized, None)
            except phonenumbers.NumberParseException:
                raise forms.ValidationError(INVALID_PHONE_NUMBER)

            if not phonenumbers.is_valid_number(parsed):
                raise forms.ValidationError(INVALID_PHONE_NUMBER)

            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    form_class = Form

    def form_valid(self, form):
        org = self.request.user.get_org()
        data = form.cleaned_data

        self.object = Channel.create(
            org,
            self.request.user,
            data["country"],
            self.channel_type,
            config={},
            name=data["name"],
            address=data["phone_number"],
        )

        return super().form_valid(form)
