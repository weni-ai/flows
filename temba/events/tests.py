import json

from mock import patch
from temba.events.models import AirtimeEvent, TransferAirtime
from temba.tests import TembaTest, MockResponse


class AirtimeEventTest(TembaTest):
    def setUp(self):
        super(AirtimeEventTest, self).setUp()

        self.org.connect_transferto('mylogin', 'api_token')
        self.airtime_event = AirtimeEvent.objects.create(org=self.org, phone_number='+250788123123', amount='100',
                                                         created_by=self.admin, modified_by=self.admin)

    def test_translate_transferto_api_response(self):
        self.assertEqual(AirtimeEvent.translate_transferto_response_content_as_json(""), dict())

        self.assertEqual(AirtimeEvent.translate_transferto_response_content_as_json("foo"), dict())

        self.assertEqual(AirtimeEvent.translate_transferto_response_content_as_json("foo\r\nbar"), dict())

        self.assertEqual(AirtimeEvent.translate_transferto_response_content_as_json("foo=allo\r\nbar"),
                         dict(foo='allo'))

        self.assertEqual(AirtimeEvent.translate_transferto_response_content_as_json("foo=allo\r\nbar=1,2,3\r\n"),
                         dict(foo='allo', bar=['1', '2', '3']))

    @patch('temba.events.models.AirtimeEvent.post_transferto_api_response')
    def test_get_transferto_response_json(self, mock_post_transferto):
        mock_post_transferto.return_value = MockResponse(200, "foo=allo\r\nbar=1,2,3\r\n")

        self.assertEqual((dict(foo="allo", bar=["1", "2", "3"]), "foo=allo\r\nbar=1,2,3\r\n"),
                         self.airtime_event.get_transferto_response_json(action='command'))

        mock_post_transferto.assert_called_once_with('mylogin', 'api_token', action='command')

    @patch('temba.events.models.AirtimeEvent.get_transferto_response_json')
    def test_fetch_msisdn_info(self, mock_transferto_response_json):
        mock_transferto_response_json.return_value = (dict(foo="allo", bar=["1", "2", "3"]),
                                                      "foo=allo\r\nbar=1,2,3\r\n")

        self.assertFalse(self.airtime_event.dump_content)
        self.assertFalse(self.airtime_event.data_json)

        self.airtime_event.fetch_msisdn_info()

        airtime_event = AirtimeEvent.objects.get(pk=self.airtime_event.pk)
        self.assertTrue(airtime_event.dump_content)
        self.assertTrue(airtime_event.data_json)
        self.assertEqual(airtime_event.data_json, json.dumps(dict(foo="allo", bar=["1", "2", "3"])))
        self.assertEqual(airtime_event.dump_content, "foo=allo\r\nbar=1,2,3\r\n")

    @patch('temba.events.models.AirtimeEvent.get_transferto_response_json')
    def test_update_denomination(self, mock_transferto_response_json):
        mock_transferto_response_json.return_value = (dict(foo="allo", bar=["1", "2", "3"]),
                                                      "foo=allo\r\nbar=1,2,3\r\n")

        self.assertFalse(self.airtime_event.denomination)
        self.assertIsNone(self.airtime_event.update_denomination())
        self.assertFalse(self.airtime_event.denomination)

        self.airtime_event.data_json = json.dumps(dict(foo="allo", bar=["1", "2", "3"]))
        self.airtime_event.dump_content = "foo=allo\r\nbar=1,2,3\r\n"
        self.airtime_event.save()

        self.assertFalse(self.airtime_event.update_denomination())
        self.assertFalse(self.airtime_event.denomination)

        self.airtime_event.data_json = json.dumps(dict(foo="allo", bar=["1", "2", "3"], product_list=1000))
        self.airtime_event.dump_content = "foo=allo\r\nbar=1,2,3\r\nproduct_list=1000\r\n"
        self.airtime_event.save()

        self.assertFalse(self.airtime_event.update_denomination())
        self.assertFalse(self.airtime_event.denomination)

        self.airtime_event.data_json = json.dumps(dict(foo="allo", bar=["1", "2", "3"], product_list=50))
        self.airtime_event.dump_content = "foo=allo\r\nbar=1,2,3\r\nproduct_list=50\r\n"
        self.airtime_event.save()

        self.assertTrue(self.airtime_event.update_denomination())

        airtime_event = AirtimeEvent.objects.get(pk=self.airtime_event.pk)
        self.assertTrue(airtime_event.denomination)
        self.assertEqual(airtime_event.denomination, str(50.0))

        self.airtime_event.data_json = json.dumps(dict(foo="allo", bar=["1", "2", "3"], product_list=[20, 50, 80, 200]))
        self.airtime_event.dump_content = "foo=allo\r\nbar=1,2,3\r\nproduct_list=20,50,80,200\r\n"
        self.airtime_event.save()

        self.assertTrue(self.airtime_event.update_denomination())

        airtime_event = AirtimeEvent.objects.get(pk=self.airtime_event.pk)
        self.assertTrue(airtime_event.denomination)
        self.assertEqual(airtime_event.denomination, str(80.0))

    @patch('temba.events.models.AirtimeEvent.get_transferto_response_json')
    def test_transfer_airtime(self, mock_transferto_response_json):
        mock_transferto_response_json.side_effect = [(dict(error_code='0', reserve_id='123'),
                                                      "reserve_id=123\r\nerror_code=0\r\n"),
                                                     (dict(error_code='0', operator_reference='456'),
                                                      "operator_reference=456\r\nerror_code=0\r\n")]

        self.assertFalse(self.airtime_event.denomination)
        self.assertFalse(TransferAirtime.objects.all())

        self.airtime_event.transfer_airtime()
        self.assertEqual(mock_transferto_response_json.call_count, 0)

        self.assertFalse(TransferAirtime.objects.all())
        self.airtime_event.denomination = 50
        self.airtime_event.save()

        self.airtime_event.transfer_airtime()

        self.assertTrue(TransferAirtime.objects.all())
        self.assertEqual(TransferAirtime.objects.all().count(), 1)
        self.assertEqual(mock_transferto_response_json.call_count, 2)

        transfer = TransferAirtime.objects.get()
        self.assertEqual(transfer.error_code, '0')
