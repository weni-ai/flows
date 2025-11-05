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

            errors = []
            oauth_token = self.cleaned_data.get("oauth_token")
            if not oauth_token:
                errors.append(_("OAuth Token is required"))

            freshchat_domain = self.cleaned_data.get("freshchat_domain")
            if not freshchat_domain:
                errors.append(_("Freshchat Domain is required"))

            if errors:
                raise forms.ValidationError(errors)

            current_org = self.request.user.get_org()

            # Check if ticketer exists in this workspace
            existing_same_org = Ticketer.objects.filter(
                is_active=True,
                ticketer_type=FreshchatType.slug,
                org=current_org,
                config__freshchat_domain=freshchat_domain,
            ).first()

            if existing_same_org:
                raise forms.ValidationError(
                    _("A Freshchat ticketer for this domain already exists in this workspace.")
                )

            # Check if ticketer exists in another workspace
            existing_other_org = (
                Ticketer.objects.filter(
                    is_active=True,
                    ticketer_type=FreshchatType.slug,
                    config__freshchat_domain=freshchat_domain,
                )
                .exclude(org=current_org)
                .first()
            )

            if existing_other_org:
                raise forms.ValidationError(
                    _("A Freshchat ticketer for this domain already exists in another workspace.")
                )

            return self.cleaned_data

    def get_success_url(self):
        return reverse("tickets.types.freshchat.configure", args=[self.object.uuid])

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
        # Build webhook URL
        domain = self.object.org.get_brand_domain()
        webhook_url = f"https://{domain}/mr/tickets/types/freshchat/webhook/{self.object.uuid}"

        context = super().get_context_data(**kwargs)
        context["webhook_url"] = webhook_url
        return context
