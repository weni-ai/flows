import hashlib
import json

import time

import requests
from django.db import models

from smartmin.models import SmartModel
from temba.orgs.models import Org, TRANSFERTO_ACCOUNT_LOGIN, TRANSFERTO_AIRTIME_API_TOKEN


TRANSFERTO_AIRTIME_API_URL = 'https://fm.transfer-to.com/cgi-bin/shop/topup'


class AirtimeEvent(SmartModel):
    org = models.ForeignKey(Org)
    phone_number = models.CharField(max_length=64)
    amount = models.FloatField()
    denomination = models.CharField(max_length=32, null=True, blank=True)
    dump_content = models.TextField(null=True, blank=True)
    data_json = models.TextField(null=True, blank=True)

    @classmethod
    def post_transferto_api_response(cls, login, token, **kwargs):
        key = str(int(time.time()))
        md5 = hashlib.md5()
        md5.update(login + token + key)
        md5 = md5.hexdigest()

        data = kwargs
        data.update(dict(login=login, key=key, md5=md5))

        response = requests.post(TRANSFERTO_AIRTIME_API_URL, data)

        return response

    @classmethod
    def translate_transferto_response_content_as_json(cls, content):
        splitted_content = content.split('\r\n')
        output = dict()

        for elt in splitted_content:
            if elt and elt.find('=') > 0:
                key, val = tuple(elt.split('='))
                if val.find(',') > 0:
                    val = val.split(',')

                output[key] = val

        return output

    def get_transferto_response_json(self, **kwargs):
        config = self.org.config_json()
        login = config.get(TRANSFERTO_ACCOUNT_LOGIN)
        token = config.get(TRANSFERTO_AIRTIME_API_TOKEN)

        response = AirtimeEvent.post_transferto_api_response(login, token, **kwargs)
        content_json = AirtimeEvent.translate_transferto_response_content_as_json(response.content)

        return content_json, response.content

    def fetch_msisdn_info(self):
        content_json, content = self.get_transferto_response_json(action='msisdn_info', destination_msisdn=self.phone_number)

        AirtimeEvent.objects.filter(pk=self.pk).update(**{'data_json': json.dumps(content_json),
                                                          'dump_content': content})

    def update_denomination(self):
        if not self.data_json or not self.amount:
            return

        content_json = json.loads(self.data_json)
        product_list = content_json.get('product_list', [])

        if not isinstance(product_list, list):
            product_list = [product_list]

        targeted_prices = [float(i) for i in product_list if float(i) <= float(self.amount)]

        updated = False
        if targeted_prices:
            denomination = max(targeted_prices)
            updated = AirtimeEvent.objects.filter(pk=self.pk).update(**{'denomination': denomination})

        return bool(updated)

    def transfer_airtime(self):
        if not self.denomination:
            return

        content_json, content = self.get_transferto_response_json(action='reserve_id')
        transaction_id = content_json.get('reserve_id')

        transfer = TransferAirtime.objects.create(event=self, transaction_id=transaction_id,
                                                  created_by=self.created_by, modified_by=self.created_by)
        return transfer.topup()


class TransferAirtime(SmartModel):
    event = models.ForeignKey(AirtimeEvent)
    transaction_id = models.CharField(max_length=256)
    error_code = models.CharField(max_length=64, null=True, blank=True)
    error_txt = models.CharField(max_length=512, null=True, blank=True)
    reference_operator = models.CharField(max_length=64, null=True, blank=True)
    airtime_amount = models.CharField(max_length=32, null=True, blank=True)
    dump_content = models.TextField(null=True, blank=True)
    data_json = models.TextField(null=True, blank=True)

    def topup(self):
        content_json, content = self.event.get_transferto_response_json(action='topup', reserve_id=self.transaction_id,
                                                                         destination_msisdn=self.event.phone_number,
                                                                         product=self.event.denomination)

        update_fields = dict()
        error_code = content_json.get('error_code', None)
        update_fields['error_code'] = error_code
        update_fields['error_txt'] = content_json.get('error_txt', None)
        update_fields['reference_operator'] = content_json.get('reference_operator', None)
        update_fields['airtime_amount'] = content_json.get('airtime_amount', None)
        update_fields['data_json'] = json.dumps(content_json)
        update_fields['dump_content'] = content

        if update_fields:
            TransferAirtime.objects.filter(pk=self.pk).update(**update_fields)

        return error_code
