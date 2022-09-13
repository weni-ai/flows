from django import forms
from django.utils.translation import ugettext_lazy as _
from temba.api.models import APIToken

from temba.tickets.models import Ticketer
from temba.tickets.views import BaseConnectView
from temba.utils.uuid import uuid4
from django.core.exceptions import ValidationError
import requests

class ConnectView(BaseConnectView):
  class Form(BaseConnectView.Form):
    sector_uuid = forms.CharField(
      label=_("Sector UUID"), help_text=_("Sector UUID")
    )

    def clean(self):
      from .type import WeniChatsType
      sector_uuid = self.cleaned_data.get("sector_uuid")
      if not sector_uuid:
        raise forms.ValidationError(_("Invalid sector UUID"))

      existing = Ticketer.objects.filter(
        is_active=True,
        ticketer_type=WeniChatsType.slug,
        config__contains=sector_uuid
      )

      if existing:
        if existing.org_id == self.request.user.get_org().id:
          raise ValidationError(_("A Weni Chats ticketer for this sector already exists in this workspace."))
        raise ValidationError(_("A Weni Chats ticketer for this sector already exists in another workspace."))


  def form_valid(self, form):
    from .type import WeniChatsType
    sector_uuid = form.cleaned_data["sector_uuid"]

    user_token = self.request.user.api_token
    project_flows_uuid = f"{self.request.user.get_org().uuid}"

    flows_response = requests.post(
      url = WeniChatsType.base_url + '/flows',
      data = {'project_flows_uuid': project_flows_uuid},
      headers = {'Content-Type': 'application/json', 'Authorization': 'Token ' + user_token},
    )
    
    
    if flows_response.status_code != 201:
      raise Exception(_(f"This ticketer integration with Weni Chats couldn't be created, try again. status code: {flows_response.status_code}"))

    auth_token = flows_response.json()["uuid"]

    sectors_response =  requests.get(
      url = WeniChatsType.base_url + '/sectors',
      headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + auth_token},
    )
    
    if sectors_response.status_code != 200:
      raise Exception(_("This ticketer integration with Weni Chats couldn't be created, try again."))

    current_sector = {}


    for sector in sectors_response.json()["results"]:
      if sector["uuid"] == sector_uuid:
        current_sector = sector
    
    if not current_sector:
      raise Exception(_("This ticketer integration with Weni Chats couldn't be created, the defined sector not exists."))

    config = {
      WeniChatsType.CONFIG_SECTOR_UUID: sector_uuid,
      WeniChatsType.CONFIG_AUTH_TOKEN: auth_token,
      WeniChatsType.CONFIG_PROJECT_FLOWS_UUID: project_flows_uuid
    }

    # TODO: Definir como será o nome do ticketer
    self.object = Ticketer(
      uuid=uuid4(),
      org=self.org,
      ticketer_type=WeniChatsType.slug,
      config=config,
      name=current_sector["name"],
      created_by=self.request.user,
      modified_by=self.request.user,
    )
    
    self.object.save()
    return super().form_valid(form)
    
  form_class = Form
  template_name = "tickets/types/wenichats/connect.haml"