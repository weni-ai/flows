from smartmin.views import SmartReadView

from django import forms
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

from temba.orgs.views import OrgPermsMixin
from temba.tickets.models import Ticketer
from temba.tickets.views import BaseConnectView
from temba.utils.uuid import uuid4
from temba.utils.views import ComponentFormMixin


class ConnectView(BaseConnectView):
    class Form(BaseConnectView.Form):
        oauth_token = forms.CharField(label=_("OAuth Token"), help_text=_("OAuth Token"))
        freshchat_domain = forms.CharField(label=_("Freshchat Domain"), help_text=_("Freshchat Domain"))

        def clean(self):
            from .type import FreshchatType

            oauth_token = self.cleaned_data.get("oauth_token")
            if not oauth_token:
                raise forms.ValidationError(_("OAuth Token is required"))

            freshchat_domain = self.cleaned_data.get("freshchat_domain")
            if not freshchat_domain:
                raise forms.ValidationError(_("Freshchat Domain is required"))

            existing = Ticketer.objects.filter(
                is_active=True,
                ticketer_type=FreshchatType.slug,
                config__contains=freshchat_domain,
            )

            if existing:
                raise forms.ValidationError(
                    _("A Freshchat ticketer for this domain already exists in this workspace.")
                )

            if existing.org_id != self.request.user.get_org().id:
                raise forms.ValidationError(
                    _("A Freshchat ticketer for this domain already exists in another workspace.")
                )

            return self.cleaned_data

    def form_valid(self, form):
        from .type import FreshchatType

        oauth_token = form.cleaned_data["oauth_token"]
        freshchat_domain = form.cleaned_data["freshchat_domain"]

        config = {
            FreshchatType.CONFIG_OAUTH_TOKEN: oauth_token,
            FreshchatType.CONFIG_FRESHCHAT_DOMAIN: freshchat_domain,
        }

        self.object = Ticketer(
            uuid=uuid4(),
            org=self.org,
            ticketer_type=FreshchatType.slug,
            config=config,
            name=freshchat_domain,
            created_by=self.request.user,
            modified_by=self.request.user,
        )

        self.object.save()
        return super().form_valid(form)

    form_class = Form
    template_name = "tickets/types/freshchat/connect.haml"


class ConfigureView(ComponentFormMixin, OrgPermsMixin, SmartReadView):
    model = Ticketer
    fields = ()
    permission = "tickets.ticketer_configure"
    slug_url_kwarg = "uuid"
    template_name = "tickets/types/freshchat/configure.haml"

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(org=self.get_user().get_org())

    def get_gear_links(self):
        links = []
        if self.has_org_perm("tickets.ticket_list"):
            links.append(dict(title=_("Tickets"), href=reverse("tickets.ticket_list")))
        return links

    def get_context_data(self, **kwargs):
        from .type import FreshchatType

        oauth_token = self.object.config[FreshchatType.CONFIG_OAUTH_TOKEN]
        freshchat_domain = self.object.config[FreshchatType.CONFIG_FRESHCHAT_DOMAIN]

        # Build webhook URL
        domain = self.object.org.get_brand_domain()
        webhook_url = f"https://{domain}/mr/tickets/types/freshchat/webhook/{self.object.uuid}"

        context = super().get_context_data(**kwargs)
        context["oauth_token"] = oauth_token
        context["freshchat_domain"] = freshchat_domain
        context["webhook_url"] = webhook_url
        return context
