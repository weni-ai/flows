from smartmin.views import SmartFormView, SmartView

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.views import View

from temba.orgs.views import OrgPermsMixin

from ...models import Channel
from ...views import ClaimViewMixin
from . import outlook


class ClaimView(ClaimViewMixin, SmartFormView):
    class Form(ClaimViewMixin.Form):
        username = forms.CharField(label=_("username"), required=False)
        password = forms.CharField(label=_("password"), required=False)
        smtp_host = forms.CharField(label=_("smtp_host"), required=False)
        smtp_port = forms.IntegerField(label=_("smtp_port"), required=False)
        imap_host = forms.CharField(label=_("imap_host"), required=False)
        imap_port = forms.IntegerField(label=_("imap_port"), required=False)
        access_token = forms.CharField(label=_("access_token"), required=False)
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
            name=cleaned_data["username"],
            address=cleaned_data["username"],
            config=config,
        )

        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["outlook_enabled"] = bool(settings.APP_MICROSOFT_CLIENT_ID)
        return context


class _OutlookView(OrgPermsMixin, SmartView, View):
    permission = "channels.channel_claim"
    channel_type = None

    def __init__(self, channel_type):
        self.channel_type = channel_type
        super().__init__()

    messages_by_code = {
        "invalid_address": _("Enter the mailbox address."),
        "access_denied": _("Sign in was not completed. You can try again."),
        "state": _("Sign in again to connect the mailbox."),
        "mailbox_mismatch": _("Microsoft did not confirm that mailbox. An alias cannot be connected."),
        "already_connected": _("This mailbox is already connected."),
        "token": _("Microsoft did not complete the sign-in."),
        "invalid_token": _("Microsoft did not complete the sign-in."),
    }

    def _claim_url(self):
        return reverse("channels.types.email.claim")

    def _callback_uri(self, request):
        return request.build_absolute_uri(reverse("channels.types.email.outlook_callback"))

    def _tell(self, request, exc):
        if exc.admin_consent and settings.APP_MICROSOFT_CLIENT_ID:
            messages.error(
                request,
                format_html(
                    '{} <a href="{}">{}</a>',
                    _("A Microsoft 365 administrator must approve this app before the mailbox can be connected."),
                    outlook.admin_consent_link(),
                    _("Ask a Microsoft 365 administrator to approve the app"),
                ),
            )
            return

        if exc.show_description and exc.description:
            messages.error(request, exc.description)
            return

        messages.error(request, self.messages_by_code.get(exc.code, self.messages_by_code["state"]))


class OutlookStart(_OutlookView):
    def post(self, request, *args, **kwargs):
        claim_url = self._claim_url()
        if not settings.APP_MICROSOFT_CLIENT_ID:
            return HttpResponseRedirect(claim_url)

        username = outlook.normalize_mailbox(request.POST.get("username"))
        if not username:
            messages.error(request, self.messages_by_code["invalid_address"])
            return HttpResponseRedirect(claim_url)

        return HttpResponseRedirect(
            outlook.begin(request.user.get_org(), request.user, username, self._callback_uri(request))
        )


class OutlookCallback(_OutlookView):
    def get(self, request, *args, **kwargs):
        claim_url = self._claim_url()
        error = request.GET.get("error")
        if error:
            outlook.pop_attempt(request.GET.get("state"))
            org = request.user.get_org()
            outlook.record_failure(
                org.id,
                request.user.id,
                error,
                account_id=outlook.account_identifier(org),
                correlation_id=outlook.correlation_identifier(request),
                report=False,
            )
            self._tell(request, outlook.rejection_from_provider(error, request.GET.get("error_description")))
            return HttpResponseRedirect(claim_url)

        org = request.user.get_org()
        try:
            channel = outlook.complete(
                org,
                request.user,
                request.GET.get("code"),
                request.GET.get("state"),
                self._callback_uri(request),
                account_id=outlook.account_identifier(org),
                correlation_id=outlook.correlation_identifier(request),
            )
        except outlook.ConsentError as exc:
            self._tell(request, exc)
            return HttpResponseRedirect(claim_url)

        return HttpResponseRedirect(reverse("channels.channel_read", args=[channel.uuid]))
