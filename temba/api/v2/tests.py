import base64
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch
from urllib.parse import quote_plus

import iso8601
import pytz
from rest_framework import serializers
from rest_framework.test import APIClient

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.contrib.gis.geos import GEOSGeometry
from django.core.cache import cache
from django.db import connection
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from temba.api.models import APIToken, Resthook, WebHookEvent
from temba.api.v2.views import (
    ContactsTemplatesEndpoint,
    ExternalServicesEndpoint,
    FilterTemplatesEndpoint,
    FlowsLabelsEndpoint,
    ProductsEndpoint,
    TemplatesEndpoint,
    WhatsappFlowsEndpoint,
)
from temba.archives.models import Archive
from temba.campaigns.models import Campaign, CampaignEvent
from temba.channels.models import Channel, ChannelEvent
from temba.channels.types.whatsapp.type import (
    CONFIG_FB_ACCESS_TOKEN,
    CONFIG_FB_BUSINESS_ID,
    CONFIG_FB_NAMESPACE,
    CONFIG_FB_TEMPLATE_LIST_DOMAIN,
)
from temba.classifiers.models import Classifier
from temba.classifiers.types.luis import LuisType
from temba.classifiers.types.wit import WitType
from temba.contacts.models import Contact, ContactField, ContactGroup, ContactURN
from temba.externals.models import ExternalService
from temba.flows.models import Flow, FlowLabel, FlowRun, FlowStart
from temba.globals.models import Global
from temba.locations.models import AdminBoundary, BoundaryAlias
from temba.msgs.models import Broadcast, Label, Msg
from temba.orgs.models import Org
from temba.templates.models import Template, TemplateTranslation
from temba.tests import AnonymousOrg, TembaTest, matchers, mock_mailroom
from temba.tests.engine import MockSessionWriter
from temba.tickets.models import Ticket, Ticketer, Topic
from temba.tickets.types.mailgun import MailgunType
from temba.tickets.types.zendesk import ZendeskType
from temba.triggers.models import Trigger
from temba.utils import json
from temba.wpp_flows.models import WhatsappFlow
from temba.wpp_products.models import Catalog, Product

from . import fields
from .serializers import ExternalServicesReadSerializer, ProductReadSerializer, format_datetime, normalize_extra

NUM_BASE_REQUEST_QUERIES = 6  # number of db queries required for any API request


class APITest(TembaTest):
    def setUp(self):
        super().setUp()

        self.joe = self.create_contact("Joe Blow", phone="0788123123")
        self.frank = self.create_contact("Frank", urns=["twitter:franky"])

        self.twitter = self.create_channel("TT", "Twitter Channel", "billy_bob")

        self.hans = self.create_contact("Hans Gruber", phone="+4921551511", org=self.org2)

        self.org2channel = self.create_channel("A", "Org2Channel", "123456", country="RW", org=self.org2)

        # this is needed to prevent REST framework from rolling back transaction created around each unit test
        connection.settings_dict["ATOMIC_REQUESTS"] = False

    def tearDown(self):
        super().tearDown()

        connection.settings_dict["ATOMIC_REQUESTS"] = True

    def fetchHTML(self, url, query=None):
        if query:
            url += "?" + query

        return self.client.get(url, HTTP_X_FORWARDED_HTTPS="https")

    def fetchJSON(self, url, query=None, raw_url=False, readonly_models: set = None):
        if not raw_url:
            url += ".json"
            if query:
                url += "?" + query

        with self.mockReadOnly(assert_models=readonly_models):
            response = self.client.get(url, content_type="application/json", HTTP_X_FORWARDED_HTTPS="https")

        # this will fail if our response isn't valid json
        response.json()

        return response

    def postJSON(self, url, query, data, **kwargs):
        url += ".json"
        if query:
            url = url + "?" + query

        return self.client.post(
            url, json.dumps(data), content_type="application/json", HTTP_X_FORWARDED_HTTPS="https", **kwargs
        )

    def deleteJSON(self, url, query=None):
        url += ".json"
        if query:
            url = url + "?" + query

        return self.client.delete(url, content_type="application/json", HTTP_X_FORWARDED_HTTPS="https")

    def assertEndpointAccess(self, url, query=None, fetch_returns=200):
        self.client.logout()

        # 403 if not authenticated but can read docs
        response = self.fetchHTML(url, query)
        self.assertEqual(response.status_code, 403)

        # same for non-org user
        self.login(self.non_org_user)
        response = self.fetchHTML(url, query)
        self.assertEqual(response.status_code, 403)

        # viewers can do gets on some endpoints
        self.login(self.user)
        response = self.fetchHTML(url, query)
        self.assertIn(response.status_code, [200, 403])

        # same with JSON
        response = self.fetchJSON(url, query)
        self.assertIn(response.status_code, [200, 403])

        # but viewers should always get a forbidden when posting
        response = self.postJSON(url, query, {})
        self.assertEqual(response.status_code, 403)

        # 200 for administrator assuming this endpoint supports fetches
        self.login(self.admin)
        response = self.fetchHTML(url, query)
        self.assertEqual(response.status_code, fetch_returns)

        # 405 for OPTIONS requests
        response = self.client.options(url, HTTP_X_FORWARDED_HTTPS="https")
        self.assertEqual(response.status_code, 405)

    def assertResultsById(self, response, expected):
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["id"] for r in response.json()["results"]], [o.pk for o in expected])

    def assertResultsByUUID(self, response, expected):
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["uuid"] for r in response.json()["results"]], [o.uuid for o in expected])

    def assertResponseError(self, response, field, expected_message, status_code=400):
        self.assertEqual(response.status_code, status_code)
        resp_json = response.json()
        if field:
            self.assertIn(field, resp_json)
            self.assertIsInstance(resp_json[field], list)
            self.assertIn(expected_message, resp_json[field])
        else:
            self.assertIsInstance(resp_json, dict)
            self.assertIn("detail", resp_json)
            self.assertEqual(resp_json["detail"], expected_message)

    def assert404(self, response):
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Not found."})

    @override_settings(REST_HANDLE_EXCEPTIONS=True)
    @patch("temba.api.v2.views.FieldsEndpoint.get_queryset")
    def test_error_handling(self, mock_get_queryset):
        mock_get_queryset.side_effect = ValueError("DOH!")

        self.login(self.admin)

        response = self.client.get(
            reverse("api.v2.fields") + ".json", content_type="application/json", HTTP_X_FORWARDED_HTTPS="https"
        )
        self.assertContains(response, "Server Error. Site administrators have been notified.", status_code=500)

    def test_serializer_fields(self):
        def assert_field(f, *, submissions: dict, representations: dict):
            f._context = {"org": self.org}  # noqa

            for submitted, expected in submissions.items():
                if isinstance(expected, type) and issubclass(expected, Exception):
                    with self.assertRaises(expected, msg=f"expected exception for '{submitted}'"):
                        f.to_internal_value(submitted)
                else:
                    self.assertEqual(
                        f.to_internal_value(submitted), expected, f"to_internal_value mismatch for '{submitted}'"
                    )

            for value, expected in representations.items():
                self.assertEqual(f.to_representation(value), expected, f"to_representation mismatch for '{value}'")

        group = self.create_group("Customers")
        field_obj = ContactField.get_or_create(
            self.org, self.admin, "registered", "Registered On", value_type=ContactField.TYPE_DATETIME
        )
        flow = self.create_flow()
        campaign = Campaign.create(self.org, self.admin, "Reminders #1", group)
        event = CampaignEvent.create_flow_event(
            self.org, self.admin, campaign, field_obj, 6, CampaignEvent.UNIT_HOURS, flow, delivery_hour=12
        )

        field = fields.LimitedListField(child=serializers.IntegerField(), source="test")

        self.assertEqual(field.to_internal_value([1, 2, 3]), [1, 2, 3])
        self.assertRaises(serializers.ValidationError, field.to_internal_value, list(range(101)))  # too long

        field = fields.CampaignField(source="test")
        field._context = {"org": self.org}

        self.assertEqual(field.to_internal_value(campaign.uuid), campaign)
        self.assertRaises(serializers.ValidationError, field.to_internal_value, {"id": 3})  # not a string or int

        field = fields.CampaignEventField(source="test")
        field._context = {"org": self.org}

        self.assertEqual(field.to_internal_value(event.uuid), event)

        field._context = {"org": self.org2}

        self.assertRaises(serializers.ValidationError, field.to_internal_value, event.uuid)

        deleted_channel = self.create_channel("A", "My Android", "123456")
        deleted_channel.is_active = False
        deleted_channel.save(update_fields=("is_active",))

        assert_field(
            fields.ChannelField(source="test"),
            submissions={self.channel.uuid: self.channel, deleted_channel.uuid: serializers.ValidationError},
            representations={self.channel: {"uuid": str(self.channel.uuid), "name": "Test Channel"}},
        )

        assert_field(
            fields.ContactField(source="test"),
            submissions={
                self.joe.uuid: self.joe,  # by UUID
                self.joe.get_urn().urn: self.joe,  # by URN
                0: serializers.ValidationError,
                (self.joe.uuid, self.frank.uuid): serializers.ValidationError,
            },
            representations={self.joe: {"uuid": str(self.joe.uuid), "name": "Joe Blow"}},
        )

        assert_field(
            fields.ContactField(source="test", many=True),
            submissions={
                (self.joe.uuid, self.frank.uuid): [self.joe, self.frank],
                self.joe.uuid: serializers.ValidationError,
            },
            representations={
                (self.joe, self.frank): [
                    {"uuid": str(self.joe.uuid), "name": "Joe Blow"},
                    {"uuid": str(self.frank.uuid), "name": "Frank"},
                ]
            },
        )

        assert_field(
            fields.ContactGroupField(source="test"),
            submissions={group.uuid: group},
            representations={group: {"uuid": str(group.uuid), "name": "Customers"}},
        )

        field_created_on = self.org.contactfields.get(key="created_on")

        assert_field(
            fields.ContactFieldField(source="test"),
            submissions={"registered": field_obj, "created_on": field_created_on, "xyz": serializers.ValidationError},
            representations={field_obj: {"key": "registered", "label": "Registered On"}},
        )

        assert_field(
            fields.FlowField(source="test"),
            submissions={flow.uuid: flow},
            representations={flow: {"uuid": str(flow.uuid), "name": flow.name}},
        )

        assert_field(
            fields.TopicField(source="test"),
            submissions={str(self.org.default_ticket_topic.uuid): self.org.default_ticket_topic},
            representations={
                self.org.default_ticket_topic: {"uuid": str(self.org.default_ticket_topic.uuid), "name": "General"}
            },
        )

        assert_field(
            fields.URNField(source="test"),
            submissions={
                "tel:+1-800-123-4567": "tel:+18001234567",
                "tel:0788 123 123": "tel:+250788123123",  # using org country
                "tel:(078) 812-3123": "tel:+250788123123",
                "12345": serializers.ValidationError,  # un-parseable
                "tel:800-123-4567": serializers.ValidationError,  # no country code
                18_001_234_567: serializers.ValidationError,  # non-string
            },
            representations={"tel:+18001234567": "tel:+18001234567"},
        )

        self.editor.first_name = "Ed"
        self.editor.last_name = "Flows"
        self.editor.is_active = False
        self.editor.save(update_fields=("first_name", "last_name", "is_active"))

        assert_field(
            fields.UserField(source="test"),
            submissions={
                "USER@NYARUKA.COM": self.user,
                "administrator@nyaruka.com": self.admin,
                self.editor.email: serializers.ValidationError,  # deleted
                self.admin2.email: serializers.ValidationError,  # not in org
            },
            representations={
                self.user: {"email": "User@nyaruka.com", "name": ""},
                self.editor: {"email": "Editor@nyaruka.com", "name": "Ed Flows"},
            },
        )
        assert_field(
            fields.UserField(source="test", assignable_only=True),
            submissions={
                self.user.email: serializers.ValidationError,  # not assignable
                self.admin.email: self.admin,
                self.agent.email: self.agent,
            },
            representations={self.agent: {"email": "Agent@nyaruka.com", "name": ""}},
        )

        field = fields.TranslatableField(source="test", max_length=10)
        field._context = {"org": self.org}

        self.assertEqual(field.to_internal_value("Hello"), ({"base": "Hello"}, "base"))
        self.assertEqual(field.to_internal_value({"base": "Hello"}), ({"base": "Hello"}, "base"))

        self.org.set_flow_languages(self.admin, ["kin"])
        self.org.save()

        self.assertEqual(field.to_internal_value("Hello"), ({"kin": "Hello"}, "kin"))
        self.assertEqual(
            field.to_internal_value({"eng": "Hello", "kin": "Muraho"}), ({"eng": "Hello", "kin": "Muraho"}, "kin")
        )

        self.assertRaises(serializers.ValidationError, field.to_internal_value, 123)  # not a string or dict
        self.assertRaises(serializers.ValidationError, field.to_internal_value, {"kin": 123})
        self.assertRaises(serializers.ValidationError, field.to_internal_value, {})
        self.assertRaises(serializers.ValidationError, field.to_internal_value, {123: "Hello", "kin": "Muraho"})
        self.assertRaises(serializers.ValidationError, field.to_internal_value, "HelloHello1")  # too long
        self.assertRaises(
            serializers.ValidationError, field.to_internal_value, {"kin": "HelloHello1"}
        )  # also too long
        self.assertRaises(
            serializers.ValidationError, field.to_internal_value, {"eng": "HelloHello1"}
        )  # base lang not provided

    @override_settings(FLOW_START_PARAMS_SIZE=4)
    def test_normalize_extra(self):
        self.assertEqual(OrderedDict(), normalize_extra({}))
        self.assertEqual(
            OrderedDict([("0", "a"), ("1", True), ("2", Decimal("1.0")), ("3", "")]),
            normalize_extra(["a", True, Decimal("1.0"), None]),
        )
        self.assertEqual(OrderedDict([("_3__x", "z")]), normalize_extra({"%3 !x": "z"}))
        self.assertEqual(
            OrderedDict([("0", "a"), ("1", "b"), ("2", "c"), ("3", "d")]), normalize_extra(["a", "b", "c", "d", "e"])
        )
        self.assertEqual(
            OrderedDict([("a", 1), ("b", 2), ("c", 3), ("d", 4)]),
            normalize_extra({"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}),
        )
        self.assertEqual(OrderedDict([("a", "x" * 640)]), normalize_extra({"a": "x" * 641}))

    def test_authentication(self):
        def request(endpoint, **headers):
            return self.client.get(
                f"{endpoint}.json", content_type="application/json", HTTP_X_FORWARDED_HTTPS="https", **headers
            )

        def request_by_token(endpoint, token):
            return request(endpoint, HTTP_AUTHORIZATION=f"Token {token}")

        def request_by_basic_auth(endpoint, username, token):
            credentials_base64 = base64.encodebytes(f"{username}:{token}".encode()).decode()
            return request(endpoint, HTTP_AUTHORIZATION=f"Basic {credentials_base64}")

        def request_by_session(endpoint, user):
            self.login(user)
            resp = request(endpoint)
            self.client.logout()
            return resp

        contacts_url = reverse("api.v2.contacts")
        campaigns_url = reverse("api.v2.campaigns")
        fields_url = reverse("api.v2.fields")

        token1 = APIToken.get_or_create(self.org, self.admin, Group.objects.get(name="Administrators"))
        token2 = APIToken.get_or_create(self.org, self.admin, Group.objects.get(name="Surveyors"))

        # can request fields endpoint using all 3 methods
        response = request_by_token(fields_url, token1.key)
        self.assertEqual(200, response.status_code)
        response = request_by_basic_auth(fields_url, self.admin.username, token1.key)
        self.assertEqual(200, response.status_code)
        response = request_by_session(fields_url, self.admin)
        self.assertEqual(200, response.status_code)

        # can't fetch endpoint with invalid token
        response = request_by_token(contacts_url, "1234567890")
        self.assertResponseError(response, None, "Invalid token", status_code=403)

        # can't fetch endpoint with invalid token
        response = request_by_basic_auth(contacts_url, self.admin.username, "1234567890")
        self.assertResponseError(response, None, "Invalid token or email", status_code=403)

        # can't fetch endpoint with invalid username
        response = request_by_basic_auth(contacts_url, "some@name.com", token1.key)
        self.assertResponseError(response, None, "Invalid token or email", status_code=403)

        # can fetch campaigns endpoint with valid admin token
        response = request_by_token(campaigns_url, token1.key)
        self.assertEqual(response.status_code, 200)

        # but not with surveyor token
        response = request_by_token(campaigns_url, token2.key)
        self.assertResponseError(response, None, "You do not have permission to perform this action.", status_code=403)

        response = request_by_basic_auth(campaigns_url, self.admin.username, token2.key)
        self.assertResponseError(response, None, "You do not have permission to perform this action.", status_code=403)

        # but it can be used to access the contacts endpoint
        response = request_by_token(contacts_url, token2.key)
        self.assertEqual(response.status_code, 200)

        response = request_by_basic_auth(contacts_url, self.admin.username, token2.key)
        self.assertEqual(response.status_code, 200)

        # simulate the admin user exceeding the rate limit for the v2 scope
        cache.set(f"throttle_v2_{self.org.id}-{self.admin.id}", [time.time() for r in range(10000)])

        # next request they make using a token will be rejected
        response = request_by_token(fields_url, token1.key)
        self.assertEqual(response.status_code, 429)

        # same with basic auth
        response = request_by_basic_auth(fields_url, self.admin.username, token1.key)
        self.assertEqual(response.status_code, 429)

        # but they can still make a request if they have a session
        response = request_by_session(fields_url, self.admin)
        self.assertEqual(response.status_code, 200)

        # if user loses access to the token's role, don't allow the request
        self.org.administrators.remove(self.admin)
        self.org.surveyors.add(self.admin)

        self.assertEqual(request_by_token(campaigns_url, token1.key).status_code, 403)
        self.assertEqual(request_by_basic_auth(campaigns_url, self.admin.username, token1.key).status_code, 403)
        self.assertEqual(request_by_token(contacts_url, token2.key).status_code, 200)  # other token unaffected
        self.assertEqual(request_by_basic_auth(contacts_url, self.admin.username, token2.key).status_code, 200)

        # and if user is inactive, disallow the request
        self.admin.is_active = False
        self.admin.save()

        response = request_by_token(contacts_url, token2.key)
        self.assertResponseError(response, None, "Invalid token", status_code=403)

        response = request_by_basic_auth(contacts_url, self.admin.username, token2.key)
        self.assertResponseError(response, None, "Invalid token or email", status_code=403)

    @override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_HTTPS", "https"))
    def test_root(self):
        url = reverse("api.v2")

        # browse as HTML anonymously (should still show docs)
        response = self.fetchHTML(url)
        self.assertContains(response, "We provide a RESTful JSON API", status_code=403)

        # same thing if user navigates to just /api
        response = self.client.get(reverse("api"), follow=True)
        self.assertContains(response, "We provide a RESTful JSON API", status_code=403)

        # try to browse as JSON anonymously
        response = self.fetchJSON(url)
        self.assertResponseError(response, None, "Authentication credentials were not provided.", status_code=403)

        # login as administrator
        self.login(self.admin)
        token = self.admin.api_token  # generates token for the user
        self.assertIsInstance(token, str)
        self.assertEqual(len(token), 40)

        with self.assertNumQueries(0):  # subsequent lookup of token comes from cache
            self.assertEqual(self.admin.api_token, token)

        # browse as HTML
        response = self.fetchHTML(url)
        self.assertContains(response, token, status_code=200)  # displays their API token

        # browse as JSON
        response = self.fetchJSON(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["runs"], "https://testserver:80/api/v2/runs")  # endpoints are listed

    def test_explorer(self):
        url = reverse("api.v2.explorer")

        response = self.fetchHTML(url)
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "Log in to use the Explorer")

        # login as non-org user
        self.login(self.non_org_user)
        response = self.fetchHTML(url)
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "Log in to use the Explorer")

        # login as administrator
        self.login(self.admin)
        response = self.fetchHTML(url)
        self.assertEqual(200, response.status_code)
        self.assertNotContains(response, "Log in to use the Explorer")

    def test_pagination(self):
        url = reverse("api.v2.runs") + ".json"
        self.login(self.admin)

        # create 1255 test runs (5 full pages of 250 items + 1 partial with 5 items)
        flow = self.create_flow()
        FlowRun.objects.bulk_create([FlowRun(org=self.org, flow=flow, contact=self.joe) for r in range(1255)])
        actual_ids = list(FlowRun.objects.order_by("-pk").values_list("pk", flat=True))

        # give them all the same modified_on
        FlowRun.objects.all().update(modified_on=datetime(2015, 9, 15, 0, 0, 0, 0, pytz.UTC))

        returned_ids = []

        # fetch all full pages
        resp_json = None
        for p in range(5):
            response = self.fetchJSON(url if p == 0 else resp_json["next"], raw_url=True)
            resp_json = response.json()

            self.assertEqual(len(resp_json["results"]), 250)
            self.assertIsNotNone(resp_json["next"])

            returned_ids += [r["id"] for r in response.json()["results"]]

        # fetch final partial page
        response = self.fetchJSON(resp_json["next"], raw_url=True)

        resp_json = response.json()
        self.assertEqual(len(resp_json["results"]), 5)
        self.assertIsNone(resp_json["next"])

        returned_ids += [r["id"] for r in response.json()["results"]]

        self.assertEqual(returned_ids, actual_ids)  # ensure all results were returned and in correct order

    def test_authenticate(self):
        url = reverse("api.v2.authenticate")

        # fetch as HTML
        response = self.fetchHTML(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["form"].fields.keys()), ["username", "password", "role", "loc"])

        admins = Group.objects.get(name="Administrators")
        surveyors = Group.objects.get(name="Surveyors")

        # try to authenticate with incorrect password
        response = self.client.post(url, {"username": "Administrator", "password": "XXXX", "role": "A"})
        self.assertEqual(response.status_code, 403)

        # try to authenticate with invalid role
        response = self.client.post(url, {"username": "Administrator", "password": "Administrator", "role": "X"})
        self.assertFormError(response, "form", "role", "Select a valid choice. X is not one of the available choices.")

        # authenticate an admin as an admin
        response = self.client.post(url, {"username": "Administrator", "password": "Administrator", "role": "A"})

        # should have created a new token object
        token_obj1 = APIToken.objects.get(user=self.admin, role=admins)

        tokens = response.json()["tokens"]
        self.assertEqual(len(tokens), 1)
        self.assertEqual(
            tokens[0],
            {"org": {"id": self.org.pk, "name": "Temba", "uuid": str(self.org.uuid)}, "token": token_obj1.key},
        )

        # authenticate an admin as a surveyor
        response = self.client.post(url, {"username": "Administrator", "password": "Administrator", "role": "S"})

        # should have created a new token object
        token_obj2 = APIToken.objects.get(user=self.admin, role=surveyors)

        tokens = response.json()["tokens"]
        self.assertEqual(len(tokens), 1)
        self.assertEqual(
            tokens[0],
            {"org": {"id": self.org.pk, "name": "Temba", "uuid": str(self.org.uuid)}, "token": token_obj2.key},
        )

        # the keys should be different
        self.assertNotEqual(token_obj1.key, token_obj2.key)

        client = APIClient()

        # campaigns can be fetched by admin token
        client.credentials(HTTP_AUTHORIZATION="Token " + token_obj1.key)
        self.assertEqual(client.get(reverse("api.v2.campaigns") + ".json").status_code, 200)

        # but not by an admin's surveyor token
        client.credentials(HTTP_AUTHORIZATION="Token " + token_obj2.key)
        self.assertEqual(client.get(reverse("api.v2.campaigns") + ".json").status_code, 403)

        # but their surveyor token can get flows or contacts
        self.assertEqual(client.get(reverse("api.v2.flows") + ".json").status_code, 200)
        self.assertEqual(client.get(reverse("api.v2.contacts") + ".json").status_code, 200)

        # our surveyor can't login with an admin role
        response = self.client.post(url, {"username": "Surveyor", "password": "Surveyor", "role": "A"})
        tokens = response.json()["tokens"]
        self.assertEqual(len(tokens), 0)

        # but they can with a surveyor role
        response = self.client.post(url, {"username": "Surveyor", "password": "Surveyor", "role": "S"})
        tokens = response.json()["tokens"]
        self.assertEqual(len(tokens), 1)

        token_obj3 = APIToken.objects.get(user=self.surveyor, role=surveyors)

        # and can fetch flows, contacts, and fields, but not campaigns
        client.credentials(HTTP_AUTHORIZATION="Token " + token_obj3.key)
        self.assertEqual(client.get(reverse("api.v2.flows") + ".json").status_code, 200)
        self.assertEqual(client.get(reverse("api.v2.contacts") + ".json").status_code, 200)
        self.assertEqual(client.get(reverse("api.v2.fields") + ".json").status_code, 200)
        self.assertEqual(client.get(reverse("api.v2.campaigns") + ".json").status_code, 403)

    @patch("temba.flows.models.FlowStart.create")
    def test_transactions(self, mock_flowstart_create):
        """
        Serializer writes are wrapped in a transaction. This test simulates FlowStart.create blowing up and checks that
        contacts aren't created.
        """
        mock_flowstart_create.side_effect = ValueError("DOH!")

        flow = self.create_flow()
        self.login(self.admin)
        try:
            self.postJSON(reverse("api.v2.flow_starts"), None, dict(flow=flow.uuid, urns=["tel:+12067791212"]))
            self.fail()  # ensure exception is thrown
        except ValueError:
            pass

        self.assertFalse(Contact.objects.filter(urns__path="+12067791212"))

    def test_boundaries(self):
        self.setUpLocations()

        url = reverse("api.v2.boundaries")

        self.assertEndpointAccess(url)

        BoundaryAlias.create(self.org, self.admin, self.state1, "Kigali")
        BoundaryAlias.create(self.org, self.admin, self.state2, "East Prov")
        BoundaryAlias.create(self.org2, self.admin2, self.state1, "Other Org")  # shouldn't be returned

        self.state1.simplified_geometry = GEOSGeometry("MULTIPOLYGON(((1 1, 1 -1, -1 -1, -1 1, 1 1)))")
        self.state1.save()

        # test without geometry
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 3):
            response = self.fetchJSON(url, readonly_models={AdminBoundary})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(len(resp_json["results"]), 10)
        self.assertEqual(
            resp_json["results"][0],
            {
                "osm_id": "1708283",
                "name": "Kigali City",
                "parent": {"osm_id": "171496", "name": "Rwanda"},
                "level": 1,
                "aliases": ["Kigali", "Kigari"],
                "geometry": None,
            },
        )

        # test without geometry
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 3):
            response = self.fetchJSON(url, "geometry=true")

        self.assertEqual(
            response.json()["results"][0],
            {
                "osm_id": "1708283",
                "name": "Kigali City",
                "parent": {"osm_id": "171496", "name": "Rwanda"},
                "level": 1,
                "aliases": ["Kigali", "Kigari"],
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [[[[1.0, 1.0], [1.0, -1.0], [-1.0, -1.0], [-1.0, 1.0], [1.0, 1.0]]]],
                },
            },
        )

        # if org doesn't have a country, just return no results
        self.org.country = None
        self.org.save()

        response = self.fetchJSON(url)
        self.assertEqual(response.json()["results"], [])

    @patch("temba.mailroom.queue_broadcast")
    def test_broadcasts(self, mock_queue_broadcast):
        url = reverse("api.v2.broadcasts")

        self.assertEndpointAccess(url)

        reporters = self.create_group("Reporters", [self.joe, self.frank])
        ticketer = Ticketer.create(self.org, self.admin, "mailgun", "Support Tickets", {})
        ticket = self.create_ticket(ticketer, self.joe, "Help!")

        bcast1 = Broadcast.create(self.org, self.admin, "Hello 1", urns=["twitter:franky"])
        bcast2 = Broadcast.create(self.org, self.admin, "Hello 2", contacts=[self.joe])
        bcast3 = Broadcast.create(self.org, self.admin, "Hello 3", contacts=[self.frank], status="S")
        bcast4 = Broadcast.create(
            self.org,
            self.admin,
            "Hello 4",
            urns=["twitter:franky"],
            contacts=[self.joe],
            groups=[reporters],
            status="F",
            ticket=ticket,
        )
        Broadcast.create(self.org2, self.admin2, "Different org...", contacts=[self.hans])

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 4):
            response = self.fetchJSON(url, readonly_models={Broadcast})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertResultsById(response, [bcast4, bcast3, bcast2, bcast1])
        self.assertEqual(
            {
                "id": bcast2.id,
                "urns": [],
                "contacts": [{"uuid": self.joe.uuid, "name": self.joe.name}],
                "groups": [],
                "text": {"base": "Hello 2"},
                "status": "queued",
                "created_on": format_datetime(bcast2.created_on),
            },
            resp_json["results"][2],
        )
        self.assertEqual(
            {
                "id": bcast4.id,
                "urns": ["twitter:franky"],
                "contacts": [{"uuid": self.joe.uuid, "name": self.joe.name}],
                "groups": [{"uuid": reporters.uuid, "name": reporters.name}],
                "text": {"base": "Hello 4"},
                "status": "failed",
                "created_on": format_datetime(bcast4.created_on),
            },
            resp_json["results"][0],
        )

        # filter by id
        response = self.fetchJSON(url, "id=%d" % bcast3.pk)
        self.assertResultsById(response, [bcast3])

        # filter by after
        response = self.fetchJSON(url, "after=%s" % format_datetime(bcast3.created_on))
        self.assertResultsById(response, [bcast4, bcast3])

        # filter by before
        response = self.fetchJSON(url, "before=%s" % format_datetime(bcast2.created_on))
        self.assertResultsById(response, [bcast2, bcast1])

        with AnonymousOrg(self.org):
            # URNs shouldn't be included
            response = self.fetchJSON(url, "id=%d" % bcast1.id)
            self.assertIsNone(response.json()["results"][0]["urns"])

        # try to create new broadcast with no data at all
        response = self.postJSON(url, None, {})
        self.assertResponseError(response, "text", "This field is required.")

        # try to create new broadcast with no recipients
        response = self.postJSON(url, None, {"text": "Hello"})
        self.assertResponseError(response, "non_field_errors", "Must provide either urns, contacts or groups")

        # create new broadcast with all fields
        response = self.postJSON(
            url,
            None,
            {
                "text": "Hi @(format_urn(urns.tel))",
                "urns": ["twitter:franky"],
                "contacts": [self.joe.uuid, self.frank.uuid],
                "groups": [reporters.uuid],
                "ticket": str(ticket.uuid),
            },
        )

        broadcast = Broadcast.objects.get(id=response.json()["id"])
        self.assertEqual({"base": "Hi @(format_urn(urns.tel))"}, broadcast.text)
        self.assertEqual(["twitter:franky"], broadcast.raw_urns)
        self.assertEqual({self.joe, self.frank}, set(broadcast.contacts.all()))
        self.assertEqual({reporters}, set(broadcast.groups.all()))
        self.assertEqual(ticket, broadcast.ticket)

        mock_queue_broadcast.assert_called_once_with(broadcast)

        # create new broadcast with translations
        response = self.postJSON(
            url, None, {"text": {"base": "Hello", "fra": "Bonjour"}, "contacts": [self.joe.uuid, self.frank.uuid]}
        )

        broadcast = Broadcast.objects.get(id=response.json()["id"])
        self.assertEqual({"base": "Hello", "fra": "Bonjour"}, broadcast.text)
        self.assertEqual({self.joe, self.frank}, set(broadcast.contacts.all()))

        # create new broadcast with an expression
        response = self.postJSON(url, None, {"text": "You are @fields.age", "contacts": [self.joe.uuid]})
        broadcast = Broadcast.objects.get(id=response.json()["id"])
        self.assertEqual({"base": "You are @fields.age"}, broadcast.text)

        # try sending as a flagged org
        self.org.flag()
        response = self.postJSON(url, None, {"text": "Hello", "urns": ["twitter:franky"]})
        self.assertResponseError(response, "non_field_errors", Org.BLOCKER_FLAGGED)

    @patch("temba.mailroom.queue_broadcast")
    def test_whatsapp_broadcasts(self, mock_queue_broadcast):
        url = reverse("api.v2.whatsapp_broadcasts")

        self.assertEndpointAccess(url)

        reporters = self.create_group("Reporters", [self.joe, self.frank])
        ticketer = Ticketer.create(self.org, self.admin, "mailgun", "Support Tickets", {})
        ticket = self.create_ticket(ticketer, self.joe, "Help!")
        channel = self.create_channel("WAC", "WhatsApp: 1234", "1234", org=self.org)

        bcast1 = Broadcast.create(
            self.org,
            self.admin,
            "Hello 1",
            urns=["whatsapp:5561912345678"],
            broadcast_type=Broadcast.BROADCAST_TYPE_WHATSAPP,
        )
        bcast2 = Broadcast.create(
            self.org, self.admin, "Hello 2", contacts=[self.joe], broadcast_type=Broadcast.BROADCAST_TYPE_WHATSAPP
        )
        bcast3 = Broadcast.create(
            self.org,
            self.admin,
            "Hello 3",
            contacts=[self.frank],
            status="S",
            broadcast_type=Broadcast.BROADCAST_TYPE_WHATSAPP,
        )
        bcast4 = Broadcast.create(
            self.org,
            self.admin,
            "Hello 4",
            urns=["twitter:franky"],
            contacts=[self.joe],
            groups=[reporters],
            status="F",
            ticket=ticket,
            broadcast_type=Broadcast.BROADCAST_TYPE_WHATSAPP,
        )
        Broadcast.create(
            self.org2,
            self.admin2,
            "Different org...",
            contacts=[self.hans],
            broadcast_type=Broadcast.BROADCAST_TYPE_WHATSAPP,
        )

        template = Template.objects.create(name="Template1", uuid="0ca51332-8c61-49a0-a4a8-c52c0bf57729", org=self.org)

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 4):
            response = self.fetchJSON(url, readonly_models={Broadcast})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertResultsById(response, [bcast4, bcast3, bcast2, bcast1])
        self.assertEqual(
            {
                "id": bcast2.id,
                "urns": [],
                "contacts": [{"uuid": self.joe.uuid, "name": self.joe.name}],
                "groups": [],
                "text": {"base": "Hello 2"},
                "status": "queued",
                "created_on": format_datetime(bcast2.created_on),
                "channel": None,
                "metadata": {},
            },
            resp_json["results"][2],
        )
        self.assertEqual(
            {
                "id": bcast4.id,
                "urns": ["twitter:franky"],
                "contacts": [{"uuid": self.joe.uuid, "name": self.joe.name}],
                "groups": [{"uuid": reporters.uuid, "name": reporters.name}],
                "text": {"base": "Hello 4"},
                "status": "failed",
                "created_on": format_datetime(bcast4.created_on),
                "channel": None,
                "metadata": {},
            },
            resp_json["results"][0],
        )

        # filter by id
        response = self.fetchJSON(url, "id=%d" % bcast3.pk)
        self.assertResultsById(response, [bcast3])

        # filter by after
        response = self.fetchJSON(url, "after=%s" % format_datetime(bcast3.created_on))
        self.assertResultsById(response, [bcast4, bcast3])

        # filter by before
        response = self.fetchJSON(url, "before=%s" % format_datetime(bcast2.created_on))
        self.assertResultsById(response, [bcast2, bcast1])

        with AnonymousOrg(self.org):
            # URNs shouldn't be included
            response = self.fetchJSON(url, "id=%d" % bcast1.id)
            self.assertIsNone(response.json()["results"][0]["urns"])

        # try to create new broadcast with no recipients
        response = self.postJSON(url, None, {"text": "Hello", "msg": {"text": "Test"}})
        self.assertResponseError(response, "non_field_errors", "Must provide either urns, contacts or groups")

        # try to create new broadcast with no recipients
        response = self.postJSON(url, None, {"text": "Hello"})
        self.assertEqual(response.json(), {"msg": ["This field is required."]})

        # try to send msg with an existing template
        expected_metadata = {
            "template": {"name": template.name, "uuid": template.uuid, "variables": [], "locale": None},
            "text": "Send a message",
        }

        response = self.postJSON(
            url,
            None,
            {
                "text": "Hi @(format_urn(urns.tel))",
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid, self.frank.uuid],
                "groups": [reporters.uuid],
                "ticket": str(ticket.uuid),
                "msg": {"template": {"uuid": template.uuid}, "text": "Send a message"},
            },
        )

        broadcast = Broadcast.objects.get(id=response.json()["id"])
        self.assertEqual(expected_metadata, broadcast.metadata)

        # try to send msg with an wrong template uuid
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid, self.frank.uuid],
                "groups": [reporters.uuid],
                "ticket": str(ticket.uuid),
                "msg": {"template": {"uuid": "1bb5d3de-6ddf-437b-9009-a04201bef143"}, "text": "Send a message"},
            },
        )

        self.assertResponseError(
            response, "non_field_errors", "Template with UUID 1bb5d3de-6ddf-437b-9009-a04201bef143 not found."
        )

        # try to send msg with no template uuid
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid, self.frank.uuid],
                "groups": [reporters.uuid],
                "ticket": str(ticket.uuid),
                "msg": {"template": {}, "text": "Send a message"},
            },
        )

        self.assertResponseError(response, "non_field_errors", "Template UUID or Name are required.")

        # try to send msg with no template, text and attachments
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid, self.frank.uuid],
                "groups": [reporters.uuid],
                "ticket": str(ticket.uuid),
                "msg": {},
            },
        )

        self.assertEqual(response.json(), {"msg": ["Must provide either text, attachments, template or action_type"]})

        # send a msg with a defined channel
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid, self.frank.uuid],
                "groups": [reporters.uuid],
                "ticket": str(ticket.uuid),
                "msg": {"text": "Send a message"},
                "channel": channel.uuid,
            },
        )

        expected_metadata = {"text": "Send a message"}
        broadcast = Broadcast.objects.get(id=response.json()["id"])

        self.assertEqual(expected_metadata, broadcast.metadata)
        self.assertEqual(channel, broadcast.channel)

        # send a msg with a non whatsapp cloud defined channel
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid, self.frank.uuid],
                "groups": [reporters.uuid],
                "ticket": str(ticket.uuid),
                "msg": {"text": "Send a message"},
                "channel": self.channel.uuid,
            },
        )

        self.assertResponseError(response, "non_field_errors", "Channel must be a WhatsApp Cloud channel")

        # send a msg with a non existing channel
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid, self.frank.uuid],
                "groups": [reporters.uuid],
                "ticket": str(ticket.uuid),
                "msg": {"text": "Send a message"},
                "channel": "1bb5d3de-6ddf-437b-9009-a04201bef149",
            },
        )

        self.assertResponseError(response, "non_field_errors", "Channel not found")

        # create a translation for a different channel othen than whatsapp, but linked to the same template
        TemplateTranslation.get_or_create(
            self.channel,
            template.name,
            "eng",
            "US",
            "Hello {{1}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "1234",
            "",
            "AUTHENTICATION",
        )

        # send a template msg with a defined channel, but the template is not for the channel
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid, self.frank.uuid],
                "groups": [reporters.uuid],
                "ticket": str(ticket.uuid),
                "msg": {"template": {"uuid": template.uuid}, "variables": ["1"]},
                "channel": channel.uuid,
            },
        )

        self.assertResponseError(
            response,
            "non_field_errors",
            f"Template {template.uuid} not found in channel {channel.uuid}",
        )

        # now create a valid template translation for the WAC channel

        TemplateTranslation.get_or_create(
            channel,
            template.name,
            "eng",
            "US",
            "Hello {{1}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "1234",
            "",
            "AUTHENTICATION",
        )

        # send a template msg with a defined channel, and the template is for the channel
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid, self.frank.uuid],
                "groups": [reporters.uuid],
                "ticket": str(ticket.uuid),
                "msg": {"template": {"uuid": template.uuid, "variables": ["1"]}},
                "channel": channel.uuid,
            },
        )

        expected_metadata = {
            "template": {"name": template.name, "uuid": template.uuid, "variables": ["1"], "locale": None}
        }
        broadcast = Broadcast.objects.get(id=response.json()["id"])

        self.assertEqual(expected_metadata, broadcast.metadata)
        self.assertEqual(channel, broadcast.channel)

        # send a template msg from name without specifing the channel

        response = self.postJSON(
            url,
            None,
            {
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid, self.frank.uuid],
                "groups": [reporters.uuid],
                "ticket": str(ticket.uuid),
                "msg": {"template": {"name": template.name, "variables": ["1"]}},
            },
        )

        self.assertResponseError(
            response,
            "non_field_errors",
            f"Channel is required to use template name",
        )

        # send a template msg from name specifing the channel

        response = self.postJSON(
            url,
            None,
            {
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid, self.frank.uuid],
                "groups": [reporters.uuid],
                "ticket": str(ticket.uuid),
                "msg": {"template": {"name": template.name, "variables": ["1"]}},
                "channel": channel.uuid,
            },
        )

        expected_metadata = {
            "template": {"name": template.name, "uuid": template.uuid, "variables": ["1"], "locale": None}
        }
        broadcast = Broadcast.objects.get(id=response.json()["id"])

        self.assertEqual(expected_metadata, broadcast.metadata)
        self.assertEqual(channel, broadcast.channel)

        # Trying to get a not existing UUID
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid],
                "msg": {"template": {"uuid": "1bb5d3de-6ddf-437b-9009-a04201bef143"}},
                "channel": channel.uuid,
            },
        )
        self.assertResponseError(
            response, "non_field_errors", "Template with UUID 1bb5d3de-6ddf-437b-9009-a04201bef143 not found."
        )

        # Trying to get a not existing template name
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["whatsapp:5561912345678"],
                "contacts": [self.joe.uuid],
                "msg": {"template": {"name": "Away"}},
                "channel": channel.uuid,
            },
        )
        self.assertResponseError(response, "non_field_errors", "Template with name Away not found.")

    def test_archives(self):
        url = reverse("api.v2.archives")

        self.assertEndpointAccess(url)

        # create some archives
        Archive.objects.create(
            org=self.org,
            start_date=datetime(2017, 4, 5),
            build_time=12,
            record_count=34,
            size=345,
            hash="feca9988b7772c003204a28bd741d0d0",
            archive_type=Archive.TYPE_MSG,
            period=Archive.PERIOD_DAILY,
        )
        may_archive = Archive.objects.create(
            org=self.org,
            start_date=datetime(2017, 5, 5),
            build_time=12,
            record_count=34,
            size=345,
            hash="feca9988b7772c003204a28bd741d0d0",
            archive_type=Archive.TYPE_MSG,
            period=Archive.PERIOD_MONTHLY,
        )
        Archive.objects.create(
            org=self.org,
            start_date=datetime(2017, 6, 5),
            build_time=12,
            record_count=34,
            size=345,
            hash="feca9988b7772c003204a28bd741d0d0",
            archive_type=Archive.TYPE_FLOWRUN,
            period=Archive.PERIOD_DAILY,
        )
        Archive.objects.create(
            org=self.org,
            start_date=datetime(2017, 7, 5),
            build_time=12,
            record_count=34,
            size=345,
            hash="feca9988b7772c003204a28bd741d0d0",
            archive_type=Archive.TYPE_FLOWRUN,
            period=Archive.PERIOD_MONTHLY,
        )
        # this archive has been rolled up and it should not be included in the API responses
        Archive.objects.create(
            org=self.org,
            start_date=datetime(2017, 5, 1),
            build_time=12,
            record_count=34,
            size=345,
            hash="feca9988b7772c003204a28bd741d0d0",
            archive_type=Archive.TYPE_FLOWRUN,
            period=Archive.PERIOD_DAILY,
            rollup_id=may_archive.id,
        )

        # create archive for other org
        Archive.objects.create(
            org=self.org2,
            start_date=datetime(2017, 5, 1),
            build_time=12,
            record_count=34,
            size=345,
            hash="feca9988b7772c003204a28bd741d123",
            archive_type=Archive.TYPE_FLOWRUN,
            period=Archive.PERIOD_DAILY,
        )

        response = self.fetchJSON(url, readonly_models={Archive})
        resp_json = response.json()

        self.assertEqual(response.status_code, 200)
        # there should be 4 archives in the response, because one has been rolled up
        self.assertEqual(len(resp_json["results"]), 4)
        self.assertEqual(
            resp_json["results"][0],
            {
                "archive_type": "run",
                "download_url": "",
                "hash": "feca9988b7772c003204a28bd741d0d0",
                "period": "monthly",
                "record_count": 34,
                "size": 345,
                "start_date": "2017-07-05",
            },
        )

        response = self.fetchJSON(url, query="after=2017-05-01")
        resp_json = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(resp_json["results"]), 3)

        response = self.fetchJSON(url, query="after=2017-05-01&archive_type=run")
        resp_json = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(resp_json["results"]), 2)

        # unknown archive type
        response = self.fetchJSON(url, query="after=2017-05-01&archive_type=!!!unknown!!!")
        resp_json = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(resp_json["results"]), 0)

        # only for dailies
        response = self.fetchJSON(url, query="after=2017-05-01&archive_type=run&period=daily")
        resp_json = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(resp_json["results"]), 1)

        # only for monthlies
        response = self.fetchJSON(url, query="period=monthly")
        resp_json = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(resp_json["results"]), 2)

    def test_campaigns(self):
        url = reverse("api.v2.campaigns")

        self.assertEndpointAccess(url)

        reporters = self.create_group("Reporters", [self.joe, self.frank])
        other_group = self.create_group("Others", [])
        campaign1 = Campaign.create(self.org, self.admin, "Reminders #1", reporters)
        campaign2 = Campaign.create(self.org, self.admin, "Reminders #2", reporters)

        # create campaign for other org
        spammers = ContactGroup.get_or_create(self.org2, self.admin2, "Spammers")
        spam = Campaign.create(self.org2, self.admin2, "Spam", spammers)

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 2):
            response = self.fetchJSON(url, readonly_models={Campaign})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertResultsByUUID(response, [campaign2, campaign1])
        self.assertEqual(
            resp_json["results"][0],
            {
                "uuid": campaign2.uuid,
                "name": "Reminders #2",
                "archived": False,
                "group": {"uuid": reporters.uuid, "name": "Reporters"},
                "created_on": format_datetime(campaign2.created_on),
            },
        )

        # filter by UUID
        response = self.fetchJSON(url, "uuid=%s" % campaign1.uuid)
        self.assertResultsByUUID(response, [campaign1])

        # try to create empty campaign
        response = self.postJSON(url, None, {})
        self.assertResponseError(response, "name", "This field is required.")
        self.assertResponseError(response, "group", "This field is required.")

        # create new campaign
        response = self.postJSON(url, None, {"name": "Reminders #3", "group": reporters.uuid})
        self.assertEqual(response.status_code, 201)

        campaign3 = Campaign.objects.get(name="Reminders #3")
        self.assertEqual(
            response.json(),
            {
                "uuid": campaign3.uuid,
                "name": "Reminders #3",
                "archived": False,
                "group": {"uuid": reporters.uuid, "name": "Reporters"},
                "created_on": format_datetime(campaign3.created_on),
            },
        )

        # try to create another campaign with same name
        response = self.postJSON(url, None, {"name": "Reminders #3", "group": reporters.uuid})
        self.assertResponseError(response, "name", "This field must be unique.")

        # it's fine if a campaign in another org has that name
        response = self.postJSON(url, None, {"name": "Spam", "group": reporters.uuid})
        self.assertEqual(response.status_code, 201)

        # try to create a campaign with name that's too long
        response = self.postJSON(url, None, {"name": "x" * 256, "group": reporters.uuid})
        self.assertResponseError(response, "name", "Ensure this field has no more than 255 characters.")

        # update campaign by UUID
        response = self.postJSON(url, "uuid=%s" % campaign3.uuid, {"name": "Reminders III", "group": other_group.uuid})
        self.assertEqual(response.status_code, 200)

        campaign3.refresh_from_db()
        self.assertEqual(campaign3.name, "Reminders III")
        self.assertEqual(campaign3.group, other_group)

        # can't update campaign in other org
        response = self.postJSON(url, "uuid=%s" % spam.uuid, {"name": "Won't work", "group": spammers.uuid})
        self.assert404(response)

    def test_campaigns_does_not_update_inactive_archived(self):
        url = reverse("api.v2.campaigns")

        self.assertEndpointAccess(url)

        reporters = self.create_group("Reporters", [self.joe, self.frank])
        campaign = Campaign.create(self.org, self.admin, "Reminders #1", reporters)

        campaign.is_active = False
        campaign.save(update_fields=("is_active",))

        # can't update inactive or archived campaign
        response = self.postJSON(
            url, "uuid=%s" % campaign.uuid, data={"name": "Reminders III", "group": reporters.uuid}
        )
        self.assertEqual(response.status_code, 404)

        campaign.is_active = True
        campaign.is_archived = True
        campaign.save(update_fields=("is_active", "is_archived"))

        # can't update inactive or archived campaign
        response = self.postJSON(
            url, "uuid=%s" % campaign.uuid, data={"name": "Reminders III", "group": reporters.uuid}
        )
        self.assertEqual(response.status_code, 404)

    @mock_mailroom
    def test_campaign_events(self, mr_mocks):
        url = reverse("api.v2.campaign_events")

        self.assertEndpointAccess(url)

        flow = self.create_flow()
        reporters = self.create_group("Reporters", [self.joe, self.frank])
        registration = ContactField.get_or_create(
            self.org, self.admin, "registration", "Registration", value_type=ContactField.TYPE_DATETIME
        )
        field_created_on = self.org.contactfields.get(key="created_on")

        # create our contact and set a registration date
        contact = self.create_contact(
            "Joe", phone="+12065551515", fields={"registration": self.org.format_datetime(timezone.now())}
        )
        reporters.contacts.add(contact)

        campaign1 = Campaign.create(self.org, self.admin, "Reminders", reporters)
        event1 = CampaignEvent.create_message_event(
            self.org,
            self.admin,
            campaign1,
            registration,
            1,
            CampaignEvent.UNIT_DAYS,
            "Don't forget to brush your teeth",
        )

        campaign2 = Campaign.create(self.org, self.admin, "Notifications", reporters)
        event2 = CampaignEvent.create_flow_event(
            self.org, self.admin, campaign2, registration, 6, CampaignEvent.UNIT_HOURS, flow, delivery_hour=12
        )

        campaign3 = Campaign.create(self.org, self.admin, "Alerts", reporters)
        event3 = CampaignEvent.create_flow_event(
            self.org, self.admin, campaign3, field_created_on, 6, CampaignEvent.UNIT_HOURS, flow, delivery_hour=12
        )

        # create event for another org
        joined = ContactField.get_or_create(
            self.org2, self.admin2, "joined", "Joined On", value_type=ContactField.TYPE_DATETIME
        )
        spammers = ContactGroup.get_or_create(self.org2, self.admin2, "Spammers")
        spam = Campaign.create(self.org2, self.admin2, "Cool stuff", spammers)
        CampaignEvent.create_flow_event(
            self.org2, self.admin2, spam, joined, 6, CampaignEvent.UNIT_HOURS, flow, delivery_hour=12
        )

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 4):
            response = self.fetchJSON(url, readonly_models={CampaignEvent})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertResultsByUUID(response, [event3, event2, event1])
        self.assertEqual(
            resp_json["results"],
            [
                {
                    "uuid": event3.uuid,
                    "campaign": {"uuid": campaign3.uuid, "name": "Alerts"},
                    "relative_to": {"key": "created_on", "label": "Created On"},
                    "offset": 6,
                    "unit": "hours",
                    "delivery_hour": 12,
                    "flow": {"uuid": flow.uuid, "name": "Test Flow"},
                    "message": None,
                    "created_on": format_datetime(event3.created_on),
                },
                {
                    "uuid": event2.uuid,
                    "campaign": {"uuid": campaign2.uuid, "name": "Notifications"},
                    "relative_to": {"key": "registration", "label": "Registration"},
                    "offset": 6,
                    "unit": "hours",
                    "delivery_hour": 12,
                    "flow": {"uuid": flow.uuid, "name": "Test Flow"},
                    "message": None,
                    "created_on": format_datetime(event2.created_on),
                },
                {
                    "uuid": event1.uuid,
                    "campaign": {"uuid": campaign1.uuid, "name": "Reminders"},
                    "relative_to": {"key": "registration", "label": "Registration"},
                    "offset": 1,
                    "unit": "days",
                    "delivery_hour": -1,
                    "flow": None,
                    "message": {"base": "Don't forget to brush your teeth"},
                    "created_on": format_datetime(event1.created_on),
                },
            ],
        )

        # filter by UUID
        response = self.fetchJSON(url, "uuid=%s" % event1.uuid)
        self.assertResultsByUUID(response, [event1])

        # filter by campaign name
        response = self.fetchJSON(url, "campaign=Reminders")
        self.assertResultsByUUID(response, [event1])

        # filter by campaign UUID
        response = self.fetchJSON(url, "campaign=%s" % campaign1.uuid)
        self.assertResultsByUUID(response, [event1])

        # filter by invalid campaign
        response = self.fetchJSON(url, "campaign=invalid")
        self.assertResultsByUUID(response, [])

        # try to create empty campaign event
        response = self.postJSON(url, None, {})
        self.assertResponseError(response, "campaign", "This field is required.")
        self.assertResponseError(response, "relative_to", "This field is required.")
        self.assertResponseError(response, "offset", "This field is required.")
        self.assertResponseError(response, "unit", "This field is required.")
        self.assertResponseError(response, "delivery_hour", "This field is required.")

        # try again with some invalid values
        response = self.postJSON(
            url,
            None,
            {
                "campaign": campaign1.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "epocs",
                "delivery_hour": 25,
            },
        )
        self.assertResponseError(response, "unit", '"epocs" is not a valid choice.')
        self.assertResponseError(response, "delivery_hour", "Ensure this value is less than or equal to 23.")

        # provide valid values for those fields.. but not a message or flow
        response = self.postJSON(
            url,
            None,
            {
                "campaign": campaign1.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "weeks",
                "delivery_hour": -1,
            },
        )
        self.assertResponseError(response, "non_field_errors", "Flow UUID or a message text required.")

        # create a message event
        response = self.postJSON(
            url,
            None,
            {
                "campaign": campaign1.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "weeks",
                "delivery_hour": -1,
                "message": "You are @fields.age",
            },
        )
        self.assertEqual(response.status_code, 201)

        event1 = CampaignEvent.objects.filter(campaign=campaign1).order_by("-id").first()
        self.assertEqual(event1.event_type, CampaignEvent.TYPE_MESSAGE)
        self.assertEqual(event1.relative_to, registration)
        self.assertEqual(event1.offset, 15)
        self.assertEqual(event1.unit, "W")
        self.assertEqual(event1.delivery_hour, -1)
        self.assertEqual(event1.message, {"base": "You are @fields.age"})
        self.assertIsNotNone(event1.flow)

        # a message event with an empty message
        response = self.postJSON(
            url,
            None,
            {
                "campaign": campaign1.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "weeks",
                "delivery_hour": -1,
                "message": "",
            },
        )

        # we should have failed validation for sending an empty message
        self.assertResponseError(response, "non_field_errors", "Message text is required")

        response = self.postJSON(
            url,
            None,
            {
                "campaign": campaign1.uuid,
                "relative_to": "created_on",
                "offset": 15,
                "unit": "days",
                "delivery_hour": -1,
                "message": "Nice unit of work @fields.code",
            },
        )
        self.assertEqual(response.status_code, 201)

        event1 = CampaignEvent.objects.filter(campaign=campaign1).order_by("-id").first()
        self.assertEqual(event1.event_type, CampaignEvent.TYPE_MESSAGE)
        self.assertEqual(event1.relative_to, field_created_on)
        self.assertEqual(event1.offset, 15)
        self.assertEqual(event1.unit, "D")
        self.assertEqual(event1.delivery_hour, -1)
        self.assertEqual(event1.message, {"base": "Nice unit of work @fields.code"})
        self.assertIsNotNone(event1.flow)

        # create a flow event
        response = self.postJSON(
            url,
            None,
            {
                "campaign": campaign1.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "weeks",
                "delivery_hour": -1,
                "flow": flow.uuid,
            },
        )
        self.assertEqual(response.status_code, 201)

        event2 = CampaignEvent.objects.filter(campaign=campaign1).order_by("-id").first()
        self.assertEqual(event2.event_type, CampaignEvent.TYPE_FLOW)
        self.assertEqual(event2.relative_to, registration)
        self.assertEqual(event2.offset, 15)
        self.assertEqual(event2.unit, "W")
        self.assertEqual(event2.delivery_hour, -1)
        self.assertEqual(event2.message, None)
        self.assertEqual(event2.flow, flow)

        # make sure we queued a mailroom task to schedule this event
        self.assertEqual(
            {
                "org_id": self.org.id,
                "type": "schedule_campaign_event",
                "queued_on": matchers.Datetime(),
                "task": {"campaign_event_id": event2.id, "org_id": self.org.id},
            },
            mr_mocks.queued_batch_tasks[-1],
        )

        # update the message event to be a flow event
        response = self.postJSON(
            url,
            "uuid=%s" % event1.uuid,
            {
                "campaign": campaign1.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "weeks",
                "delivery_hour": -1,
                "flow": flow.uuid,
            },
        )
        self.assertEqual(response.status_code, 200)

        event1 = CampaignEvent.objects.filter(campaign=campaign1).order_by("-id").first()

        self.assertEqual(event1.event_type, CampaignEvent.TYPE_FLOW)
        self.assertIsNone(event1.message)
        self.assertEqual(event1.flow, flow)

        # and update the flow event to be a message event
        response = self.postJSON(
            url,
            "uuid=%s" % event2.uuid,
            {
                "campaign": campaign1.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "weeks",
                "delivery_hour": -1,
                "message": {"base": "OK @(format_urn(urns.tel))", "fra": "D'accord"},
            },
        )
        self.assertEqual(response.status_code, 200)

        event2 = CampaignEvent.objects.filter(campaign=campaign1).order_by("-id").first()
        self.assertEqual(event2.event_type, CampaignEvent.TYPE_MESSAGE)
        self.assertEqual(event2.message, {"base": "OK @(format_urn(urns.tel))", "fra": "D'accord"})

        # and update update it's message again
        response = self.postJSON(
            url,
            "uuid=%s" % event2.uuid,
            {
                "campaign": campaign1.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "weeks",
                "delivery_hour": -1,
                "message": {"base": "OK", "fra": "D'accord", "kin": "Sawa"},
            },
        )
        self.assertEqual(response.status_code, 200)

        event2 = CampaignEvent.objects.filter(campaign=campaign1).order_by("-id").first()
        self.assertEqual(event2.event_type, CampaignEvent.TYPE_MESSAGE)
        self.assertEqual(event2.message, {"base": "OK", "fra": "D'accord", "kin": "Sawa"})

        # try to change an existing event's campaign
        response = self.postJSON(
            url,
            "uuid=%s" % event1.uuid,
            {
                "campaign": campaign2.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "weeks",
                "delivery_hour": -1,
                "flow": flow.uuid,
            },
        )
        self.assertResponseError(response, "campaign", "Cannot change campaign for existing events")

        # try an empty delete request
        response = self.deleteJSON(url, "")
        self.assertResponseError(response, None, "URL must contain one of the following parameters: uuid")

        # delete an event by UUID
        response = self.deleteJSON(url, "uuid=%s" % event1.uuid)
        self.assertEqual(response.status_code, 204)

        self.assertFalse(CampaignEvent.objects.filter(id=event1.id, is_active=True).exists())

    def test_campaignevents_cant_modify_on_inactive_campaign(self):
        url = reverse("api.v2.campaign_events")

        self.login(self.admin)

        reporters = self.create_group("Reporters", [self.joe, self.frank])
        registration = ContactField.get_or_create(
            self.org, self.admin, "registration", "Registration", value_type=ContactField.TYPE_DATETIME
        )

        campaign1 = Campaign.create(self.org, self.admin, "Reminders", reporters)
        event1 = CampaignEvent.create_message_event(
            self.org,
            self.admin,
            campaign1,
            registration,
            1,
            CampaignEvent.UNIT_DAYS,
            "Don't forget to brush your teeth",
        )

        campaign1.is_active = False
        campaign1.save(update_fields=("is_active",))

        # fetch campaign event on inactive campaign
        response = self.fetchJSON(url, "uuid=%s" % event1.uuid)
        self.assertEqual(len(response.json()["results"]), 1)

        # creating a new flow event on the inactive campaign does not work
        response = self.postJSON(
            url,
            None,
            {
                "campaign": campaign1.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "weeks",
                "delivery_hour": -1,
                "message": "Nice job",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"campaign": [f"No such object: {campaign1.uuid}"]})

        # updating a flow event on the inactive campaign does not work
        response = self.postJSON(
            url,
            f"uuid={event1.uuid}",
            {
                "campaign": campaign1.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "weeks",
                "delivery_hour": -1,
                "message": "Nice job",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"campaign": [f"No such object: {campaign1.uuid}"]})

        # we can delete an event on the inactive campaign
        response = self.deleteJSON(url, "uuid=%s" % event1.uuid)
        self.assertEqual(response.status_code, 204)

    def test_campaignevents_on_archived_campaign(self):
        url = reverse("api.v2.campaign_events")

        self.login(self.admin)

        reporters = self.create_group("Reporters", [self.joe, self.frank])
        registration = ContactField.get_or_create(
            self.org, self.admin, "registration", "Registration", value_type=ContactField.TYPE_DATETIME
        )

        campaign1 = Campaign.create(self.org, self.admin, "Reminders", reporters)
        event1 = CampaignEvent.create_message_event(
            self.org,
            self.admin,
            campaign1,
            registration,
            1,
            CampaignEvent.UNIT_DAYS,
            "Don't forget to brush your teeth",
        )

        campaign1.is_active = True
        campaign1.is_archived = True
        campaign1.save(update_fields=("is_active", "is_archived"))

        # creating a new flow event on the archived campaign does not work
        response = self.postJSON(
            url,
            None,
            {
                "campaign": campaign1.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "weeks",
                "delivery_hour": -1,
                "message": "Nice job",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"campaign": [f"No such object: {campaign1.uuid}"]})

        # updating a flow event on the inactive campaign does not work
        response = self.postJSON(
            url,
            f"uuid={event1.uuid}",
            {
                "campaign": campaign1.uuid,
                "relative_to": "registration",
                "offset": 15,
                "unit": "weeks",
                "delivery_hour": -1,
                "message": "Nice job",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"campaign": [f"No such object: {campaign1.uuid}"]})

        # fetch campaign event on archived campaign
        response = self.fetchJSON(url, "uuid=%s" % event1.uuid)
        self.assertEqual(len(response.json()["results"]), 1)

        # we can delete an event on the archived campaign
        response = self.deleteJSON(url, "uuid=%s" % event1.uuid)
        self.assertEqual(response.status_code, 204)

    def test_channels(self):
        url = reverse("api.v2.channels")

        self.assertEndpointAccess(url)

        # create deleted channel
        deleted = self.create_channel("JC", "Deleted", "nyaruka")
        deleted.release(self.admin)

        # create channel for other org
        self.create_channel("TT", "Twitter Channel", "nyaruka", org=self.org2)

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 2):
            response = self.fetchJSON(url, readonly_models={Channel})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertResultsByUUID(response, [self.twitter, self.channel])
        self.assertEqual(
            resp_json["results"][1],
            {
                "uuid": self.channel.uuid,
                "name": "Test Channel",
                "address": "+250785551212",
                "country": "RW",
                "device": {
                    "name": "Nexus 5X",
                    "network_type": None,
                    "power_level": -1,
                    "power_source": None,
                    "power_status": None,
                },
                "last_seen": format_datetime(self.channel.last_seen),
                "created_on": format_datetime(self.channel.created_on),
            },
        )

        # filter by UUID
        response = self.fetchJSON(url, "uuid=%s" % self.twitter.uuid)
        self.assertResultsByUUID(response, [self.twitter])

        # filter by address
        response = self.fetchJSON(url, "address=billy_bob")
        self.assertResultsByUUID(response, [self.twitter])

    def test_channel_events(self):
        url = reverse("api.v2.channel_events")

        self.assertEndpointAccess(url)

        call1 = self.create_channel_event(self.channel, "tel:0788123123", ChannelEvent.TYPE_CALL_IN_MISSED)
        call2 = self.create_channel_event(
            self.channel, "tel:0788124124", ChannelEvent.TYPE_CALL_IN, extra=dict(duration=36)
        )
        call3 = self.create_channel_event(self.channel, "tel:0788124124", ChannelEvent.TYPE_CALL_OUT_MISSED)
        call4 = self.create_channel_event(
            self.channel, "tel:0788123123", ChannelEvent.TYPE_CALL_OUT, extra=dict(duration=15)
        )

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 3):
            response = self.fetchJSON(url, readonly_models={ChannelEvent})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertResultsById(response, [call4, call3, call2, call1])
        self.assertEqual(
            resp_json["results"][0],
            {
                "id": call4.pk,
                "channel": {"uuid": self.channel.uuid, "name": "Test Channel"},
                "type": "call-out",
                "contact": {"uuid": self.joe.uuid, "name": self.joe.name},
                "occurred_on": format_datetime(call4.occurred_on),
                "extra": dict(duration=15),
                "created_on": format_datetime(call4.created_on),
            },
        )

        # filter by id
        response = self.fetchJSON(url, "id=%d" % call1.pk)
        self.assertResultsById(response, [call1])

        # filter by contact
        response = self.fetchJSON(url, "contact=%s" % self.joe.uuid)
        self.assertResultsById(response, [call4, call1])

        # filter by invalid contact
        response = self.fetchJSON(url, "contact=invalid")
        self.assertResultsById(response, [])

        # filter by before
        response = self.fetchJSON(url, "before=%s" % format_datetime(call3.created_on))
        self.assertResultsById(response, [call3, call2, call1])

        # filter by after
        response = self.fetchJSON(url, "after=%s" % format_datetime(call2.created_on))
        self.assertResultsById(response, [call4, call3, call2])

    def test_toggle_channels(self):
        url = reverse("api.v2.toggle_channels")

        self.assertEndpointAccess(url)

        channel = self.create_channel(
            "WAC",
            "WhatsApp: +61923456789",
            "12345",
            config={
                Channel.CONFIG_BASE_URL: "https://nyaruka.com/whatsapp",
                Channel.CONFIG_USERNAME: "temba",
                Channel.CONFIG_PASSWORD: "tembapasswd2",
                Channel.CONFIG_AUTH_TOKEN: "authtoken321",
                CONFIG_FB_BUSINESS_ID: "4321",
                CONFIG_FB_ACCESS_TOKEN: "token123",
                CONFIG_FB_NAMESPACE: "my-custom-app-1",
                CONFIG_FB_TEMPLATE_LIST_DOMAIN: "graph.facebook.com",
            },
        )

        response = self.postJSON(
            url,
            "uuid=%s" % channel.uuid,
            {"action": "disable"},
        )
        self.assertEqual(response.status_code, 200)

        channel.refresh_from_db()
        self.assertEqual(channel.is_active, False)

        response = self.postJSON(
            url,
            "uuid=%s" % channel.uuid,
            {"action": "enable"},
        )
        self.assertEqual(response.status_code, 200)
        channel.refresh_from_db()
        self.assertEqual(channel.is_active, True)

        # filter by UUID
        response = self.fetchJSON(url, "uuid=%s" % channel.uuid)
        self.assertResultsByUUID(response, [channel])

        # filter by address
        response = self.fetchJSON(url, "address=12345")
        self.assertResultsByUUID(response, [channel])

    @mock_mailroom
    def test_contacts(self, mr_mocks):
        url = reverse("api.v2.contacts")

        self.assertEndpointAccess(url)

        # create some more contacts (in addition to Joe and Frank)
        contact1 = self.create_contact(
            "Ann", phone="0788000001", language="fra", fields={"nickname": "Annie", "gender": "female"}
        )
        contact2 = self.create_contact("Bob", phone="0788000002")
        contact3 = self.create_contact("Cat", phone="0788000003")
        contact4 = self.create_contact(
            "Don", phone="0788000004", language="fra", fields={"nickname": "Donnie", "gender": "male"}
        )

        contact1.stop(self.user)
        contact2.block(self.user)
        contact3.release(self.user)

        # put some contacts in a group
        group = self.create_group("Customers", contacts=[self.joe, contact4])
        other_org_group = self.create_group("Nerds", org=self.org2)

        # tweak modified_on so we get the order we want
        self.joe.modified_on = timezone.now()
        self.joe.save(update_fields=("modified_on",))
        contact4.modified_on = timezone.now()
        contact4.last_seen_on = datetime(2020, 8, 12, 13, 30, 45, 123456, pytz.UTC)
        contact4.save(update_fields=("modified_on", "last_seen_on"))

        contact1.refresh_from_db()
        contact4.refresh_from_db()
        self.joe.refresh_from_db()

        # create contact for other org
        hans = self.create_contact("Hans", phone="0788000004", org=self.org2)

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 5):
            response = self.fetchJSON(url, readonly_models={Contact})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertResultsByUUID(response, [contact4, self.joe, contact2, contact1, self.frank])
        self.assertEqual(
            resp_json["results"][0],
            {
                "uuid": contact4.uuid,
                "name": "Don",
                "language": "fra",
                "urns": ["tel:+250788000004"],
                "groups": [{"uuid": group.uuid, "name": group.name}],
                "fields": {"nickname": "Donnie", "gender": "male"},
                "blocked": False,
                "stopped": False,
                "created_on": format_datetime(contact4.created_on),
                "modified_on": format_datetime(contact4.modified_on),
                "last_seen_on": "2020-08-12T13:30:45.123456Z",
            },
        )

        # reversed
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 5):
            response = self.fetchJSON(url, "reverse=true")

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertResultsByUUID(response, [self.frank, contact1, contact2, self.joe, contact4])

        with AnonymousOrg(self.org):
            with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 5):
                response = self.fetchJSON(url)

            resp_json = response.json()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(resp_json["next"], None)
            self.assertResultsByUUID(response, [contact4, self.joe, contact2, contact1, self.frank])
            self.assertEqual(
                resp_json["results"][0],
                {
                    "uuid": contact4.uuid,
                    "name": "Don",
                    "language": "fra",
                    "urns": ["tel:********"],
                    "groups": [{"uuid": group.uuid, "name": group.name}],
                    "fields": {"nickname": "Donnie", "gender": "male"},
                    "blocked": False,
                    "stopped": False,
                    "created_on": format_datetime(contact4.created_on),
                    "modified_on": format_datetime(contact4.modified_on),
                    "last_seen_on": "2020-08-12T13:30:45.123456Z",
                },
            )

        # filter by UUID
        response = self.fetchJSON(url, "uuid=%s" % contact2.uuid)
        self.assertResultsByUUID(response, [contact2])

        # filter by URN (which should be normalized)
        response = self.fetchJSON(url, "urn=%s" % quote_plus("tel:078-8000004"))
        self.assertResultsByUUID(response, [contact4])

        # filter by seacrh
        response = self.fetchJSON(url, "search=%s" % quote_plus("tel:078-8000004"))
        self.assertResultsByUUID(response, [contact4])

        # filter by search without urn
        response = self.fetchJSON(url, "search=%s" % contact2.name)
        self.assertResultsByUUID(response, [contact2])

        # filter by Name
        response = self.fetchJSON(url, "name=%s" % contact2.name)
        self.assertResultsByUUID(response, [contact2])

        # error if URN can't be parsed
        response = self.fetchJSON(url, "urn=12345")
        self.assertResponseError(response, None, "Invalid URN: 12345")

        # filter by group name
        response = self.fetchJSON(url, "group=Customers")
        self.assertResultsByUUID(response, [contact4, self.joe])

        # filter by group UUID
        response = self.fetchJSON(url, "group=%s" % group.uuid)
        self.assertResultsByUUID(response, [contact4, self.joe])

        # filter by invalid group
        response = self.fetchJSON(url, "group=invalid")
        self.assertResultsByUUID(response, [])

        # filter by before
        response = self.fetchJSON(url, "before=%s" % format_datetime(contact1.modified_on))
        self.assertResultsByUUID(response, [contact1, self.frank])

        # filter by after
        response = self.fetchJSON(url, "after=%s" % format_datetime(self.joe.modified_on))
        self.assertResultsByUUID(response, [contact4, self.joe])

        # test limit
        response = self.fetchJSON(url, "limit=2")
        self.assertResultsByUUID(response, [contact4, self.joe])

        # passing a order_by param
        response = self.fetchJSON(url, "group=%s&order_by=created_on" % group.uuid)
        self.assertResultsByUUID(response, [self.joe, contact4])

        # passing a order_by param error
        response = self.fetchJSON(url, "group=%s&order_by=name" % group.uuid)
        self.assertResultsByUUID(response, [contact4, self.joe])

        # view the deleted contact
        response = self.fetchJSON(url, "deleted=true")
        self.assertResultsByUUID(response, [contact3])
        self.assertEqual(
            response.json()["results"][0],
            {
                "uuid": contact3.uuid,
                "name": None,
                "language": None,
                "urns": [],
                "groups": [],
                "fields": {},
                "blocked": None,
                "stopped": None,
                "created_on": format_datetime(contact3.created_on),
                "modified_on": format_datetime(contact3.modified_on),
                "last_seen_on": None,
            },
        )

        # try to post something other than an object
        response = self.postJSON(url, None, [])
        self.assertEqual(response.status_code, 400)

        # create an empty contact
        response = self.postJSON(url, None, {})
        self.assertEqual(response.status_code, 201)

        empty = Contact.objects.get(name=None, is_active=True)

        self.assertEqual(
            response.json(),
            {
                "uuid": empty.uuid,
                "name": None,
                "language": None,
                "urns": [],
                "groups": [],
                "fields": {"nickname": None, "gender": None},
                "blocked": False,
                "stopped": False,
                "created_on": format_datetime(empty.created_on),
                "modified_on": format_datetime(empty.modified_on),
                "last_seen_on": None,
            },
        )

        # create with all fields but empty
        response = self.postJSON(url, None, {"name": None, "language": None, "urns": [], "groups": [], "fields": {}})
        self.assertEqual(response.status_code, 201)

        jaqen = Contact.objects.order_by("id").last()
        self.assertIsNone(jaqen.name)
        self.assertIsNone(jaqen.language)
        self.assertEqual(Contact.STATUS_ACTIVE, jaqen.status)
        self.assertEqual(set(), set(jaqen.urns.all()))
        self.assertEqual(set(), set(jaqen.user_groups.all()))
        self.assertIsNone(jaqen.fields)

        # create a dynamic group
        dyn_group = self.create_group("Dynamic Group", query="name = Frank")
        ContactGroup.user_groups.filter(id=dyn_group.id).update(status=ContactGroup.STATUS_READY)

        # create with all fields
        response = self.postJSON(
            url,
            None,
            {
                "name": "Jean",
                "language": "fra",
                "urns": ["tel:+250783333333", "twitter:JEAN"],
                "groups": [group.uuid],
                "fields": {"nickname": "Jado"},
            },
        )
        self.assertEqual(response.status_code, 201)

        resp_json = response.json()
        self.assertEqual(resp_json["urns"], ["tel:+250783333333", "twitter:jean"])

        # URNs will be normalized
        nickname = ContactField.get_by_key(self.org, "nickname")
        gender = ContactField.get_by_key(self.org, "gender")
        jean = Contact.objects.filter(name="Jean", language="fra").order_by("-pk").first()
        self.assertEqual(set(jean.urns.values_list("identity", flat=True)), {"tel:+250783333333", "twitter:jean"})
        self.assertEqual(set(jean.user_groups.all()), {group})
        self.assertEqual(jean.get_field_value(nickname), "Jado")

        # try to create with group from other org
        response = self.postJSON(url, None, {"name": "Jim", "groups": [other_org_group.uuid]})
        self.assertResponseError(response, "groups", f"No such object: {other_org_group.uuid}")

        # try to create with invalid fields
        response = self.postJSON(
            url,
            None,
            {
                "name": "Jim",
                "language": "xyz",
                "urns": ["1234556789"],
                "groups": ["59686b4e-14bc-4160-9376-b649b218c806"],
                "fields": {"hmmm": "X"},
            },
        )
        self.assertResponseError(response, "language", "Not a valid ISO639-3 language code.")
        self.assertResponseError(response, "groups", "No such object: 59686b4e-14bc-4160-9376-b649b218c806")
        self.assertResponseError(response, "fields", "Invalid contact field key: hmmm")

        self.assertEqual(
            response.json()["urns"], {"0": ["Invalid URN: 1234556789. Ensure phone numbers contain country codes."]}
        )

        # update an existing contact by UUID but don't provide any fields
        response = self.postJSON(url, "uuid=%s" % jean.uuid, {})
        self.assertEqual(response.status_code, 200)

        # contact should be unchanged
        jean = Contact.objects.get(pk=jean.pk)
        self.assertEqual(jean.name, "Jean")
        self.assertEqual(jean.language, "fra")
        self.assertEqual(set(jean.urns.values_list("identity", flat=True)), {"tel:+250783333333", "twitter:jean"})
        self.assertEqual(set(jean.user_groups.all()), {group})
        self.assertEqual(jean.get_field_value(nickname), "Jado")

        # update by UUID and change all fields
        response = self.postJSON(
            url,
            "uuid=%s" % jean.uuid,
            {
                "name": "Jason Undead",
                "language": "ita",
                "urns": ["tel:+250784444444"],
                "groups": [],
                "fields": {"nickname": "Žan", "gender": "frog"},
            },
        )
        self.assertEqual(response.status_code, 200)

        jean = Contact.objects.get(pk=jean.pk)
        self.assertEqual(jean.name, "Jason Undead")
        self.assertEqual(jean.language, "ita")
        self.assertEqual(set(jean.urns.values_list("identity", flat=True)), {"tel:+250784444444"})
        self.assertEqual(set(jean.user_groups.all()), set())
        self.assertEqual(jean.get_field_value(nickname), "Žan")
        self.assertEqual(jean.get_field_value(gender), "frog")

        # change the language field
        response = self.postJSON(
            url,
            "uuid=%s" % jean.uuid,
            {"name": "Jean II", "language": "eng", "urns": ["tel:+250784444444"], "groups": [], "fields": {}},
        )
        self.assertEqual(response.status_code, 200)
        jean = Contact.objects.get(pk=jean.pk)
        self.assertEqual(jean.name, "Jean II")
        self.assertEqual(jean.language, "eng")
        self.assertEqual(set(jean.urns.values_list("identity", flat=True)), {"tel:+250784444444"})
        self.assertEqual(set(jean.user_groups.all()), set())
        self.assertEqual(jean.get_field_value(nickname), "Žan")

        # update by uuid and remove all fields
        response = self.postJSON(
            url,
            "uuid=%s" % jean.uuid,
            {
                "name": "Jean II",
                "language": "eng",
                "urns": ["tel:+250784444444"],
                "groups": [],
                "fields": {"nickname": "", "gender": ""},
            },
        )
        self.assertEqual(response.status_code, 200)

        jean = Contact.objects.get(pk=jean.pk)
        self.assertEqual(jean.get_field_value(nickname), None)
        self.assertEqual(jean.get_field_value(gender), None)

        # update by uuid and update/remove fields
        response = self.postJSON(
            url,
            "uuid=%s" % jean.uuid,
            {
                "name": "Jean II",
                "language": "eng",
                "urns": ["tel:+250784444444"],
                "groups": [],
                "fields": {"nickname": "Jado", "gender": ""},
            },
        )
        self.assertEqual(response.status_code, 200)

        jean = Contact.objects.get(pk=jean.pk)
        self.assertEqual(jean.get_field_value(nickname), "Jado")
        self.assertEqual(jean.get_field_value(gender), None)

        # update by URN (which should be normalized)
        response = self.postJSON(url, "urn=%s" % quote_plus("tel:+250-78-4444444"), {"name": "Jean III"})
        self.assertEqual(response.status_code, 200)

        jean = Contact.objects.get(pk=jean.pk)
        self.assertEqual(jean.name, "Jean III")

        # try to specify URNs field whilst referencing by URN
        response = self.postJSON(url, "urn=%s" % quote_plus("tel:+250784444444"), {"urns": ["tel:+250785555555"]})
        self.assertResponseError(response, "urns", "Field not allowed when using URN in URL")

        # if contact doesn't exist with URN, they're created
        response = self.postJSON(url, "urn=%s" % quote_plus("tel:+250-78-5555555"), {"name": "Bobby"})
        self.assertEqual(response.status_code, 201)

        # URN should be normalized
        bobby = Contact.objects.get(name="Bobby")
        self.assertEqual(set(bobby.urns.values_list("identity", flat=True)), {"tel:+250785555555"})

        # try to create a contact with a URN belonging to another contact
        response = self.postJSON(url, None, {"name": "Robert", "urns": ["tel:+250-78-5555555"]})
        self.assertEqual(response.status_code, 400)
        self.assertResponseError(response, "urns", "URN belongs to another contact: tel:+250785555555")

        # try to update a contact with non-existent UUID
        response = self.postJSON(url, "uuid=ad6acad9-959b-4d70-b144-5de2891e4d00", {})
        self.assert404(response)

        # try to update a contact in another org
        response = self.postJSON(url, "uuid=%s" % hans.uuid, {})
        self.assert404(response)

        # try to add a contact to a dynamic group
        response = self.postJSON(url, "uuid=%s" % jean.uuid, {"groups": [dyn_group.uuid]})
        self.assertResponseError(response, "groups", "Contact group must not be dynamic: %s" % dyn_group.uuid)

        # try to give a contact more than 100 URNs
        response = self.postJSON(url, "uuid=%s" % jean.uuid, {"urns": ["twitter:bob%d" % u for u in range(101)]})
        self.assertResponseError(response, "urns", "This field can only contain up to 100 items.")

        # try to give a contact more than 100 contact fields
        response = self.postJSON(url, "uuid=%s" % jean.uuid, {"fields": {"field_%d" % f: f for f in range(101)}})
        self.assertResponseError(response, "fields", "This field can only contain up to 100 items.")

        # ok to give them 100 URNs
        response = self.postJSON(url, "uuid=%s" % jean.uuid, {"urns": ["twitter:bob%d" % u for u in range(100)]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(jean.urns.count(), 100)

        # try to move a blocked contact into a group
        jean.block(self.user)
        response = self.postJSON(url, "uuid=%s" % jean.uuid, {"groups": [group.uuid]})
        self.assertResponseError(response, "groups", "Non-active contacts can't be added to groups")

        # try to update a contact by both UUID and URN
        response = self.postJSON(url, "uuid=%s&urn=%s" % (jean.uuid, quote_plus("tel:+250784444444")), {})
        self.assertResponseError(
            response, None, "URL can only contain one of the following parameters: name, urn, uuid"
        )

        # try an empty delete request
        response = self.deleteJSON(url, None)
        self.assertResponseError(response, None, "URL must contain one of the following parameters: name, urn, uuid")

        # delete a contact by UUID
        response = self.deleteJSON(url, "uuid=%s" % jean.uuid)
        self.assertEqual(response.status_code, 204)

        jean.refresh_from_db()
        self.assertFalse(jean.is_active)

        response = self.postJSON(url, "uuid=%s" % jean.uuid, {})
        self.assertResponseError(response, "non_field_errors", "Inactive contacts can't be modified.")

        # create xavier
        response = self.postJSON(url, None, {"name": "Xavier", "urns": ["tel:+250-78-7777777", "twitter:XAVIER"]})
        self.assertEqual(response.status_code, 201)

        xavier = Contact.objects.get(name="Xavier")
        self.assertEqual(set(xavier.urns.values_list("identity", flat=True)), {"twitter:xavier", "tel:+250787777777"})

        # updating fields by urn should keep all exiting urns
        response = self.postJSON(url, "urn=%s" % quote_plus("tel:+250787777777"), {"fields": {"gender": "Male"}})
        self.assertEqual(response.status_code, 200)

        xavier = Contact.objects.get(name="Xavier")
        self.assertEqual(set(xavier.urns.values_list("identity", flat=True)), {"twitter:xavier", "tel:+250787777777"})
        self.assertEqual(xavier.get_field_value(gender), "Male")

        # delete a contact by URN (which should be normalized)
        response = self.deleteJSON(url, "urn=%s" % quote_plus("twitter:XAVIER"))
        self.assertEqual(response.status_code, 204)

        xavier.refresh_from_db()
        self.assertFalse(xavier.is_active)

        # try deleting a contact by a non-existent URN
        response = self.deleteJSON(url, "urn=twitter:billy")
        self.assert404(response)

        # try to delete a contact in another org
        response = self.deleteJSON(url, "uuid=%s" % hans.uuid)
        self.assert404(response)

        # Add key to verify ninth digit
        self.org.config["verify_ninth_digit"] = True
        self.org.save()

        # Verify brazilian whatsapp urn with ninth digit
        self.create_contact("Julius", urns=["whatsapp:5521912345678"])
        response = self.postJSON(url, "urn=%s" % quote_plus("whatsapp:552112345678"), {"name": "Julito"})
        self.assertEqual(response.status_code, 200)

        # Verify brazilian whatsapp urn without ninth digit
        self.create_contact("Rochele", urns=["whatsapp:558912345678"])

        response = self.postJSON(url, "urn=%s" % quote_plus("whatsapp:5589912345678"), {"name": "Rochel"})
        self.assertEqual(response.status_code, 200)

    @mock_mailroom
    def test_contacts_lean(self, mr_mocks):
        url = reverse("api.v2.contacts_lean")

        self.assertEndpointAccess(url)

        # create some more contacts (in addition to Joe and Frank)
        contact1 = self.create_contact(
            "Mary", phone="0788000001", language="fra", fields={"nickname": "Mary", "gender": "female"}
        )
        contact2 = self.create_contact("Rob", phone="0788000002")
        contact3 = self.create_contact("Paul", phone="0788000003")
        contact4 = self.create_contact(
            "Dominic", phone="0788000004", language="fra", fields={"nickname": "Donnie", "gender": "male"}
        )

        contact1.stop(self.user)
        contact2.block(self.user)
        contact3.release(self.user)

        # put some contacts in a group
        group = self.create_group("Customers", contacts=[self.joe, contact4])

        # tweak modified_on so we get the order we want
        self.joe.modified_on = timezone.now()
        self.joe.save(update_fields=("modified_on",))
        contact4.modified_on = timezone.now()
        contact4.last_seen_on = datetime(2020, 8, 12, 13, 30, 45, 123456, pytz.UTC)
        contact4.save(update_fields=("modified_on", "last_seen_on"))

        contact1.refresh_from_db()
        contact4.refresh_from_db()
        self.joe.refresh_from_db()

        # filter by UUID
        response = self.fetchJSON(url, "uuid=%s" % contact2.uuid)
        self.assertResultsByUUID(response, [contact2])

        # filter by seacrh
        response = self.fetchJSON(url, "search=%s" % quote_plus("tel:078-8000004"))
        self.assertResultsByUUID(response, [contact4])

        # filter by search without urn
        response = self.fetchJSON(url, "search=%s" % contact2.name)
        self.assertResultsByUUID(response, [contact2])

        # filter by Name
        response = self.fetchJSON(url, "name=%s" % contact2.name)
        self.assertResultsByUUID(response, [contact2])

        # filter by group name
        response = self.fetchJSON(url, "group=Customers")
        self.assertResultsByUUID(response, [contact4, self.joe])

        # filter by group UUID
        response = self.fetchJSON(url, "group=%s" % group.uuid)
        self.assertResultsByUUID(response, [contact4, self.joe])

        # filter by invalid group
        response = self.fetchJSON(url, "group=invalid")
        self.assertResultsByUUID(response, [])

        # filter by before
        response = self.fetchJSON(url, "before=%s" % format_datetime(contact1.modified_on))
        self.assertResultsByUUID(response, [contact1, self.frank])

        # filter by after
        response = self.fetchJSON(url, "after=%s" % format_datetime(self.joe.modified_on))
        self.assertResultsByUUID(response, [contact4, self.joe])

        # test limit
        response = self.fetchJSON(url, "limit=2")
        self.assertResultsByUUID(response, [contact4, self.joe])

        # passing a order_by param
        response = self.fetchJSON(url, "group=%s&order_by=created_on" % group.uuid)
        self.assertResultsByUUID(response, [self.joe, contact4])

        # passing a order_by param error
        response = self.fetchJSON(url, "group=%s&order_by=name" % group.uuid)
        self.assertResultsByUUID(response, [contact4, self.joe])

    def test_prevent_modifying_contacts_with_fields_that_have_null_chars(self):
        """
        Verifies fix for: https://sentry.io/nyaruka/textit/issues/770220071/
        """

        url = reverse("api.v2.contacts")
        self.assertEndpointAccess(url)

        ContactField.get_or_create(self.org, self.admin, "string_field")
        ContactField.get_or_create(self.org, self.admin, "number_field", value_type=ContactField.TYPE_NUMBER)

        # test create with a null chars \u0000
        response = self.postJSON(
            url,
            None,
            {
                "name": "Jean",
                "language": "fra",
                "urns": ["tel:+250783333334"],
                "groups": [],
                "fields": {"string_field": "crayons on the wall \u0000, pudding on the wall \x00, yeah \0"},
            },
        )
        response_json = response.json()
        self.assertTrue("string_field" in response_json["fields"])
        self.assertEqual(response_json["fields"]["string_field"], ["Null characters are not allowed."])

        # test create with a null chars \u0000
        response = self.postJSON(
            url,
            None,
            {
                "name": "Jean",
                "language": "fra",
                "urns": ["tel:+250783333334"],
                "groups": [],
                "fields": {"number_field": "123\u0000"},
            },
        )

        response_json = response.json()
        self.assertTrue("number_field" in response_json["fields"])
        self.assertEqual(response_json["fields"]["number_field"], ["Null characters are not allowed."])

    @mock_mailroom
    def test_contact_action_update_datetime_field(self, mr_mocks):
        url = reverse("api.v2.contacts")

        self.assertEndpointAccess(url)

        self.create_field("tag_activated_at", "Tag activation", ContactField.TYPE_DATETIME)

        # update contact with valid date format for the org - DD-MM-YYYY
        response = self.postJSON(url, "uuid=%s" % self.joe.uuid, {"fields": {"tag_activated_at": "31-12-2017"}})
        self.assertEqual(response.status_code, 200)
        resp_json = response.json()

        self.assertIsNotNone(resp_json["fields"]["tag_activated_at"])

        # update contact with valid ISO8601 timestamp value with timezone
        response = self.postJSON(
            url, "uuid=%s" % self.joe.uuid, {"fields": {"tag_activated_at": "2017-11-11T11:12:13Z"}}
        )
        self.assertEqual(response.status_code, 200)
        resp_json = response.json()

        self.assertEqual(resp_json["fields"]["tag_activated_at"], "2017-11-11T13:12:13+02:00")

        # update contact with valid ISO8601 timestamp value, 'T' replaced with space
        response = self.postJSON(
            url, "uuid=%s" % self.joe.uuid, {"fields": {"tag_activated_at": "2017-11-11 11:12:13Z"}}
        )
        self.assertEqual(response.status_code, 200)
        resp_json = response.json()

        self.assertEqual(resp_json["fields"]["tag_activated_at"], "2017-11-11T13:12:13+02:00")

        # update contact with invalid ISO8601 timestamp value without timezone
        response = self.postJSON(
            url, "uuid=%s" % self.joe.uuid, {"fields": {"tag_activated_at": "2017-11-11T11:12:13"}}
        )
        self.assertEqual(response.status_code, 200)
        resp_json = response.json()

        self.assertIsNone(resp_json["fields"]["tag_activated_at"])

        # update contact with invalid date format for the org - MM-DD-YYYY
        response = self.postJSON(url, "uuid=%s" % self.joe.uuid, {"fields": {"tag_activated_at": "12-31-2017"}})
        self.assertEqual(response.status_code, 200)
        resp_json = response.json()

        self.assertIsNone(resp_json["fields"]["tag_activated_at"])

        # update contact with invalid timestamp value
        response = self.postJSON(url, "uuid=%s" % self.joe.uuid, {"fields": {"tag_activated_at": "el123a41"}})
        self.assertEqual(response.status_code, 200)
        resp_json = response.json()

        self.assertIsNone(resp_json["fields"]["tag_activated_at"])

    @mock_mailroom
    def test_contact_actions_if_org_is_anonymous(self, mr_mocks):
        url = reverse("api.v2.contacts")
        self.assertEndpointAccess(url)

        group = ContactGroup.get_or_create(self.org, self.admin, "Customers")

        response = self.postJSON(
            url,
            None,
            {
                "name": "Jean",
                "language": "fra",
                "urns": ["tel:+250783333333", "twitter:JEAN"],
                "groups": [group.uuid],
                "fields": {},
            },
        )
        self.assertEqual(response.status_code, 201)

        jean = Contact.objects.filter(name="Jean", language="fra").get()

        with AnonymousOrg(self.org):
            # can't update via URN
            response = self.postJSON(url, "urn=%s" % "tel:+250785555555", {})
            self.assertEqual(response.status_code, 400)
            self.assertResponseError(response, None, "URN lookups not allowed for anonymous organizations")

            # can't update contact URNs
            response = self.postJSON(url, "uuid=%s" % jean.uuid, {"urns": ["tel:+250786666666"]})
            self.assertEqual(response.status_code, 400)
            self.assertResponseError(response, "urns", "Updating URNs not allowed for anonymous organizations")

            # output shouldn't include URNs
            response = self.fetchJSON(url, "uuid=%s" % jean.uuid)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["results"][0]["urns"], ["tel:********", "twitter:********"])

            # but can create with URNs
            response = self.postJSON(url, None, {"name": "Xavier", "urns": ["tel:+250-78-7777777", "twitter:XAVIER"]})
            self.assertEqual(response.status_code, 201)

            # TODO should UUID be masked in response??
            xavier = Contact.objects.get(name="Xavier")
            self.assertEqual(
                set(xavier.urns.values_list("identity", flat=True)), {"tel:+250787777777", "twitter:xavier"}
            )

            # can't filter by URN
            response = self.fetchJSON(url, "urn=%s" % quote_plus("tel:+250-78-8000004"))
            self.assertEqual(response.status_code, 400)
            self.assertResponseError(response, None, "URN lookups not allowed for anonymous organizations")

    @mock_mailroom
    def test_contact_create_with_urns(self, mr_mocks):
        url = reverse("api.v2.contacts")
        self.assertEndpointAccess(url)

        # one of the URNs will already exist in an orphaned state
        ContactURN.get_or_create(self.org, None, "tel:+250783333335")

        # test create with a null chars \u0000
        response = self.postJSON(
            url, None, {"name": "Jean", "urns": ["tel:+250783333334", "tel:+250783333335", "tel:+250783333336"]}
        )
        self.assertEqual(201, response.status_code)

        # check URNs are in the specified order
        contact = Contact.objects.get(name="Jean")
        self.assertEqual(
            ["tel:+250783333334", "tel:+250783333335", "tel:+250783333336"], [u.identity for u in contact.get_urns()]
        )

    @mock_mailroom
    def test_contact_actions(self, mr_mocks):
        url = reverse("api.v2.contact_actions")

        self.assertEndpointAccess(url, fetch_returns=405)

        for contact in Contact.objects.all():
            contact.release(self.admin)
            contact.delete()

        # create some contacts to act on
        contact1 = self.create_contact("Ann", phone="+250788000001")
        contact2 = self.create_contact("Bob", phone="+250788000002")
        contact3 = self.create_contact("Cat", phone="+250788000003")
        contact4 = self.create_contact("Don", phone="+250788000004")  # a blocked contact
        contact5 = self.create_contact("Eve", phone="+250788000005")  # a deleted contact
        contact4.block(self.user)
        contact5.release(self.user)

        group = self.create_group("Testers")
        self.create_field("isdeveloper", "Is developer")
        self.create_group("Developers", query="isdeveloper = YES")
        other_org_group = self.create_group("Testers", org=self.org2)

        # create some "active" runs for some of the contacts
        flow = self.get_flow("favorites_v13")
        FlowRun.objects.create(org=self.org, flow=flow, contact=contact1)
        FlowRun.objects.create(org=self.org, flow=flow, contact=contact2)
        FlowRun.objects.create(org=self.org, flow=flow, contact=contact3)

        self.create_incoming_msg(contact1, "Hello")
        self.create_incoming_msg(contact2, "Hello")
        self.create_incoming_msg(contact3, "Hello")
        self.create_incoming_msg(contact4, "Hello")

        # try adding more contacts to group than this endpoint is allowed to operate on at one time
        response = self.postJSON(
            url, None, {"contacts": [str(x) for x in range(101)], "action": "add", "group": "Testers"}
        )
        self.assertResponseError(response, "contacts", "This field can only contain up to 100 items.")

        # try adding all contacts to a group by its name
        response = self.postJSON(
            url,
            None,
            {
                "contacts": [contact1.uuid, "tel:+250788000002", contact3.uuid, contact4.uuid, contact5.uuid],
                "action": "add",
                "group": "Testers",
            },
        )

        # error reporting that at least one of the UUIDs is not a valid contact
        self.assertResponseError(response, "contacts", "No such object: %s" % contact5.uuid)

        # try adding a blocked contact to a group
        response = self.postJSON(
            url,
            None,
            {
                "contacts": [contact1.uuid, contact2.uuid, contact3.uuid, contact4.uuid],
                "action": "add",
                "group": "Testers",
            },
        )

        # error reporting that the deleted and test contacts are invalid
        self.assertResponseError(
            response, "non_field_errors", "Non-active contacts cannot be added to groups: %s" % contact4.uuid
        )

        # add valid contacts to the group by name
        response = self.postJSON(
            url, None, {"contacts": [contact1.uuid, "tel:+250788000002"], "action": "add", "group": "Testers"}
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(group.contacts.all()), {contact1, contact2})

        # try to add to a non-existent group
        response = self.postJSON(url, None, {"contacts": [contact1.uuid], "action": "add", "group": "Spammers"})
        self.assertResponseError(response, "group", "No such object: Spammers")

        # try to add to a dynamic group
        response = self.postJSON(url, None, {"contacts": [contact1.uuid], "action": "add", "group": "Developers"})
        self.assertResponseError(response, "group", "Contact group must not be dynamic: Developers")

        # add contact 3 to a group by its UUID
        response = self.postJSON(url, None, {"contacts": [contact3.uuid], "action": "add", "group": group.uuid})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(group.contacts.all()), {contact1, contact2, contact3})

        # try adding with invalid group UUID
        response = self.postJSON(url, None, {"contacts": [contact3.uuid], "action": "add", "group": "nope"})
        self.assertResponseError(response, "group", "No such object: nope")

        # try to add to a group in another org
        response = self.postJSON(
            url, None, {"contacts": [contact1.uuid], "action": "add", "group": other_org_group.uuid}
        )
        self.assertResponseError(response, "group", f"No such object: {other_org_group.uuid}")

        # remove contact 2 from group by its name (which is case-insensitive)
        response = self.postJSON(url, None, {"contacts": [contact2.uuid], "action": "remove", "group": "testers"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(group.contacts.all()), {contact1, contact3})

        # and remove contact 3 from group by its UUID
        response = self.postJSON(url, None, {"contacts": [contact3.uuid], "action": "remove", "group": group.uuid})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(group.contacts.all()), {contact1})

        # try to add to group without specifying a group
        response = self.postJSON(url, None, {"contacts": [contact1.uuid], "action": "add"})
        self.assertResponseError(response, "non_field_errors", 'For action "add" you should also specify a group')
        response = self.postJSON(url, None, {"contacts": [contact1.uuid], "action": "add", "group": ""})
        self.assertResponseError(response, "group", "This field may not be null.")

        # block all contacts
        response = self.postJSON(
            url, None, {"contacts": [contact1.uuid, contact2.uuid, contact3.uuid, contact4.uuid], "action": "block"}
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            set(Contact.objects.filter(status=Contact.STATUS_BLOCKED)), {contact1, contact2, contact3, contact4}
        )

        # unblock contact 1
        response = self.postJSON(url, None, {"contacts": [contact1.uuid], "action": "unblock"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(self.org.contacts.filter(status=Contact.STATUS_ACTIVE)), {contact1, contact5})
        self.assertEqual(set(self.org.contacts.filter(status=Contact.STATUS_BLOCKED)), {contact2, contact3, contact4})

        # interrupt any active runs of contacts 1 and 2
        with patch("temba.mailroom.queue_interrupt") as mock_queue_interrupt:
            response = self.postJSON(url, None, {"contacts": [contact1.uuid, contact2.uuid], "action": "interrupt"})
            self.assertEqual(response.status_code, 204)

            mock_queue_interrupt.assert_called_once_with(self.org, contacts=[contact1, contact2])

        # archive all messages for contacts 1 and 2
        response = self.postJSON(url, None, {"contacts": [contact1.uuid, contact2.uuid], "action": "archive_messages"})
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Msg.objects.filter(contact__in=[contact1, contact2], direction="I", visibility="V").exists())
        self.assertTrue(Msg.objects.filter(contact=contact3, direction="I", visibility="V").exists())

        # delete contacts 1 and 2
        response = self.postJSON(url, None, {"contacts": [contact1.uuid, contact2.uuid], "action": "delete"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(self.org.contacts.filter(is_active=False)), {contact1, contact2, contact5})
        self.assertEqual(set(self.org.contacts.filter(is_active=True)), {contact3, contact4})
        self.assertFalse(Msg.objects.filter(contact__in=[contact1, contact2]).exclude(visibility="D").exists())
        self.assertTrue(Msg.objects.filter(contact=contact3).exclude(visibility="D").exists())

        # try to provide a group for a non-group action
        response = self.postJSON(url, None, {"contacts": [contact3.uuid], "action": "block", "group": "Testers"})
        self.assertResponseError(response, "non_field_errors", 'For action "block" you should not specify a group')

        # trying to act on zero contacts is an error
        response = self.postJSON(url, None, {"contacts": [], "action": "interrupt"})
        self.assertResponseError(response, "contacts", "Contacts can't be empty.")

        # try to invoke an invalid action
        response = self.postJSON(url, None, {"contacts": [contact3.uuid], "action": "like"})
        self.assertResponseError(response, "action", '"like" is not a valid choice.')

    def test_definitions_with_non_legacy_flow(self):
        url = reverse("api.v2.definitions")

        self.login(self.admin)

        self.import_file("favorites_v13")

        flow = Flow.objects.filter(name="Favorites").first()

        response = self.fetchJSON(url, "flow=%s" % flow.uuid)

        self.assertEqual(len(response.json()["flows"]), 1)
        self.assertEqual(len(response.json()["flows"][0]["nodes"]), 9)
        self.assertEqual(response.json()["flows"][0]["spec_version"], Flow.CURRENT_SPEC_VERSION)

    def test_definitions(self):
        url = reverse("api.v2.definitions")

        self.assertEndpointAccess(url)

        self.import_file("subflow")
        flow = Flow.objects.filter(name="Parent Flow").first()

        # all flow dependencies and we should get the child flow
        response = self.fetchJSON(url, "flow=%s" % flow.uuid)
        self.assertEqual({f["name"] for f in response.json()["flows"]}, {"Parent Flow", "Child Flow"})

        # export just the parent flow
        response = self.fetchJSON(url, "flow=%s&dependencies=none" % flow.uuid)
        self.assertEqual({f["name"] for f in response.json()["flows"]}, {"Parent Flow"})

        # import the clinic app which has campaigns
        self.import_file("the_clinic")

        # our catchall flow, all alone
        flow = Flow.objects.filter(name="Catch All").first()
        response = self.fetchJSON(url, "flow=%s&dependencies=none" % flow.uuid)
        resp_json = response.json()
        self.assertEqual(len(resp_json["flows"]), 1)
        self.assertEqual(len(resp_json["campaigns"]), 0)
        self.assertEqual(len(resp_json["triggers"]), 0)

        # with its trigger dependency
        response = self.fetchJSON(url, "flow_uuid=%s" % flow.uuid)
        resp_json = response.json()
        self.assertEqual(len(resp_json["flows"]), 1)
        self.assertEqual(len(resp_json["campaigns"]), 0)
        self.assertEqual(len(resp_json["triggers"]), 1)

        # our registration flow, all alone
        flow = Flow.objects.filter(name="Register Patient").first()
        response = self.fetchJSON(url, "flow=%s&dependencies=none" % flow.uuid)
        resp_json = response.json()
        self.assertEqual(len(resp_json["flows"]), 1)
        self.assertEqual(len(resp_json["campaigns"]), 0)
        self.assertEqual(len(resp_json["triggers"]), 0)

        # touches a lot of stuff
        response = self.fetchJSON(url, "flow=%s" % flow.uuid)
        resp_json = response.json()
        self.assertEqual(len(resp_json["flows"]), 6)
        self.assertEqual(len(resp_json["campaigns"]), 1)
        self.assertEqual(len(resp_json["triggers"]), 2)

        # ignore campaign dependencies
        response = self.fetchJSON(url, "flow=%s&dependencies=flows" % flow.uuid)
        resp_json = response.json()
        self.assertEqual(len(resp_json["flows"]), 2)
        self.assertEqual(len(resp_json["campaigns"]), 0)
        self.assertEqual(len(resp_json["triggers"]), 1)

        # add our missed call flow
        missed_call = Flow.objects.filter(name="Missed Call").first()
        response = self.fetchJSON(url, "flow=%s&flow=%s&dependencies=all" % (flow.uuid, missed_call.uuid))
        resp_json = response.json()
        self.assertEqual(len(resp_json["flows"]), 7)
        self.assertEqual(len(resp_json["campaigns"]), 1)
        self.assertEqual(len(resp_json["triggers"]), 3)

        campaign = Campaign.objects.filter(name="Appointment Schedule").first()
        response = self.fetchJSON(url, "campaign=%s&dependencies=none" % campaign.uuid)
        resp_json = response.json()
        self.assertEqual(len(resp_json["flows"]), 0)
        self.assertEqual(len(resp_json["campaigns"]), 1)
        self.assertEqual(len(resp_json["triggers"]), 0)

        response = self.fetchJSON(url, "campaign=%s" % campaign.uuid)
        resp_json = response.json()
        self.assertEqual(len(resp_json["flows"]), 6)
        self.assertEqual(len(resp_json["campaigns"]), 1)
        self.assertEqual(len(resp_json["triggers"]), 2)

        # test deprecated param names
        response = self.fetchJSON(url, "flow_uuid=%s&campaign_uuid=%s&dependencies=none" % (flow.uuid, campaign.uuid))
        resp_json = response.json()
        self.assertEqual(len(resp_json["flows"]), 1)
        self.assertEqual(len(resp_json["campaigns"]), 1)
        self.assertEqual(len(resp_json["triggers"]), 0)

        # test an invalid value for dependencies
        response = self.fetchJSON(url, "flow_uuid=%s&campaign_uuid=%s&dependencies=xx" % (flow.uuid, campaign.uuid))
        self.assertResponseError(response, None, "dependencies must be one of none, flows, all")

    @override_settings(ORG_LIMIT_DEFAULTS={"fields": 10})
    def test_fields(self):
        url = reverse("api.v2.fields")

        self.assertEndpointAccess(url)

        self.create_field("nick_name", "Nick Name")
        self.create_field("registered", "Registered On", value_type=ContactField.TYPE_DATETIME)
        self.create_field("not_ours", "Something Else", org=self.org2)

        deleted = self.create_field("deleted", "Deleted")
        deleted.release(self.admin)

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 1):
            response = self.fetchJSON(url, readonly_models={ContactField})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {"key": "registered", "label": "Registered On", "value_type": "datetime", "pinned": False},
                {"key": "nick_name", "label": "Nick Name", "value_type": "text", "pinned": False},
            ],
        )

        # filter by key
        response = self.fetchJSON(url, "key=nick_name")
        self.assertEqual(
            response.json()["results"],
            [{"key": "nick_name", "label": "Nick Name", "pinned": False, "value_type": "text"}],
        )

        # try to create empty field
        response = self.postJSON(url, None, {})
        self.assertResponseError(response, "label", "This field is required.")
        self.assertResponseError(response, "value_type", "This field is required.")

        # try again with some invalid values
        response = self.postJSON(url, None, {"label": "!@#$%", "value_type": "video"})
        self.assertResponseError(response, "label", "Can only contain letters, numbers and hypens.")
        self.assertResponseError(response, "value_type", '"video" is not a valid choice.')

        # try again with a label that would generate an invalid key
        response = self.postJSON(url, None, {"label": "Created By", "value_type": "user"})
        self.assertResponseError(response, "label", 'Generated key "created_by" is invalid or a reserved name.')

        # try again with a label that's already taken
        response = self.postJSON(url, None, {"label": "nick name", "value_type": "text"})
        self.assertResponseError(response, "label", "This field must be unique.")

        # create a new field
        response = self.postJSON(url, None, {"label": "Age", "value_type": "numeric"})
        self.assertEqual(response.status_code, 201)

        age = ContactField.user_fields.get(org=self.org, label="Age", value_type="N", is_active=True)

        # update a field by its key
        response = self.postJSON(url, "key=age", {"label": "Real Age", "value_type": "datetime"})
        self.assertEqual(response.status_code, 200)

        age.refresh_from_db()
        self.assertEqual(age.label, "Real Age")
        self.assertEqual(age.value_type, "D")

        # try to update with key of deleted field
        response = self.postJSON(url, "key=deleted", {"label": "Something", "value_type": "text"})
        self.assert404(response)

        # try to update with non-existent key
        response = self.postJSON(url, "key=not_ours", {"label": "Something", "value_type": "text"})
        self.assert404(response)

        ContactField.user_fields.all().delete()

        for i in range(10):
            ContactField.get_or_create(self.org, self.admin, "field%d" % i, "Field%d" % i)

        response = self.postJSON(url, None, {"label": "Age", "value_type": "numeric"})
        self.assertResponseError(
            response,
            "non_field_errors",
            "This org has 10 contact fields and the limit is 10. "
            "You must delete existing ones before you can create new ones.",
        )

    def test_flows(self):
        url = reverse("api.v2.flows")

        self.assertEndpointAccess(url)

        survey = self.get_flow("media_survey")
        color = self.get_flow("color")
        archived = self.get_flow("favorites")
        archived.archive(self.admin)

        # add a campaign message flow that should be filtered out
        Flow.create_single_message(self.org, self.admin, dict(eng="Hello world"), "eng")

        # add a flow label
        reporting = FlowLabel.objects.create(org=self.org, name="Reporting")
        color.labels.add(reporting)

        # make it look like joe completed a the color flow
        run = FlowRun.objects.create(org=self.org, flow=color, contact=self.joe)
        run.exit_type = FlowRun.EXIT_TYPE_COMPLETED
        run.exited_on = timezone.now()
        run.is_active = False
        run.save(update_fields=("exit_type", "exited_on", "modified_on", "is_active"))

        # flow belong to other org
        self.create_flow(org=self.org2, name="Other")

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 5):
            response = self.fetchJSON(url, readonly_models={Flow})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {
                    "uuid": archived.uuid,
                    "name": "Favorites",
                    "type": "message",
                    "archived": True,
                    "labels": [],
                    "expires": 720,
                    "runs": {"active": 0, "completed": 0, "interrupted": 0, "expired": 0},
                    "results": [
                        {
                            "key": "color",
                            "name": "Color",
                            "categories": ["Red", "Green", "Blue", "Cyan", "Other"],
                            "node_uuids": [matchers.UUID4String()],
                        },
                        {
                            "key": "beer",
                            "name": "Beer",
                            "categories": ["Mutzig", "Primus", "Turbo King", "Skol", "Other"],
                            "node_uuids": [matchers.UUID4String()],
                        },
                        {
                            "key": "name",
                            "name": "Name",
                            "categories": ["All Responses"],
                            "node_uuids": [matchers.UUID4String()],
                        },
                    ],
                    "parent_refs": [],
                    "created_on": format_datetime(archived.created_on),
                    "modified_on": format_datetime(archived.modified_on),
                },
                {
                    "uuid": color.uuid,
                    "name": "Color Flow",
                    "type": "message",
                    "archived": False,
                    "labels": [{"uuid": reporting.uuid, "name": "Reporting"}],
                    "expires": 10080,
                    "runs": {"active": 0, "completed": 1, "interrupted": 0, "expired": 0},
                    "results": [
                        {
                            "key": "color",
                            "name": "color",
                            "categories": ["Orange", "Blue", "Other", "Nothing"],
                            "node_uuids": [matchers.UUID4String()],
                        }
                    ],
                    "parent_refs": [],
                    "created_on": format_datetime(color.created_on),
                    "modified_on": format_datetime(color.modified_on),
                },
                {
                    "uuid": survey.uuid,
                    "name": "Media Survey",
                    "type": "survey",
                    "archived": False,
                    "labels": [],
                    "expires": 10080,
                    "runs": {"active": 0, "completed": 0, "interrupted": 0, "expired": 0},
                    "results": [
                        {
                            "key": "name",
                            "name": "Name",
                            "categories": ["All Responses"],
                            "node_uuids": [matchers.UUID4String()],
                        },
                        {
                            "key": "photo",
                            "name": "Photo",
                            "categories": ["All Responses"],
                            "node_uuids": [matchers.UUID4String()],
                        },
                        {
                            "key": "location",
                            "name": "Location",
                            "categories": ["All Responses"],
                            "node_uuids": [matchers.UUID4String()],
                        },
                        {
                            "key": "video",
                            "name": "Video",
                            "categories": ["All Responses"],
                            "node_uuids": [matchers.UUID4String()],
                        },
                    ],
                    "parent_refs": [],
                    "created_on": format_datetime(survey.created_on),
                    "modified_on": format_datetime(survey.modified_on),
                },
            ],
        )

        # filter by UUID
        response = self.fetchJSON(url, "uuid=%s" % color.uuid)
        self.assertResultsByUUID(response, [color])

        # filter by type
        response = self.fetchJSON(url, "type=message")
        self.assertResultsByUUID(response, [archived, color])

        response = self.fetchJSON(url, "type=survey")
        self.assertResultsByUUID(response, [survey])

        # filter by archived
        response = self.fetchJSON(url, "archived=1")
        self.assertResultsByUUID(response, [archived])

        response = self.fetchJSON(url, "archived=0")
        self.assertResultsByUUID(response, [color, survey])

        response = self.fetchJSON(url, "archived=false")
        self.assertResultsByUUID(response, [color, survey])

        # filter by labels
        response = self.fetchJSON(url, "labels=Reporting")
        self.assertResultsByUUID(response, [color])

        # filter by before
        response = self.fetchJSON(url, "before=%s" % format_datetime(color.modified_on))
        self.assertResultsByUUID(response, [color, survey])

        # filter by after
        response = self.fetchJSON(url, "after=%s" % format_datetime(color.modified_on))
        self.assertResultsByUUID(response, [archived, color])

        # inactive flows are never returned
        archived.is_active = False
        archived.save()

        response = self.fetchJSON(url)
        self.assertResultsByUUID(response, [color, survey])

    @override_settings(ORG_LIMIT_DEFAULTS={"globals": 3})
    def test_globals(self):
        url = reverse("api.v2.globals")
        self.assertEndpointAccess(url)

        # create some globals
        global1 = Global.get_or_create(self.org, self.admin, "org_name", "Org Name", "Acme Ltd")
        global2 = Global.get_or_create(self.org, self.admin, "access_token", "Access Token", "23464373")

        # on another org
        Global.get_or_create(self.org2, self.admin, "thingy", "Thingy", "xyz")

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 1):
            response = self.fetchJSON(url, readonly_models={Global})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {
                    "key": "access_token",
                    "name": "Access Token",
                    "value": "23464373",
                    "modified_on": format_datetime(global2.modified_on),
                },
                {
                    "key": "org_name",
                    "name": "Org Name",
                    "value": "Acme Ltd",
                    "modified_on": format_datetime(global1.modified_on),
                },
            ],
        )

        # Filter by key
        response = self.fetchJSON(url, "key=org_name")
        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {
                    "key": "org_name",
                    "name": "Org Name",
                    "value": "Acme Ltd",
                    "modified_on": format_datetime(global1.modified_on),
                }
            ],
        )

        # filter by after
        response = self.fetchJSON(url, "after=%s" % format_datetime(global1.modified_on))
        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {
                    "key": "access_token",
                    "name": "Access Token",
                    "value": "23464373",
                    "modified_on": format_datetime(global2.modified_on),
                },
                {
                    "key": "org_name",
                    "name": "Org Name",
                    "value": "Acme Ltd",
                    "modified_on": format_datetime(global1.modified_on),
                },
            ],
        )

        # filter by before
        response = self.fetchJSON(url, "before=%s" % format_datetime(global1.modified_on))
        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {
                    "key": "org_name",
                    "name": "Org Name",
                    "value": "Acme Ltd",
                    "modified_on": format_datetime(global1.modified_on),
                }
            ],
        )

        # lets change a global
        response = self.postJSON(url, "key=org_name", {"value": "Acme LLC"})
        self.assertEqual(response.status_code, 200)
        global1.refresh_from_db()
        self.assertEqual(global1.value, "Acme LLC")

        # try to create a global with no name
        response = self.postJSON(url, None, {"value": "yes"})
        self.assertResponseError(response, "non_field_errors", "Name is required when creating new global.")

        # try to create a global with invalid name
        response = self.postJSON(url, None, {"name": "!!!#$%^"})
        self.assertResponseError(response, "name", "Name contains illegal characters.")

        # try to create a global with name that creates an invalid key
        response = self.postJSON(url, None, {"name": "2cool key", "value": "23464373"})
        self.assertResponseError(response, "name", "Name creates Key that is invalid")

        # try to create a global with name that's too long
        response = self.postJSON(url, None, {"name": "x" * 37})
        self.assertResponseError(response, "name", "Ensure this field has no more than 36 characters.")

        # lets create a global via the API
        response = self.postJSON(url, None, {"name": "New Global", "value": "23464373"})
        self.assertEqual(response.status_code, 201)
        global3 = Global.objects.get(key="new_global")
        self.assertEqual(
            response.json(),
            {
                "key": "new_global",
                "name": "New Global",
                "value": "23464373",
                "modified_on": format_datetime(global3.modified_on),
            },
        )

        # try again now that we've hit the mocked limit of globals per org
        response = self.postJSON(url, None, {"name": "Website URL", "value": "http://example.com"})
        self.assertResponseError(
            response,
            "non_field_errors",
            "This org has 3 globals and the limit is 3. "
            "You must delete existing ones before you can create new ones.",
        )

    @override_settings(ORG_LIMIT_DEFAULTS={"groups": 10})
    @mock_mailroom
    def test_groups(self, mr_mocks):
        url = reverse("api.v2.groups")

        self.assertEndpointAccess(url)

        self.create_field("isdeveloper", "Is developer")
        customers = self.create_group("Customers", [self.frank])
        developers = self.create_group("Developers", query='isdeveloper = "YES"')
        ContactGroup.user_groups.filter(id=developers.id).update(status=ContactGroup.STATUS_READY)

        dynamic = self.create_group("Big Group", query='isdeveloper = "NO"')
        ContactGroup.user_groups.filter(id=dynamic.id).update(status=ContactGroup.STATUS_EVALUATING)

        # an initializing group
        ContactGroup.create_static(self.org, self.admin, "Initializing", status=ContactGroup.STATUS_INITIALIZING)

        # group belong to other org
        spammers = ContactGroup.get_or_create(self.org2, self.admin2, "Spammers")

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 2):
            response = self.fetchJSON(url, readonly_models={ContactGroup})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {
                    "uuid": dynamic.uuid,
                    "name": "Big Group",
                    "query": 'isdeveloper = "NO"',
                    "status": "evaluating",
                    "count": 0,
                },
                {
                    "uuid": developers.uuid,
                    "name": "Developers",
                    "query": 'isdeveloper = "YES"',
                    "status": "ready",
                    "count": 0,
                },
                {"uuid": customers.uuid, "name": "Customers", "query": None, "status": "ready", "count": 1},
            ],
        )

        # filter by UUID
        response = self.fetchJSON(url, "uuid=%s" % customers.uuid)
        self.assertResultsByUUID(response, [customers])

        # filter by name
        response = self.fetchJSON(url, "name=developers")
        self.assertResultsByUUID(response, [developers])

        # try to filter by both
        response = self.fetchJSON(url, "uuid=%s&name=developers" % developers.uuid)
        self.assertResponseError(response, None, "You may only specify one of the uuid, name parameters")

        # try to create empty group
        response = self.postJSON(url, None, {})
        self.assertResponseError(response, "name", "This field is required.")

        # create new group
        response = self.postJSON(url, None, {"name": "Reporters"})
        self.assertEqual(response.status_code, 201)

        reporters = ContactGroup.user_groups.get(name="Reporters")
        self.assertEqual(
            response.json(),
            {"uuid": reporters.uuid, "name": "Reporters", "query": None, "status": "ready", "count": 0},
        )

        # try to create another group with same name
        response = self.postJSON(url, None, {"name": "reporters"})
        self.assertResponseError(response, "name", "This field must be unique.")

        # it's fine if a group in another org has that name
        response = self.postJSON(url, None, {"name": "Spammers"})
        self.assertEqual(response.status_code, 201)

        # try to create a group with invalid name
        response = self.postJSON(url, None, {"name": "!!!#$%^"})
        self.assertResponseError(response, "name", "Name contains illegal characters.")

        # try to create a group with name that's too long
        response = self.postJSON(url, None, {"name": "x" * 65})
        self.assertResponseError(response, "name", "Ensure this field has no more than 64 characters.")

        # update group by UUID
        response = self.postJSON(url, "uuid=%s" % reporters.uuid, {"name": "U-Reporters"})
        self.assertEqual(response.status_code, 200)

        reporters.refresh_from_db()
        self.assertEqual(reporters.name, "U-Reporters")

        # can't update group from other org
        response = self.postJSON(url, "uuid=%s" % spammers.uuid, {"name": "Won't work"})
        self.assert404(response)

        # try an empty delete request
        response = self.deleteJSON(url, None)
        self.assertResponseError(response, None, "URL must contain one of the following parameters: uuid")

        # delete a group by UUID
        response = self.deleteJSON(url, "uuid=%s" % reporters.uuid)
        self.assertEqual(response.status_code, 204)

        reporters.refresh_from_db()
        self.assertFalse(reporters.is_active)

        # try to delete a group in another org
        response = self.deleteJSON(url, "uuid=%s" % spammers.uuid)
        self.assert404(response)

        for group in ContactGroup.user_groups.all():
            group.release(self.admin)

        for i in range(10):
            ContactGroup.create_static(self.org2, self.admin2, "group%d" % i)

        response = self.postJSON(url, None, {"name": "Reporters"})
        self.assertEqual(response.status_code, 201)

        ContactGroup.user_groups.all().delete()

        for i in range(10):
            ContactGroup.create_static(self.org, self.admin, "group%d" % i)

        response = self.postJSON(url, None, {"name": "Reporters"})
        self.assertResponseError(
            response,
            "non_field_errors",
            "This org has 10 groups and the limit is 10. "
            "You must delete existing ones before you can create new ones.",
        )

        group1 = ContactGroup.user_groups.filter(org=self.org, name="group1").first()
        response = self.deleteJSON(url, "uuid=%s" % group1.uuid)
        self.assertEqual(response.status_code, 204)

    def test_api_groups_cant_delete_with_trigger_dependency(self):
        url = reverse("api.v2.groups")
        self.login(self.admin)

        flow = self.get_flow("dependencies")
        cats = ContactGroup.user_groups.filter(name="Cat Facts").first()

        trigger = Trigger.objects.create(
            org=self.org, flow=flow, keyword="block_group", created_by=self.admin, modified_by=self.admin
        )
        trigger.groups.add(cats)

        response = self.deleteJSON(url, "uuid=%s" % cats.uuid)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": f"Group is being used by the following triggers which must be archived first: {trigger.id}"},
        )

    def test_api_groups_cant_delete_with_flow_dependency(self):
        url = reverse("api.v2.groups")
        self.login(self.admin)

        self.get_flow("dependencies")

        flow = Flow.objects.get(name="Dependencies")
        cats = ContactGroup.user_groups.filter(name="Cat Facts").first()

        response = self.deleteJSON(url, "uuid=%s" % cats.uuid)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": f"Group is being used by the following flows which must be archived first: {flow.uuid}"},
        )

    def test_api_groups_cant_delete_with_campaign_dependency(self):
        url = reverse("api.v2.groups")
        self.login(self.admin)

        customers = self.create_group("Customers", [self.frank])

        self.client.post(reverse("campaigns.campaign_create"), {"name": "Don't forget to ...", "group": customers.id})

        campaign = Campaign.objects.get()

        response = self.deleteJSON(url, f"uuid={customers.uuid}")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "detail": f"Group is being used by the following campaigns which must be archived first: {campaign.uuid}"
            },
        )

    def test_labels(self):
        url = reverse("api.v2.labels")

        self.assertEndpointAccess(url)

        important = self.create_label("Important")
        feedback = self.create_label("Feedback")

        # a deleted label
        deleted = self.create_label("Deleted")
        deleted.release(self.admin)

        # create label for other org
        spam = Label.get_or_create(self.org2, self.admin2, "Spam")

        msg = self.create_incoming_msg(self.frank, "Hello")
        important.toggle_label([msg], add=True)

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 2):
            response = self.fetchJSON(url, readonly_models={Label})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {"uuid": feedback.uuid, "name": "Feedback", "count": 0},
                {"uuid": important.uuid, "name": "Important", "count": 1},
            ],
        )

        # filter by UUID
        response = self.fetchJSON(url, "uuid=%s" % feedback.uuid)
        self.assertEqual(response.json()["results"], [{"uuid": feedback.uuid, "name": "Feedback", "count": 0}])

        # filter by name
        response = self.fetchJSON(url, "name=important")
        self.assertResultsByUUID(response, [important])

        # try to filter by both
        response = self.fetchJSON(url, "uuid=%s&name=important" % important.uuid)
        self.assertResponseError(response, None, "You may only specify one of the uuid, name parameters")

        # try to create empty label
        response = self.postJSON(url, None, {})
        self.assertResponseError(response, "name", "This field is required.")

        # create new label
        response = self.postJSON(url, None, {"name": "Interesting"})
        self.assertEqual(response.status_code, 201)

        interesting = Label.label_objects.get(name="Interesting")
        self.assertEqual(response.json(), {"uuid": interesting.uuid, "name": "Interesting", "count": 0})

        # try to create another label with same name
        response = self.postJSON(url, None, {"name": "interesting"})
        self.assertResponseError(response, "name", "This field must be unique.")

        # it's fine if a label in another org has that name
        response = self.postJSON(url, None, {"name": "Spam"})
        self.assertEqual(response.status_code, 201)

        # try to create a label with invalid name
        response = self.postJSON(url, None, {"name": "!!!#$%^"})
        self.assertResponseError(response, "name", "Name contains illegal characters.")

        # try to create a label with name that's too long
        response = self.postJSON(url, None, {"name": "x" * 65})
        self.assertResponseError(response, "name", "Ensure this field has no more than 64 characters.")

        # update label by UUID
        response = self.postJSON(url, "uuid=%s" % interesting.uuid, {"name": "More Interesting"})
        self.assertEqual(response.status_code, 200)

        interesting.refresh_from_db()
        self.assertEqual(interesting.name, "More Interesting")

        # can't update label from other org
        response = self.postJSON(url, "uuid=%s" % spam.uuid, {"name": "Won't work"})
        self.assert404(response)

        # try an empty delete request
        response = self.deleteJSON(url, None)
        self.assertResponseError(response, None, "URL must contain one of the following parameters: uuid")

        # delete a label by UUID
        response = self.deleteJSON(url, "uuid=%s" % interesting.uuid)
        self.assertEqual(response.status_code, 204)

        interesting.refresh_from_db()

        self.assertFalse(interesting.is_active)

        # try to delete a label in another org
        response = self.deleteJSON(url, "uuid=%s" % spam.uuid)
        self.assert404(response)

        # try creating a new label after reaching the limit on labels
        current_count = Label.all_objects.filter(org=self.org, is_active=True).count()
        with override_settings(ORG_LIMIT_DEFAULTS={"labels": current_count}):
            response = self.postJSON(url, None, {"name": "Interesting"})
            self.assertResponseError(
                response,
                "non_field_errors",
                "This workspace has 3 labels and the limit is 3. "
                "You must delete existing ones before you can create new ones.",
            )

    def assertMsgEqual(self, msg_json, msg, msg_type, msg_status, msg_visibility):
        self.assertEqual(
            msg_json,
            {
                "id": msg.id,
                "broadcast": msg.broadcast,
                "contact": {"uuid": msg.contact.uuid, "name": msg.contact.name},
                "urn": str(msg.contact_urn),
                "channel": {"uuid": msg.channel.uuid, "name": msg.channel.name},
                "direction": "in" if msg.direction == "I" else "out",
                "type": msg_type,
                "status": msg_status,
                "archived": msg.visibility == "A",
                "visibility": msg_visibility,
                "text": msg.text,
                "labels": [dict(name=l.name, uuid=l.uuid) for l in msg.labels.all()],
                "attachments": [{"content_type": a.content_type, "url": a.url} for a in msg.get_attachments()],
                "created_on": format_datetime(msg.created_on),
                "sent_on": format_datetime(msg.sent_on),
                "modified_on": format_datetime(msg.modified_on),
                "media": msg.attachments[0] if msg.attachments else None,
            },
        )

    def test_messages(self):
        url = reverse("api.v2.messages")

        # make sure user rights are correct
        self.assertEndpointAccess(url, "folder=inbox")

        # create some messages
        joe_msg1 = self.create_incoming_msg(self.joe, "Howdy", msg_type="F")
        frank_msg1 = self.create_incoming_msg(self.frank, "Bonjour", msg_type="I", channel=self.twitter)
        joe_msg2 = self.create_outgoing_msg(self.joe, "How are you?", status="Q")
        frank_msg2 = self.create_outgoing_msg(self.frank, "Ça va?", status="D")
        joe_msg3 = self.create_incoming_msg(
            self.joe, "Good", msg_type="F", attachments=["image/jpeg:https://example.com/test.jpg"]
        )
        frank_msg3 = self.create_incoming_msg(self.frank, "Bien", channel=self.twitter, visibility="A")
        frank_msg4 = self.create_outgoing_msg(self.frank, "Ça va?", status="F")

        # add a surveyor message (no URN etc)
        joe_msg4 = self.create_outgoing_msg(self.joe, "Surveys!", msg_type="F", surveyor=True)

        # add a deleted message
        deleted_msg = self.create_incoming_msg(self.frank, "!@$!%", visibility="D")

        # add message in other org
        self.create_incoming_msg(self.hans, "Guten tag!", channel=None)

        # label some of the messages, this will change our modified on as well for our `incoming` view
        label = self.create_label("Spam")

        # we do this in two calls so that we can predict ordering later
        label.toggle_label([frank_msg3], add=True)
        label.toggle_label([frank_msg1], add=True)
        label.toggle_label([joe_msg3], add=True)

        frank_msg1.refresh_from_db(fields=("modified_on",))
        joe_msg3.refresh_from_db(fields=("modified_on",))

        # default response is all messages sorted by created_on
        response = self.fetchJSON(url)
        self.assertResultsById(
            response, [joe_msg4, frank_msg4, frank_msg3, joe_msg3, frank_msg2, joe_msg2, frank_msg1, joe_msg1]
        )

        # filter by inbox
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 5):
            response = self.fetchJSON(url, "folder=INBOX", readonly_models={Msg})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertResultsById(response, [frank_msg1])
        self.assertMsgEqual(
            resp_json["results"][0], frank_msg1, msg_type="inbox", msg_status="handled", msg_visibility="visible"
        )

        # filter by incoming, should get deleted messages too
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 5):
            response = self.fetchJSON(url, "folder=incoming")

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertResultsById(response, [joe_msg3, frank_msg1, frank_msg3, deleted_msg, joe_msg1])
        self.assertMsgEqual(
            resp_json["results"][0], joe_msg3, msg_type="flow", msg_status="handled", msg_visibility="visible"
        )

        # filter by folder (flow)
        response = self.fetchJSON(url, "folder=flows")
        self.assertResultsById(response, [joe_msg3, joe_msg1])

        # filter by folder (archived)
        response = self.fetchJSON(url, "folder=archived")
        self.assertResultsById(response, [frank_msg3])

        # filter by folder (outbox)
        response = self.fetchJSON(url, "folder=outbox")
        self.assertResultsById(response, [joe_msg2])

        # filter by folder (sent)
        response = self.fetchJSON(url, "folder=sent")
        self.assertResultsById(response, [joe_msg4, frank_msg2])

        # filter by folder (failed)
        response = self.fetchJSON(url, "folder=failed")
        self.assertResultsById(response, [frank_msg4])

        # filter by invalid view
        response = self.fetchJSON(url, "folder=invalid")
        self.assertResultsById(response, [])

        # filter by id
        response = self.fetchJSON(url, "id=%d" % joe_msg3.pk)
        self.assertResultsById(response, [joe_msg3])

        # filter by contact
        response = self.fetchJSON(url, "contact=%s" % self.joe.uuid)
        self.assertResultsById(response, [joe_msg4, joe_msg3, joe_msg2, joe_msg1])

        # filter by invalid contact
        response = self.fetchJSON(url, "contact=invalid")
        self.assertResultsById(response, [])

        # filter by label name
        response = self.fetchJSON(url, "label=Spam")
        self.assertResultsById(response, [joe_msg3, frank_msg1])

        # filter by label UUID
        response = self.fetchJSON(url, "label=%s" % label.uuid)
        self.assertResultsById(response, [joe_msg3, frank_msg1])

        # filter by invalid label
        response = self.fetchJSON(url, "label=invalid")
        self.assertResultsById(response, [])

        # filter by before (inclusive)
        response = self.fetchJSON(url, "folder=incoming&before=%s" % format_datetime(frank_msg1.modified_on))
        self.assertResultsById(response, [frank_msg1, frank_msg3, deleted_msg, joe_msg1])

        # filter by after (inclusive)
        response = self.fetchJSON(url, "folder=incoming&after=%s" % format_datetime(frank_msg1.modified_on))
        self.assertResultsById(response, [joe_msg3, frank_msg1])

        # filter by broadcast
        broadcast = self.create_broadcast(self.user, "A beautiful broadcast", contacts=[self.joe, self.frank])
        response = self.fetchJSON(url, "broadcast=%s" % broadcast.id)

        expected = {m.pk for m in broadcast.msgs.all()}
        results = {m["id"] for m in response.json()["results"]}
        self.assertEqual(expected, results)

        # can't filter with invalid id
        response = self.fetchJSON(url, "id=xyz")
        self.assertResponseError(response, None, "Value for id must be an integer")

        # can't filter by more than one of contact, folder, label or broadcast together
        for query in (
            "contact=%s&label=Spam" % self.joe.uuid,
            "label=Spam&folder=inbox",
            "broadcast=12345&folder=inbox",
            "broadcast=12345&label=Spam",
        ):
            response = self.fetchJSON(url, query)
            self.assertResponseError(
                response, None, "You may only specify one of the contact, folder, label, broadcast parameters"
            )

        with AnonymousOrg(self.org):
            # for anon orgs, don't return URN values
            response = self.fetchJSON(url, "id=%d" % joe_msg3.pk)
            self.assertIsNone(response.json()["results"][0]["urn"])

    def test_workspace(self):
        url = reverse("api.v2.workspace")
        self.assertEndpointAccess(url)

        # fetch as JSON
        response = self.fetchJSON(url)
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            response.json(),
            {
                "uuid": str(self.org.uuid),
                "name": "Temba",
                "country": "RW",
                "languages": [],
                "primary_language": None,
                "timezone": "Africa/Kigali",
                "date_style": "day_first",
                "anon": False,
            },
        )

        self.org.set_flow_languages(self.admin, ["eng", "fra"])

        response = self.fetchJSON(url)
        self.assertEqual(
            response.json(),
            {
                "uuid": str(self.org.uuid),
                "name": "Temba",
                "country": "RW",
                "languages": ["eng", "fra"],
                "primary_language": "eng",
                "timezone": "Africa/Kigali",
                "date_style": "day_first",
                "anon": False,
            },
        )

    def test_media(self):
        url = reverse("api.v2.media") + ".json"

        self.login(self.admin)

        def assert_media_upload(filename, ext):
            with open(filename, "rb") as data:
                post_data = dict(media_file=data, extension=ext, HTTP_X_FORWARDED_HTTPS="https")
                response = self.client.post(url, post_data)

                self.assertEqual(response.status_code, 201)
                location = response.json().get("location", None)
                self.assertIsNotNone(location)

                starts_with = f"{settings.STORAGE_URL}/{settings.STORAGE_ROOT_DIR}/{self.org.id}/media/"
                self.assertEqual(starts_with, location[0 : len(starts_with)])
                self.assertEqual(".%s" % ext, location[-4:])

        assert_media_upload("%s/test_media/steve.marten.jpg" % settings.MEDIA_ROOT, "jpg")
        assert_media_upload("%s/test_media/snow.mp4" % settings.MEDIA_ROOT, "mp4")

        # missing file
        response = self.client.post(url, dict(), HTTP_X_FORWARDED_HTTPS="https")
        self.assertEqual(response.status_code, 400)
        self.clear_storage()

    def test_runs(self):
        url = reverse("api.v2.runs")

        self.assertEndpointAccess(url)

        flow1 = self.get_flow("color_v13")
        flow2 = Flow.copy(flow1, self.user)

        flow1_nodes = flow1.get_definition()["nodes"]
        color_prompt = flow1_nodes[0]
        color_split = flow1_nodes[4]
        blue_reply = flow1_nodes[2]

        start1 = FlowStart.create(flow1, self.admin, contacts=[self.joe], restart_participants=True)
        joe_msg = self.create_incoming_msg(self.joe, "it is blue")
        frank_msg = self.create_incoming_msg(self.frank, "Indigo")

        joe_run1 = (
            MockSessionWriter(self.joe, flow1, start=start1)
            .visit(color_prompt)
            .visit(color_split)
            .wait()
            .resume(msg=joe_msg)
            .set_result("Color", "blue", "Blue", "it is blue")
            .visit(blue_reply)
            .complete()
            .save()
        ).session.runs.get()

        frank_run1 = (
            MockSessionWriter(self.frank, flow1)
            .visit(color_prompt)
            .visit(color_split)
            .wait()
            .resume(msg=frank_msg)
            .set_result("Color", "Indigo", "Other", "Indigo")
            .wait()
            .save()
        ).session.runs.get()

        joe_run2 = (
            MockSessionWriter(self.joe, flow1).visit(color_prompt).visit(color_split).wait().save()
        ).session.runs.get()
        frank_run2 = (
            MockSessionWriter(self.frank, flow1).visit(color_prompt).visit(color_split).wait().save()
        ).session.runs.get()

        joe_run3 = MockSessionWriter(self.joe, flow2).wait().save().session.runs.get()

        # add a run for another org
        flow3 = self.create_flow(org=self.org2)
        MockSessionWriter(self.hans, flow3).wait().save()

        # refresh runs which will have been modified by being interrupted
        joe_run1.refresh_from_db()
        joe_run2.refresh_from_db()
        frank_run1.refresh_from_db()
        frank_run2.refresh_from_db()

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 5):
            response = self.fetchJSON(url, readonly_models={FlowRun})

        self.assertEqual(200, response.status_code)
        self.assertEqual(None, response.json()["next"])
        self.assertResultsById(response, [joe_run3, joe_run2, frank_run2, frank_run1, joe_run1])

        resp_json = response.json()
        self.assertEqual(
            {
                "id": frank_run2.pk,
                "uuid": str(frank_run2.uuid),
                "flow": {"uuid": flow1.uuid, "name": "Colors"},
                "contact": {"uuid": self.frank.uuid, "urn": "twitter:franky", "name": self.frank.name},
                "start": None,
                "responded": False,
                "path": [
                    {
                        "node": color_prompt["uuid"],
                        "time": format_datetime(iso8601.parse_date(frank_run2.path[0]["arrived_on"])),
                    },
                    {
                        "node": color_split["uuid"],
                        "time": format_datetime(iso8601.parse_date(frank_run2.path[1]["arrived_on"])),
                    },
                ],
                "values": {},
                "created_on": format_datetime(frank_run2.created_on),
                "modified_on": format_datetime(frank_run2.modified_on),
                "exited_on": None,
                "exit_type": None,
            },
            resp_json["results"][2],
        )
        self.assertEqual(
            {
                "id": joe_run1.pk,
                "uuid": str(joe_run1.uuid),
                "flow": {"uuid": flow1.uuid, "name": "Colors"},
                "contact": {"uuid": self.joe.uuid, "urn": "tel:+250788123123", "name": self.joe.name},
                "start": {"uuid": str(joe_run1.start.uuid)},
                "responded": True,
                "path": [
                    {
                        "node": color_prompt["uuid"],
                        "time": format_datetime(iso8601.parse_date(joe_run1.path[0]["arrived_on"])),
                    },
                    {
                        "node": color_split["uuid"],
                        "time": format_datetime(iso8601.parse_date(joe_run1.path[1]["arrived_on"])),
                    },
                    {
                        "node": blue_reply["uuid"],
                        "time": format_datetime(iso8601.parse_date(joe_run1.path[2]["arrived_on"])),
                    },
                ],
                "values": {
                    "color": {
                        "value": "blue",
                        "category": "Blue",
                        "node": color_split["uuid"],
                        "time": format_datetime(iso8601.parse_date(joe_run1.results["color"]["created_on"])),
                        "name": "Color",
                        "input": "it is blue",
                    }
                },
                "created_on": format_datetime(joe_run1.created_on),
                "modified_on": format_datetime(joe_run1.modified_on),
                "exited_on": format_datetime(joe_run1.exited_on),
                "exit_type": "completed",
            },
            resp_json["results"][4],
        )

        # reversed
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 5):
            response = self.fetchJSON(url, "reverse=true")

        self.assertEqual(200, response.status_code)
        self.assertEqual(None, response.json()["next"])
        self.assertResultsById(response, [joe_run1, frank_run1, frank_run2, joe_run2, joe_run3])

        # filter by id
        response = self.fetchJSON(url, "id=%d" % frank_run2.pk)
        self.assertResultsById(response, [frank_run2])

        # anon orgs should not have a URN field
        with AnonymousOrg(self.org):
            response = self.fetchJSON(url, "id=%d" % frank_run2.pk)
            self.assertResultsById(response, [frank_run2])
            self.assertEqual(
                {
                    "id": frank_run2.pk,
                    "uuid": str(frank_run2.uuid),
                    "flow": {"uuid": flow1.uuid, "name": "Colors"},
                    "contact": {"uuid": self.frank.uuid, "name": self.frank.name},
                    "start": None,
                    "responded": False,
                    "path": [
                        {
                            "node": color_prompt["uuid"],
                            "time": format_datetime(iso8601.parse_date(frank_run2.path[0]["arrived_on"])),
                        },
                        {
                            "node": color_split["uuid"],
                            "time": format_datetime(iso8601.parse_date(frank_run2.path[1]["arrived_on"])),
                        },
                    ],
                    "values": {},
                    "created_on": format_datetime(frank_run2.created_on),
                    "modified_on": format_datetime(frank_run2.modified_on),
                    "exited_on": None,
                    "exit_type": None,
                },
                response.json()["results"][0],
            )

        # filter by uuid
        response = self.fetchJSON(url, "uuid=%s" % frank_run2.uuid)
        self.assertResultsById(response, [frank_run2])

        # filter by mismatching id and uuid
        response = self.fetchJSON(url, "uuid=%s&id=%d" % (frank_run2.uuid, joe_run1.pk))
        self.assertResultsById(response, [])

        response = self.fetchJSON(url, "uuid=%s&id=%d" % (frank_run2.uuid, frank_run2.pk))
        self.assertResultsById(response, [frank_run2])

        # filter by flow
        response = self.fetchJSON(url, "flow=%s" % flow1.uuid)
        self.assertResultsById(response, [joe_run2, frank_run2, frank_run1, joe_run1])

        # doesn't work if flow is inactive
        flow1.is_active = False
        flow1.save()

        response = self.fetchJSON(url, "flow=%s" % flow1.uuid)
        self.assertResultsById(response, [])

        # restore to active
        flow1.is_active = True
        flow1.save()

        # filter by invalid flow
        response = self.fetchJSON(url, "flow=invalid")
        self.assertResultsById(response, [])

        # filter by flow + responded
        response = self.fetchJSON(url, "flow=%s&responded=TrUe" % flow1.uuid)
        self.assertResultsById(response, [frank_run1, joe_run1])

        # filter by contact
        response = self.fetchJSON(url, "contact=%s" % self.joe.uuid)
        self.assertResultsById(response, [joe_run3, joe_run2, joe_run1])

        # filter by invalid contact
        response = self.fetchJSON(url, "contact=invalid")
        self.assertResultsById(response, [])

        # filter by contact + responded
        response = self.fetchJSON(url, "contact=%s&responded=yes" % self.joe.uuid)
        self.assertResultsById(response, [joe_run1])

        # filter by after
        response = self.fetchJSON(url, "after=%s" % format_datetime(frank_run1.modified_on))
        self.assertResultsById(response, [joe_run3, joe_run2, frank_run2, frank_run1])

        # filter by before
        response = self.fetchJSON(url, "before=%s" % format_datetime(frank_run1.modified_on))
        self.assertResultsById(response, [frank_run1, joe_run1])

        # filter by invalid before
        response = self.fetchJSON(url, "before=longago")
        self.assertResultsById(response, [])

        # filter by invalid after
        response = self.fetchJSON(url, "before=%s&after=thefuture" % format_datetime(frank_run1.modified_on))
        self.assertResultsById(response, [])

        # can't filter by both contact and flow together
        response = self.fetchJSON(url, "contact=%s&flow=%s" % (self.joe.uuid, flow1.uuid))
        self.assertResponseError(response, None, "You may only specify one of the contact, flow parameters")

    def test_runs_with_action_results(self):
        """
        Runs from save_run_result actions may have some fields missing
        """

        url = reverse("api.v2.runs")
        self.assertEndpointAccess(url)

        flow = self.get_flow("color")
        run = FlowRun.objects.create(org=self.org, flow=flow, contact=self.frank)
        run.results = {
            "manual": {
                "created_on": "2019-06-28T06:37:02.628152471Z",
                "name": "Manual",
                "node_uuid": "6edeb849-1f65-4038-95dc-4d99d7dde6b8",
                "value": "",
            }
        }
        run.save(update_fields=("results",))

        response = self.fetchJSON(url)

        resp_json = response.json()
        self.assertEqual(
            resp_json["results"][0]["values"],
            {
                "manual": {
                    "name": "Manual",
                    "value": "",
                    "input": None,
                    "category": None,
                    "node": "6edeb849-1f65-4038-95dc-4d99d7dde6b8",
                    "time": "2019-06-28T06:37:02.628152Z",
                }
            },
        )

    def test_message_actions(self):
        url = reverse("api.v2.message_actions")
        self.assertEndpointAccess(url, fetch_returns=405)

        # create some messages to act on
        msg1 = self.create_incoming_msg(self.joe, "Msg #1")
        msg2 = self.create_incoming_msg(self.joe, "Msg #2")
        msg3 = self.create_incoming_msg(self.joe, "Msg #3")
        label = Label.get_or_create(self.org, self.admin, "Test")

        # add label by name to messages 1 and 2
        response = self.postJSON(url, None, {"messages": [msg1.id, msg2.id], "action": "label", "label": "Test"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(label.get_messages()), {msg1, msg2})

        # add label by its UUID to message 3
        response = self.postJSON(url, None, {"messages": [msg3.id], "action": "label", "label": label.uuid})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(label.get_messages()), {msg1, msg2, msg3})

        # try to label with an invalid UUID
        response = self.postJSON(url, None, {"messages": [msg1.id], "action": "label", "label": "nope"})
        self.assertResponseError(response, "label", "No such object: nope")

        # remove label from message 2 by name (which is case-insensitive)
        response = self.postJSON(url, None, {"messages": [msg2.id], "action": "unlabel", "label": "test"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(label.get_messages()), {msg1, msg3})

        # and remove from messages 1 and 3 by UUID
        response = self.postJSON(url, None, {"messages": [msg1.id, msg3.id], "action": "unlabel", "label": label.uuid})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(label.get_messages()), set())

        # add new label via label_name
        response = self.postJSON(url, None, {"messages": [msg2.id, msg3.id], "action": "label", "label_name": "New"})
        self.assertEqual(response.status_code, 204)

        new_label = Label.all_objects.get(org=self.org, name="New", is_active=True)
        self.assertEqual(set(new_label.get_messages()), {msg2, msg3})

        # no difference if label already exists as it does now
        response = self.postJSON(url, None, {"messages": [msg1.id], "action": "label", "label_name": "New"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(new_label.get_messages()), {msg1, msg2, msg3})

        # can also remove by label_name
        response = self.postJSON(url, None, {"messages": [msg3.id], "action": "unlabel", "label_name": "New"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(new_label.get_messages()), {msg1, msg2})

        # and no error if label doesn't exist
        response = self.postJSON(url, None, {"messages": [msg3.id], "action": "unlabel", "label_name": "XYZ"})
        self.assertEqual(response.status_code, 204)

        # and label not lazy created in this case
        self.assertIsNone(Label.all_objects.filter(name="XYZ").first())

        # try to use invalid label name
        response = self.postJSON(url, None, {"messages": [msg1.id, msg2.id], "action": "label", "label_name": "$$$"})
        self.assertResponseError(response, "label_name", "Name contains illegal characters.")

        # try to label without specifying a label
        response = self.postJSON(url, None, {"messages": [msg1.id, msg2.id], "action": "label"})
        self.assertResponseError(response, "non_field_errors", 'For action "label" you should also specify a label')
        response = self.postJSON(url, None, {"messages": [msg1.id, msg2.id], "action": "label", "label": ""})
        self.assertResponseError(response, "label", "This field may not be null.")

        # try to provide both label and label_name
        response = self.postJSON(
            url, None, {"messages": [msg1.id], "action": "label", "label": "Test", "label_name": "Test"}
        )
        self.assertResponseError(response, "non_field_errors", "Can't specify both label and label_name.")

        # archive all messages
        response = self.postJSON(url, None, {"messages": [msg1.id, msg2.id, msg3.id], "action": "archive"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(Msg.objects.filter(visibility=Msg.VISIBILITY_ARCHIVED)), {msg1, msg2, msg3})

        # restore message 1
        response = self.postJSON(url, None, {"messages": [msg1.id], "action": "restore"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(Msg.objects.filter(visibility=Msg.VISIBILITY_VISIBLE)), {msg1})
        self.assertEqual(set(Msg.objects.filter(visibility=Msg.VISIBILITY_ARCHIVED)), {msg2, msg3})

        # delete messages 2
        response = self.postJSON(url, None, {"messages": [msg2.id], "action": "delete"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(set(Msg.objects.filter(visibility=Msg.VISIBILITY_VISIBLE)), {msg1})
        self.assertEqual(set(Msg.objects.filter(visibility=Msg.VISIBILITY_ARCHIVED)), {msg3})
        self.assertFalse(Msg.objects.filter(id=msg2.id).exists())

        # try to act on a a valid message and a deleted message
        response = self.postJSON(url, None, {"messages": [msg2.id, msg3.id], "action": "restore"})

        # should get a partial success
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"failures": [msg2.id]})
        self.assertEqual(set(Msg.objects.filter(visibility=Msg.VISIBILITY_VISIBLE)), {msg1, msg3})

        # try to act on an outgoing message
        msg4 = self.create_outgoing_msg(self.joe, "Hi Joe")
        response = self.postJSON(url, None, {"messages": [msg1.id, msg4.id], "action": "archive"})
        self.assertResponseError(response, "messages", "Not an incoming message: %d" % msg4.id)

        # try to provide a label for a non-labelling action
        response = self.postJSON(url, None, {"messages": [msg1.id], "action": "archive", "label": "Test"})
        self.assertResponseError(response, "non_field_errors", 'For action "archive" you should not specify a label')

        # try to invoke an invalid action
        response = self.postJSON(url, None, {"messages": [msg1.id], "action": "like"})
        self.assertResponseError(response, "action", '"like" is not a valid choice.')

    def test_resthooks(self):
        url = reverse("api.v2.resthooks")
        self.assertEndpointAccess(url)

        # create some resthooks
        resthook1 = Resthook.get_or_create(self.org, "new-mother", self.admin)
        resthook2 = Resthook.get_or_create(self.org, "new-father", self.admin)
        resthook3 = Resthook.get_or_create(self.org, "not-active", self.admin)
        resthook3.is_active = False
        resthook3.save()

        # create a resthook for another org
        other_org_resthook = Resthook.get_or_create(self.org2, "spam", self.admin2)

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 1):
            response = self.fetchJSON(url, readonly_models={Resthook})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {
                    "resthook": "new-father",
                    "created_on": format_datetime(resthook2.created_on),
                    "modified_on": format_datetime(resthook2.modified_on),
                },
                {
                    "resthook": "new-mother",
                    "created_on": format_datetime(resthook1.created_on),
                    "modified_on": format_datetime(resthook1.modified_on),
                },
            ],
        )

        # ok, let's look at subscriptions
        url = reverse("api.v2.resthook_subscribers")
        self.assertEndpointAccess(url)

        # try to create empty subscription
        response = self.postJSON(url, None, {})
        self.assertResponseError(response, "resthook", "This field is required.")
        self.assertResponseError(response, "target_url", "This field is required.")

        # try to create one for resthook in other org
        response = self.postJSON(url, None, dict(resthook="spam", target_url="https://foo.bar/"))
        self.assertResponseError(response, "resthook", "No resthook with slug: spam")

        # create subscribers on each resthook
        response = self.postJSON(url, None, dict(resthook="new-mother", target_url="https://foo.bar/mothers"))
        self.assertEqual(response.status_code, 201)
        response = self.postJSON(url, None, dict(resthook="new-father", target_url="https://foo.bar/fathers"))
        self.assertEqual(response.status_code, 201)

        hook1_subscriber = resthook1.subscribers.get()
        hook2_subscriber = resthook2.subscribers.get()

        self.assertEqual(
            response.json(),
            {
                "id": hook2_subscriber.id,
                "resthook": "new-father",
                "target_url": "https://foo.bar/fathers",
                "created_on": format_datetime(hook2_subscriber.created_on),
            },
        )

        # create a subscriber on our other resthook
        other_org_subscriber = other_org_resthook.add_subscriber("https://bar.foo", self.admin2)

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 1):
            response = self.fetchJSON(url)

        self.assertEqual(
            response.json()["results"],
            [
                {
                    "id": hook2_subscriber.id,
                    "resthook": "new-father",
                    "target_url": "https://foo.bar/fathers",
                    "created_on": format_datetime(hook2_subscriber.created_on),
                },
                {
                    "id": hook1_subscriber.id,
                    "resthook": "new-mother",
                    "target_url": "https://foo.bar/mothers",
                    "created_on": format_datetime(hook1_subscriber.created_on),
                },
            ],
        )

        # filter by id
        response = self.fetchJSON(url, "id=%d" % hook1_subscriber.id)
        self.assertResultsById(response, [hook1_subscriber])

        # filter by resthook
        response = self.fetchJSON(url, "resthook=new-father")
        self.assertResultsById(response, [hook2_subscriber])

        # remove a subscriber
        response = self.deleteJSON(url, "id=%d" % hook2_subscriber.id)
        self.assertEqual(response.status_code, 204)

        # subscriber should no longer be active
        hook2_subscriber.refresh_from_db()
        self.assertFalse(hook2_subscriber.is_active)

        # try to delete without providing id
        response = self.deleteJSON(url, "")
        self.assertResponseError(response, None, "URL must contain one of the following parameters: id")

        # try to delete a subscriber from another org
        response = self.deleteJSON(url, "id=%d" % other_org_subscriber.id)
        self.assert404(response)

        # ok, let's look at the events on this resthook
        url = reverse("api.v2.resthook_events")
        self.assertEndpointAccess(url)

        # create some events on our resthooks
        event1 = WebHookEvent.objects.create(
            org=self.org,
            resthook=resthook1,
            data={"event": "new mother", "values": {"name": "Greg"}, "steps": {"uuid": "abcde"}},
        )
        event2 = WebHookEvent.objects.create(
            org=self.org,
            resthook=resthook2,
            data={"event": "new father", "values": {"name": "Yo"}, "steps": {"uuid": "12345"}},
        )

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 1):
            response = self.fetchJSON(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"],
            [
                {
                    "resthook": "new-father",
                    "created_on": format_datetime(event2.created_on),
                    "data": {"event": "new father", "values": {"name": "Yo"}, "steps": {"uuid": "12345"}},
                },
                {
                    "resthook": "new-mother",
                    "created_on": format_datetime(event1.created_on),
                    "data": {"event": "new mother", "values": {"name": "Greg"}, "steps": {"uuid": "abcde"}},
                },
            ],
        )

    @patch("temba.flows.models.FlowStart.async_start")
    def test_flow_starts(self, mock_async_start):
        url = reverse("api.v2.flow_starts")
        self.assertEndpointAccess(url)

        flow = self.get_flow("favorites_v13")

        # try to create an empty flow start
        response = self.postJSON(url, None, {})
        self.assertResponseError(response, "flow", "This field is required.")

        # start a flow with the minimum required parameters
        response = self.postJSON(url, None, {"flow": flow.uuid, "contacts": [self.joe.uuid]})
        self.assertEqual(response.status_code, 201)

        start1 = flow.starts.get(pk=response.json()["id"])
        self.assertEqual(start1.flow, flow)
        self.assertEqual(set(start1.contacts.all()), {self.joe})
        self.assertEqual(set(start1.groups.all()), set())
        self.assertTrue(start1.restart_participants)
        self.assertEqual(start1.extra, {})

        # check we tried to start the new flow start
        mock_async_start.assert_called_once()
        mock_async_start.reset_mock()

        # start a flow with all parameters
        hans_group = self.create_group("hans", contacts=[self.hans])
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["tel:+12067791212"],
                "contacts": [self.joe.uuid],
                "groups": [hans_group.uuid],
                "flow": flow.uuid,
                "restart_participants": False,
                "extra": {"first_name": "Ryan", "last_name": "Lewis"},
            },
        )

        self.assertEqual(response.status_code, 201)

        # assert our new start
        start2 = flow.starts.get(id=response.json()["id"])
        self.assertEqual(start2.flow, flow)
        self.assertEqual(start2.start_type, FlowStart.TYPE_API)
        self.assertEqual(["tel:+12067791212"], start2.urns)
        self.assertEqual({self.joe}, set(start2.contacts.all()))
        self.assertEqual({hans_group}, set(start2.groups.all()))
        self.assertFalse(start2.restart_participants)
        self.assertTrue(start2.extra, {"first_name": "Ryan", "last_name": "Lewis"})

        # check we tried to start the new flow start
        mock_async_start.assert_called_once()
        mock_async_start.reset_mock()

        response = self.postJSON(
            url,
            None,
            {
                "urns": ["tel:+12067791212"],
                "contacts": [self.joe.uuid],
                "groups": [hans_group.uuid],
                "flow": flow.uuid,
                "restart_participants": False,
                "extra": {"first_name": "Ryan", "last_name": "Lewis"},
                "params": {"first_name": "Bob", "last_name": "Marley"},
            },
        )

        self.assertEqual(response.status_code, 201)

        # assert our new start
        start3 = flow.starts.get(pk=response.json()["id"])
        self.assertEqual(start3.flow, flow)
        self.assertEqual(["tel:+12067791212"], start3.urns)
        self.assertEqual({self.joe}, set(start3.contacts.all()))
        self.assertEqual({hans_group}, set(start3.groups.all()))
        self.assertFalse(start3.restart_participants)
        self.assertTrue(start3.include_active)
        self.assertTrue(start3.extra, {"first_name": "Bob", "last_name": "Marley"})

        # check we tried to start the new flow start
        mock_async_start.assert_called_once()
        mock_async_start.reset_mock()

        # calls from Zapier have user-agent set to Zapier
        response = self.postJSON(url, None, {"contacts": [self.joe.uuid], "flow": flow.uuid}, HTTP_USER_AGENT="Zapier")

        self.assertEqual(response.status_code, 201)

        # assert our new start has start_type of Zapier
        start4 = flow.starts.get(id=response.json()["id"])
        self.assertEqual(FlowStart.TYPE_API_ZAPIER, start4.start_type)

        # try to start a flow with no contact/group/URN
        response = self.postJSON(url, None, {"flow": flow.uuid, "restart_participants": True})
        self.assertResponseError(response, "non_field_errors", "Must specify at least one group, contact or URN")

        # should raise validation error for invalid JSON in extra
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["tel:+12067791212"],
                "contacts": [self.joe.uuid],
                "groups": [hans_group.uuid],
                "flow": flow.uuid,
                "restart_participants": False,
                "extra": "YES",
            },
        )

        self.assertResponseError(response, "extra", "Must be a valid JSON object")

        # a list is valid JSON, but extra has to be a dict
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["tel:+12067791212"],
                "contacts": [self.joe.uuid],
                "groups": [hans_group.uuid],
                "flow": flow.uuid,
                "restart_participants": False,
                "extra": [1],
            },
        )

        self.assertResponseError(response, "extra", "Must be a valid JSON object")

        response = self.postJSON(
            url,
            None,
            {
                "urns": ["tel:+12067791212"],
                "contacts": [self.joe.uuid],
                "groups": [hans_group.uuid],
                "flow": flow.uuid,
                "restart_participants": False,
                "params": "YES",
            },
        )

        self.assertResponseError(response, "params", "Must be a valid JSON object")

        # a list is valid JSON, but extra has to be a dict
        response = self.postJSON(
            url,
            None,
            {
                "urns": ["tel:+12067791212"],
                "contacts": [self.joe.uuid],
                "groups": [hans_group.uuid],
                "flow": flow.uuid,
                "restart_participants": False,
                "params": [1],
            },
        )

        self.assertResponseError(response, "params", "Must be a valid JSON object")

        # invalid URN
        response = self.postJSON(
            url, None, dict(flow=flow.uuid, restart_participants=True, urns=["foo:bar"], contacts=[self.joe.uuid])
        )
        self.assertEqual(response.status_code, 400)

        # invalid contact uuid
        response = self.postJSON(
            url, None, dict(flow=flow.uuid, restart_participants=True, urns=["tel:+12067791212"], contacts=["abcde"])
        )
        self.assertEqual(response.status_code, 400)

        # invalid group uuid
        response = self.postJSON(
            url, None, dict(flow=flow.uuid, restart_participants=True, urns=["tel:+12067791212"], groups=["abcde"])
        )
        self.assertResponseError(response, "groups", "No such object: abcde")

        # invalid flow uuid
        response = self.postJSON(url, None, dict(flow="abcde", restart_participants=True, urns=["tel:+12067791212"]))
        self.assertResponseError(response, "flow", "No such object: abcde")

        # too many groups
        group_uuids = []
        for g in range(101):
            group_uuids.append(self.create_group("Group %d" % g).uuid)

        response = self.postJSON(url, None, dict(flow=flow.uuid, restart_participants=True, groups=group_uuids))
        self.assertResponseError(response, "groups", "This field can only contain up to 100 items.")

        # check no params
        response = self.fetchJSON(url, readonly_models={FlowStart})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["next"], None)
        self.assertResultsById(response, [start4, start3, start2, start1])
        self.assertEqual(
            response.json()["results"][1],
            {
                "id": start3.id,
                "uuid": str(start3.uuid),
                "flow": {"uuid": flow.uuid, "name": "Favorites"},
                "contacts": [{"uuid": self.joe.uuid, "name": "Joe Blow"}],
                "groups": [{"uuid": hans_group.uuid, "name": "hans"}],
                "restart_participants": False,
                "exclude_active": False,
                "status": "pending",
                "extra": {"first_name": "Bob", "last_name": "Marley"},
                "params": {"first_name": "Bob", "last_name": "Marley"},
                "created_on": format_datetime(start3.created_on),
                "modified_on": format_datetime(start3.modified_on),
            },
        )

        # check filtering by UUID
        response = self.fetchJSON(url, "uuid=%s" % str(start2.uuid))
        self.assertResultsById(response, [start2])

        # check filtering by in invalid UUID
        response = self.fetchJSON(url, "uuid=xyz")
        self.assertResponseError(response, None, "Value for uuid must be a valid UUID")

        # check filtering by id (deprecated)
        response = self.fetchJSON(url, "id=%d" % start2.id)
        self.assertResultsById(response, [start2])

        response = self.postJSON(
            url,
            None,
            {
                "urns": ["tel:+12067791212"],
                "contacts": [self.joe.uuid],
                "groups": [hans_group.uuid],
                "flow": flow.uuid,
                "restart_participants": True,
                "exclude_active": False,
                "extra": {"first_name": "Ryan", "last_name": "Lewis"},
                "params": {"first_name": "Bob", "last_name": "Marley"},
            },
        )

        self.assertEqual(response.status_code, 201)

        start4 = flow.starts.get(pk=response.json()["id"])
        self.assertTrue(start4.restart_participants)
        self.assertTrue(start4.include_active)

        response = self.postJSON(
            url,
            None,
            {
                "urns": ["tel:+12067791212"],
                "contacts": [self.joe.uuid],
                "groups": [hans_group.uuid],
                "flow": flow.uuid,
                "restart_participants": True,
                "exclude_active": True,
                "extra": {"first_name": "Ryan", "last_name": "Lewis"},
                "params": {"first_name": "Bob", "last_name": "Marley"},
            },
        )

        self.assertEqual(response.status_code, 201)

        start5 = flow.starts.get(pk=response.json()["id"])
        self.assertTrue(start5.restart_participants)
        self.assertFalse(start5.include_active)

        query = f"flow={flow.uuid}&groups={hans_group.uuid}"

        response = self.postJSON(
            url,
            query,
            {},
        )
        self.assertEqual(response.status_code, 201)

    def test_templates(self):
        url = reverse("api.v2.templates")
        self.assertEndpointAccess(url)

        # create some templates
        TemplateTranslation.get_or_create(
            self.channel,
            "hello",
            "eng",
            "US",
            "Hi {{1}}",
            1,
            TemplateTranslation.STATUS_APPROVED,
            "1234",
            "foo_namespace",
            "AUTHENTICATION",
        )
        TemplateTranslation.get_or_create(
            self.channel,
            "hello",
            "fra",
            "FR",
            "Bonjour {{1}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "5678",
            "foo_namespace",
            "AUTHENTICATION",
        )
        tt = TemplateTranslation.get_or_create(
            self.channel,
            "hello",
            "afr",
            "ZA",
            "This is a template translation for a deleted channel {{1}}",
            1,
            TemplateTranslation.STATUS_APPROVED,
            "9012",
            "foo_namespace",
            "AUTHENTICATION",
        )
        tt.is_active = False
        tt.save()

        # templates on other org to test filtering
        TemplateTranslation.get_or_create(
            self.org2channel,
            "goodbye",
            "eng",
            "US",
            "Goodbye {{1}}",
            1,
            TemplateTranslation.STATUS_APPROVED,
            "1234",
            "bar_namespace",
            "AUTHENTICATION",
        )
        TemplateTranslation.get_or_create(
            self.org2channel,
            "goodbye",
            "fra",
            "FR",
            "Salut {{1}}",
            1,
            TemplateTranslation.STATUS_PENDING,
            "5678",
            "bar_namespace",
            "AUTHENTICATION",
        )

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 3):
            response = self.fetchJSON(url, readonly_models={Template})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)

    def test_classifiers(self):
        url = reverse("api.v2.classifiers")
        self.assertEndpointAccess(url)

        # create some classifiers
        c1 = Classifier.create(self.org, self.admin, WitType.slug, "Booker", {})
        c1.intents.create(name="book_flight", external_id="book_flight", created_on=timezone.now(), is_active=True)
        c1.intents.create(name="book_hotel", external_id="book_hotel", created_on=timezone.now(), is_active=False)
        c1.intents.create(name="book_car", external_id="book_car", created_on=timezone.now(), is_active=True)

        c2 = Classifier.create(self.org, self.admin, WitType.slug, "Old Booker", {})
        c2.is_active = False
        c2.save()

        # on another org
        Classifier.create(self.org2, self.admin, LuisType.slug, "Org2 Booker", {})

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 2):
            response = self.fetchJSON(url, readonly_models={Classifier})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {
                    "name": "Booker",
                    "type": "wit",
                    "uuid": str(c1.uuid),
                    "intents": ["book_car", "book_flight"],
                    "created_on": format_datetime(c1.created_on),
                }
            ],
        )

        # filter by uuid (not there)
        response = self.fetchJSON(url, "uuid=09d23a05-47fe-11e4-bfe9-b8f6b119e9ab")
        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(0, len(resp_json["results"]))

        # filter by uuid present
        response = self.fetchJSON(url, "uuid=" + str(c1.uuid))
        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(1, len(resp_json["results"]))
        self.assertEqual("Booker", resp_json["results"][0]["name"])

    def test_ticketers(self):
        url = reverse("api.v2.ticketers")
        self.assertEndpointAccess(url)

        # create some additional ticketers
        t2 = Ticketer.create(self.org, self.admin, MailgunType.slug, "bob@acme.com", {})
        t3 = Ticketer.create(self.org, self.admin, MailgunType.slug, "jim@acme.com", {})

        t4 = Ticketer.create(self.org, self.admin, MailgunType.slug, "deleted", {})
        t4.is_active = False
        t4.save()

        # on another org
        Ticketer.create(self.org2, self.admin, ZendeskType.slug, "zendesk", {})

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 1):
            response = self.fetchJSON(url, readonly_models={Ticketer})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {
                    "uuid": str(t3.uuid),
                    "name": "jim@acme.com",
                    "type": "mailgun",
                    "created_on": format_datetime(t3.created_on),
                },
                {
                    "uuid": str(t2.uuid),
                    "name": "bob@acme.com",
                    "type": "mailgun",
                    "created_on": format_datetime(t2.created_on),
                },
            ],
        )

        # filter by uuid (not there)
        response = self.fetchJSON(url, "uuid=09d23a05-47fe-11e4-bfe9-b8f6b119e9ab")
        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(0, len(resp_json["results"]))

        # filter by uuid present
        response = self.fetchJSON(url, "uuid=" + str(t2.uuid))
        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(1, len(resp_json["results"]))
        self.assertEqual("bob@acme.com", resp_json["results"][0]["name"])

    @patch("temba.mailroom.client.MailroomClient.ticket_close")
    @patch("temba.mailroom.client.MailroomClient.ticket_reopen")
    def test_tickets(self, mock_ticket_reopen, mock_ticket_close):
        url = reverse("api.v2.tickets")
        self.assertEndpointAccess(url)

        # create some tickets
        mailgun = Ticketer.create(self.org, self.admin, MailgunType.slug, "Mailgun", {})
        ann = self.create_contact("Ann", urns=["twitter:annie"])
        bob = self.create_contact("Bob", urns=["twitter:bobby"])
        ticket1 = self.create_ticket(
            mailgun, ann, "Help", closed_on=datetime(2021, 1, 1, 12, 30, 45, 123456, pytz.UTC)
        )
        ticket2 = self.create_ticket(mailgun, bob, "Really")
        ticket3 = self.create_ticket(mailgun, bob, "Pleeeease help", assignee=self.agent)

        # on another org
        zendesk = Ticketer.create(self.org2, self.admin, ZendeskType.slug, "Zendesk", {})
        self.create_ticket(zendesk, self.create_contact("Jim", urns=["twitter:jimmy"], org=self.org2), "Stuff")

        response = self.fetchJSON(url, "ticketer_type=zendesk")
        resp_json = response.json()
        self.assertEqual(0, len(resp_json["results"]))

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 5):
            response = self.fetchJSON(url, readonly_models={Ticket})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {
                    "uuid": str(ticket3.uuid),
                    "ticketer": {"uuid": str(mailgun.uuid), "name": "Mailgun"},
                    "assignee": {"email": "Agent@nyaruka.com", "name": ""},
                    "contact": {"uuid": str(bob.uuid), "name": "Bob"},
                    "status": "open",
                    "topic": {"uuid": str(self.org.default_ticket_topic.uuid), "name": "General"},
                    "body": "Pleeeease help",
                    "opened_on": format_datetime(ticket3.opened_on),
                    "closed_on": None,
                },
                {
                    "uuid": str(ticket2.uuid),
                    "ticketer": {"uuid": str(mailgun.uuid), "name": "Mailgun"},
                    "assignee": None,
                    "contact": {"uuid": str(bob.uuid), "name": "Bob"},
                    "status": "open",
                    "topic": {"uuid": str(self.org.default_ticket_topic.uuid), "name": "General"},
                    "body": "Really",
                    "opened_on": format_datetime(ticket2.opened_on),
                    "closed_on": None,
                },
                {
                    "uuid": str(ticket1.uuid),
                    "ticketer": {"uuid": str(mailgun.uuid), "name": "Mailgun"},
                    "assignee": None,
                    "contact": {"uuid": str(ann.uuid), "name": "Ann"},
                    "status": "closed",
                    "topic": {"uuid": str(self.org.default_ticket_topic.uuid), "name": "General"},
                    "body": "Help",
                    "opened_on": format_datetime(ticket1.opened_on),
                    "closed_on": "2021-01-01T12:30:45.123456Z",
                },
            ],
        )

        # filter by contact uuid (not there)
        response = self.fetchJSON(url, "contact=09d23a05-47fe-11e4-bfe9-b8f6b119e9ab")
        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(0, len(resp_json["results"]))

        # filter by contact uuid present
        response = self.fetchJSON(url, "contact=" + str(bob.uuid))
        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(2, len(resp_json["results"]))
        self.assertEqual("Bob", resp_json["results"][0]["contact"]["name"])

        # filter further by ticket uuid
        response = self.fetchJSON(url, f"uuid={ticket3.uuid}")
        resp_json = response.json()
        self.assertEqual(1, len(resp_json["results"]))

    @mock_mailroom
    def test_ticket_actions(self, mr_mocks):
        url = reverse("api.v2.ticket_actions")

        self.assertEndpointAccess(url, fetch_returns=405)

        # create some tickets
        mailgun = Ticketer.create(self.org, self.admin, MailgunType.slug, "Mailgun", {})
        sales = Topic.get_or_create(self.org, self.admin, "Sales")
        ticket1 = self.create_ticket(
            mailgun,
            self.joe,
            "Help",
            closed_on=datetime(2021, 1, 1, 12, 30, 45, 123456, pytz.UTC),
        )
        ticket2 = self.create_ticket(mailgun, self.joe, "Help")
        self.create_ticket(mailgun, self.frank, "Pleeeease help")

        # on another org
        zendesk = Ticketer.create(self.org2, self.admin, ZendeskType.slug, "Zendesk", {})
        ticket4 = self.create_ticket(zendesk, self.create_contact("Jim", urns=["twitter:jimmy"], org=self.org2), "Hi")

        # try actioning more tickets than this endpoint is allowed to operate on at one time
        response = self.postJSON(url, None, {"tickets": [str(x) for x in range(101)], "action": "close"})
        self.assertResponseError(response, "tickets", "This field can only contain up to 100 items.")

        # try actioning a ticket which is not in this org
        response = self.postJSON(
            url,
            None,
            {"tickets": [str(ticket1.uuid), str(ticket4.uuid)], "action": "close"},
        )
        self.assertResponseError(response, "tickets", f"No such object: {ticket4.uuid}")

        # try to close tickets without specifying any tickets
        response = self.postJSON(url, None, {"action": "close"})
        self.assertResponseError(response, "tickets", "This field is required.")

        # try to assign ticket without specifying assignee
        response = self.postJSON(url, None, {"tickets": [str(ticket1.uuid)], "action": "assign"})
        self.assertResponseError(response, "non_field_errors", 'For action "assign" you must specify the assignee')

        # try to add a note without specifying note
        response = self.postJSON(url, None, {"tickets": [str(ticket1.uuid)], "action": "add_note"})
        self.assertResponseError(response, "non_field_errors", 'For action "add_note" you must specify the note')

        # try to change topic without specifying topic
        response = self.postJSON(url, None, {"tickets": [str(ticket1.uuid)], "action": "change_topic"})
        self.assertResponseError(response, "non_field_errors", 'For action "change_topic" you must specify the topic')

        # assign valid tickets to a user
        response = self.postJSON(
            url,
            None,
            {"tickets": [str(ticket1.uuid), str(ticket2.uuid)], "action": "assign", "assignee": "agent@nyaruka.com"},
        )
        self.assertEqual(response.status_code, 204)

        ticket1.refresh_from_db()
        ticket2.refresh_from_db()
        self.assertEqual(self.agent, ticket1.assignee)
        self.assertEqual(self.agent, ticket2.assignee)

        # unassign tickets
        response = self.postJSON(
            url,
            None,
            {"tickets": [str(ticket1.uuid)], "action": "assign", "assignee": None},
        )
        self.assertEqual(response.status_code, 204)

        ticket1.refresh_from_db()
        self.assertIsNone(ticket1.assignee)

        # add a note to tickets
        response = self.postJSON(
            url,
            None,
            {"tickets": [str(ticket1.uuid), str(ticket2.uuid)], "action": "add_note", "note": "Looks important"},
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual("Looks important", ticket1.events.last().note)
        self.assertEqual("Looks important", ticket2.events.last().note)

        # change topic of tickets
        response = self.postJSON(
            url,
            None,
            {"tickets": [str(ticket1.uuid), str(ticket2.uuid)], "action": "change_topic", "topic": str(sales.uuid)},
        )
        ticket1.refresh_from_db()
        ticket2.refresh_from_db()
        self.assertEqual(response.status_code, 204)
        self.assertEqual(sales, ticket1.topic)
        self.assertEqual(sales, ticket2.topic)

        # close tickets
        response = self.postJSON(url, None, {"tickets": [str(ticket1.uuid), str(ticket2.uuid)], "action": "close"})
        ticket1.refresh_from_db()
        ticket2.refresh_from_db()
        self.assertEqual(response.status_code, 204)
        self.assertEqual("C", ticket1.status)
        self.assertEqual("C", ticket2.status)

        # and finally reopen them
        response = self.postJSON(url, None, {"tickets": [str(ticket1.uuid), str(ticket2.uuid)], "action": "reopen"})
        ticket1.refresh_from_db()
        ticket2.refresh_from_db()
        self.assertEqual(response.status_code, 204)
        self.assertEqual("O", ticket1.status)
        self.assertEqual("O", ticket2.status)

    def test_topics(self):
        url = reverse("api.v2.topics")
        self.assertEndpointAccess(url)

        # create some topics
        support = Topic.get_or_create(self.org, self.admin, "Support")
        sales = Topic.get_or_create(self.org, self.admin, "Sales")
        other_org = Topic.get_or_create(self.org2, self.admin, "Bugs")

        # no filtering
        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 1):
            response = self.fetchJSON(url, readonly_models={Topic})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(
            resp_json["results"],
            [
                {
                    "uuid": str(sales.uuid),
                    "name": "Sales",
                    "created_on": format_datetime(sales.created_on),
                },
                {
                    "uuid": str(support.uuid),
                    "name": "Support",
                    "created_on": format_datetime(support.created_on),
                },
                {
                    "uuid": str(self.org.default_ticket_topic.uuid),
                    "name": "General",
                    "created_on": format_datetime(self.org.default_ticket_topic.created_on),
                },
            ],
        )

        # try to create empty topic
        response = self.postJSON(url, None, {})
        self.assertResponseError(response, "name", "This field is required.")

        # create new topic
        response = self.postJSON(url, None, {"name": "Food"})
        self.assertEqual(response.status_code, 201)

        food = Topic.objects.get(name="Food")
        self.assertEqual(response.json(), {"uuid": str(food.uuid), "name": "Food", "created_on": matchers.ISODate()})

        # try to create another topic with same name
        response = self.postJSON(url, None, {"name": "food"})
        self.assertResponseError(response, "name", "This field must be unique.")

        # it's fine if a topic in another org has that name
        response = self.postJSON(url, None, {"name": "Bugs"})
        self.assertEqual(response.status_code, 201)

        # try to create a topic with invalid name
        response = self.postJSON(url, None, {"name": "!!!#$%^"})
        self.assertResponseError(response, "name", "Contains illegal characters.")

        # try to create a topic with name that's too long
        response = self.postJSON(url, None, {"name": "x" * 65})
        self.assertResponseError(response, "name", "Ensure this field has no more than 64 characters.")

        # update topic by UUID
        response = self.postJSON(url, "uuid=%s" % support.uuid, {"name": "Support Tickets"})
        self.assertEqual(response.status_code, 200)

        support.refresh_from_db()
        self.assertEqual(support.name, "Support Tickets")

        # can't update default topic for an org
        response = self.postJSON(url, "uuid=%s" % self.org.default_ticket_topic.uuid, {"name": "Won't work"})
        self.assertResponseError(response, "non_field_errors", "Can't modify default topic for a workspace.")

        # can't update topic from other org
        response = self.postJSON(url, "uuid=%s" % other_org.uuid, {"name": "Won't work"})
        self.assert404(response)

        # can't update topic to same name as existing topic
        response = self.postJSON(url, "uuid=%s" % support.uuid, {"name": "General"})
        self.assertResponseError(response, "name", "This field must be unique.")

        # try creating a new topic after reaching the limit on labels
        current_count = self.org.topics.filter(is_active=True).count()
        with override_settings(ORG_LIMIT_DEFAULTS={"topics": current_count}):
            response = self.postJSON(url, None, {"name": "Interesting"})
            self.assertResponseError(
                response,
                "non_field_errors",
                "This workspace has 5 topics and the limit is 5. "
                "You must delete existing ones before you can create new ones.",
            )

    def test_users(self):
        endpoint_url = reverse("api.v2.users")

        self.surveyor.first_name = "Stu"
        self.surveyor.last_name = "McSurveys"
        self.surveyor.save()

        self.assertEndpointAccess(endpoint_url)

        with self.assertNumQueries(NUM_BASE_REQUEST_QUERIES + 6):
            response = self.fetchJSON(endpoint_url, readonly_models={User})

        resp_json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resp_json["next"], None)
        self.assertEqual(len(resp_json["results"]), 5)
        self.assertEqual(
            resp_json["results"][0],
            {
                "email": "Surveyor@nyaruka.com",
                "first_name": "Stu",
                "last_name": "McSurveys",
                "role": "surveyor",
                "created_on": format_datetime(self.surveyor.date_joined),
            },
        )

        # filter by roles
        response = self.fetchJSON(endpoint_url, "role=agent&role=editor")
        resp_json = response.json()
        self.assertEqual(["Agent@nyaruka.com", "Editor@nyaruka.com"], [u["email"] for u in resp_json["results"]])

        # non-existent roles ignored
        response = self.fetchJSON(endpoint_url, "role=caretaker&role=editor")
        resp_json = response.json()
        self.assertEqual(["Editor@nyaruka.com"], [u["email"] for u in resp_json["results"]])


class ExternalServicesEndpointTestCase(TembaTest):
    def setUp(self):
        super().setUp()
        self.external_service = ExternalService.objects.create(
            uuid=uuid.uuid4(),
            external_service_type="chatgpt",
            name="test_chatgpt",
            config={},
            org=self.org,
            created_by=self.user,
            modified_by=self.user,
        )

        self.client = Client()
        self.view = ExternalServicesEndpoint.as_view()

    def test_filter_queryset_with_uuid(self):
        self.client.force_login(self.user)
        url = reverse("api.v2.external_services") + ".json"
        uuid = self.external_service.uuid
        request_mock = Mock()
        request_mock.query_params = {"uuid": uuid}
        request_mock.user = Mock()
        request_mock.user.get_org.return_value = self.org

        queryset = ExternalService.objects.filter(org=self.org, is_active=True, uuid=uuid)
        filter_before_after_mock = Mock(return_value=queryset)

        with patch("temba.api.v2.views.ExternalServicesEndpoint.filter_before_after", filter_before_after_mock):
            response = self.client.get(url, data={"uuid": uuid}, request=request_mock)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.external_service.uuid)


class ExternalServicesReadSerializerTest(TembaTest):
    def test_get_external_service_type(self):
        external_service_type = "chatgpt"
        external_service = ExternalService.objects.create(
            uuid=uuid.uuid4(),
            external_service_type="chatgpt",
            name="test_chatgpt",
            config={},
            org=self.org,
            created_by=self.user,
            modified_by=self.user,
        )

        serializer = ExternalServicesReadSerializer(instance=external_service)
        result = serializer.get_external_service_type(external_service)

        self.assertEqual(result, external_service_type)


class ProductReadSerializersTestCase(TembaTest):
    def test_product_read_serializer(self):
        Channel.objects.all().delete()
        org = Org.objects.create(
            name="New Org",
            timezone="UTC",
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
        )
        Channel.objects.all().delete()

        channel = self.create_channel(
            "WAC",
            "WhatsApp: 1234",
            "1234",
            config={
                Channel.CONFIG_BASE_URL: "https://nyaruka.com/whatsapp",
                Channel.CONFIG_USERNAME: "temba",
                Channel.CONFIG_PASSWORD: "tembapasswd1",
                Channel.CONFIG_AUTH_TOKEN: "authtoken123",
                CONFIG_FB_BUSINESS_ID: "1234",
                CONFIG_FB_ACCESS_TOKEN: "token123",
                CONFIG_FB_NAMESPACE: "my-custom-app-1",
                CONFIG_FB_TEMPLATE_LIST_DOMAIN: "graph.facebook.com",
            },
        )

        catalog = Catalog.objects.create(
            facebook_catalog_id="111",
            name="Test Catalog",
            channel=channel,
            org=org,
        )

        product = Product.objects.create(
            catalog=catalog,
            title="Product 1",
            facebook_product_id="fb123",
            product_retailer_id="retail123",
        )
        Product.objects.create(
            catalog=catalog,
            title="Product 2",
            facebook_product_id="fb456",
            product_retailer_id="retail456",
        )
        serializer = ProductReadSerializer(instance=product)
        serialized_data = serializer.data

        self.assertEqual(serialized_data["title"], "Product 1")

        expected_products = {
            "title": "Product 1",
            "facebook_product_id": "fb123",
            "product_retailer_id": "retail123",
            "created_on": product.created_on.replace(tzinfo=pytz.UTC),
        }

        self.assertEqual(serialized_data["facebook_product_id"], expected_products.get("facebook_product_id"))


class ProductsEndpointViewSetTest(TembaTest):
    def setUp(self):
        super().setUp()

        Channel.objects.all().delete()
        Catalog.objects.all().delete()

        self.url = reverse("api.v2.products") + ".json"
        self.client = APIClient()
        self.view = ProductsEndpoint
        self.view.permission_classes = []
        self.client.force_login(user=self.user)

        channel = self.create_channel(
            "WAC",
            "WhatsApp: 1234",
            "1234",
            org=self.org,
            config={
                Channel.CONFIG_BASE_URL: "https://nyaruka.com/whatsapp",
                Channel.CONFIG_USERNAME: "temba",
                Channel.CONFIG_PASSWORD: "tembapasswd2",
                Channel.CONFIG_AUTH_TOKEN: "authtoken123",
                CONFIG_FB_BUSINESS_ID: "1234",
                CONFIG_FB_ACCESS_TOKEN: "token123",
                CONFIG_FB_NAMESPACE: "my-custom-app-2",
                CONFIG_FB_TEMPLATE_LIST_DOMAIN: "graph.facebook.com",
            },
        )

        catalog1 = Catalog.objects.create(
            name="Catalog 1", facebook_catalog_id="111", org=self.org, channel=channel, is_active=True
        )
        catalog2 = Catalog.objects.create(name="Catalog 2", facebook_catalog_id="222", org=self.org, channel=channel)
        Catalog.objects.create(name="Catalog 3", facebook_catalog_id="333", org=self.org, channel=channel)

        self.product1 = Product.objects.create(
            catalog=catalog1, title="Product 1", facebook_product_id="fb456", product_retailer_id="retail456"
        )
        Product.objects.create(
            catalog=catalog2, title="Product 2", facebook_product_id="fb789", product_retailer_id="retail789"
        )

    def test_get_queryset(self):
        viewset = ProductsEndpoint()
        viewset.request = self.client.get("/")
        viewset.request.user = self.user

        filtered_queryset = viewset.get_queryset()

        self.assertEqual(filtered_queryset.count(), 1)
        self.assertEqual(filtered_queryset.first(), self.product1)

    @patch("temba.api.v2.views.ProductsEndpoint.filter_before_after")
    def test_filter_queryset_prodcut_name(self, mock_filter_before_after):
        name = self.product1.title
        queryset = Product.objects.filter(title=name)
        mock_filter_before_after.return_value = queryset

        response = self.client.get(self.url, data={"name": name})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product1.title)

    @patch("temba.api.v2.views.ProductsEndpoint.filter_before_after")
    def test_filter_queryset_product_retailer_id(self, mock_filter_before_after):
        retailer_id = self.product1.product_retailer_id
        queryset = Product.objects.filter(product_retailer_id=retailer_id)
        mock_filter_before_after.return_value = queryset

        response = self.client.get(self.url, data={"retailer_id": retailer_id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product1.title)


class TestSearchIntegrations(TembaTest):
    def test_search_integrations_with_classifiers_and_ticketers(self):
        classifier = Classifier.objects.create(
            org=self.org,
            created_by=self.user,
            modified_by=self.user,
            uuid=uuid.uuid4(),
            name="Classifier1",
            config={"repository": "548eaa72-18ab-432a-b781-1ac922a35e83"},
            classifier_type="bothub",
        )

        exported_flows = [
            {
                "nodes": [
                    {
                        "actions": [
                            {
                                "classifier": {
                                    "uuid": classifier.uuid,
                                    "name": classifier.name,
                                }
                            }
                        ]
                    },
                    {
                        "actions": [
                            {
                                "ticketer": {"uuid": "bf9e85ed-b74d-495c-8624-5f91fab13948", "name": "Ticketer1"},
                                "topic": {"uuid": "bcef48af-9b73-428d-bd7b-144ea66e2479", "name": "Queue1"},
                            }
                        ]
                    },
                ]
            }
        ]

        integrations = Org.search_integrations(exported_flows)

        self.assertEqual(integrations[0]["integrations"]["classifiers"][0]["uuid"], classifier.uuid)
        self.assertEqual(integrations[0]["integrations"]["classifiers"][0]["name"], classifier.name)
        self.assertEqual(
            integrations[0]["integrations"]["classifiers"][0]["repository_uuid"],
            "548eaa72-18ab-432a-b781-1ac922a35e83",
        )

        self.assertEqual(
            integrations[0]["integrations"]["ticketers"][0]["uuid"], "bf9e85ed-b74d-495c-8624-5f91fab13948"
        )
        self.assertEqual(integrations[0]["integrations"]["ticketers"][0]["name"], "Ticketer1")
        self.assertEqual(
            integrations[0]["integrations"]["ticketers"][0]["queues"][0]["uuid"],
            "bcef48af-9b73-428d-bd7b-144ea66e2479",
        )
        self.assertEqual(integrations[0]["integrations"]["ticketers"][0]["queues"][0]["name"], "Queue1")

    def test_search_integrations_with_only_classifiers(self):
        classifier = Classifier.objects.create(
            org=self.org,
            created_by=self.user,
            modified_by=self.user,
            uuid=uuid.uuid4(),
            name="Classifier1",
            config={"repository": "repo123"},
            classifier_type="bothub",
        )

        exported_flows = [
            {"nodes": [{"actions": [{"classifier": {"uuid": classifier.uuid, "name": classifier.name}}]}]}
        ]

        integrations = Org.search_integrations(exported_flows)

        self.assertEqual(integrations[0]["integrations"]["classifiers"][0]["uuid"], classifier.uuid)
        self.assertEqual(integrations[0]["integrations"]["classifiers"][0]["name"], classifier.name)
        self.assertEqual(integrations[0]["integrations"]["classifiers"][0]["repository_uuid"], "repo123")

    def test_search_integrations_with_only_ticketers(self):
        exported_flows = [
            {
                "nodes": [
                    {
                        "actions": [
                            {
                                "ticketer": {"uuid": "ticketer123", "name": "Ticketer1"},
                                "topic": {"uuid": "topic123", "name": "Queue1"},
                            }
                        ]
                    }
                ]
            }
        ]

        integrations = Org.search_integrations(exported_flows)

        self.assertEqual(integrations[0]["integrations"]["ticketers"][0]["uuid"], "ticketer123")
        self.assertEqual(integrations[0]["integrations"]["ticketers"][0]["name"], "Ticketer1")
        self.assertEqual(integrations[0]["integrations"]["ticketers"][0]["queues"][0]["uuid"], "topic123")
        self.assertEqual(integrations[0]["integrations"]["ticketers"][0]["queues"][0]["name"], "Queue1")


class TestTemplateFilterQuerySetTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.template1 = Template.objects.create(
            name="Template1", uuid="ccb4ed42-0646-45b6-bd0f-78fc2e8bb083", org=self.org
        )
        self.template2 = Template.objects.create(
            name="Template2", uuid="9f28abed-c2bd-41d7-9db4-cc2aaee79a74", org=self.org
        )

        TemplateTranslation.objects.create(
            template=self.template1,
            channel=self.channel,
            content="123456",
            variable_count=0,
            status=TemplateTranslation.STATUS_REJECTED,
            language="pt-br",
            country="BR",
            external_id=123,
            namespace="Test",
        )

        self.url = reverse("api.v2.templates") + ".json"
        self.client = APIClient()
        self.view = TemplatesEndpoint
        self.view.permission_classes = []
        self.client.force_login(user=self.user)

    @patch("temba.api.v2.views.TemplatesEndpoint.filter_before_after")
    def test_filter_queryset_by_uuid(self, mock_filter_before_after):
        uuid = self.template1.uuid
        queryset = Template.objects.filter(org=self.org, uuid=uuid)
        mock_filter_before_after.return_value = queryset

        response = self.client.get(self.url, data={"uuid": uuid})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.template1.uuid)

    @patch("temba.api.v2.views.TemplatesEndpoint.filter_before_after")
    def test_filter_queryset_by_name(self, mock_filter_before_after):
        name = self.template2.name
        queryset = Template.objects.filter(org=self.org, name=name)
        mock_filter_before_after.return_value = queryset

        response = self.client.get(self.url, data={"name": name})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.template2.name)

    @patch("temba.api.v2.views.TemplatesEndpoint.filter_before_after")
    def test_filter_queryset_by_translation_status(self, mock_filter_before_after):
        status = "R"
        queryset = Template.objects.filter(org=self.org, translations__status=TemplateTranslation.STATUS_REJECTED)
        mock_filter_before_after.return_value = queryset

        response = self.client.get(self.url, data={"status": status})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "rejected")

    @patch("temba.api.v2.views.TemplatesEndpoint.filter_before_after")
    def test_filter_queryset_no_parameters(self, mock_filter_before_after):
        queryset = Template.objects.filter(org=self.org)
        mock_filter_before_after.return_value = queryset

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)


class FlowsLabelsEndpointTest(TembaTest):
    @patch("temba.api.v2.views.FlowsLabelsEndpoint.get_queryset")
    def test_flows_labels_endpoint(self, mock_get_queryset):
        client = APIClient()
        view = FlowsLabelsEndpoint
        view.permission_classes = []

        client.force_login(self.user)
        org = self.user.get_org()

        label = FlowLabel.objects.create(org=org, name="Important", parent=None)

        url = reverse("api.v2.flows_labels") + ".json"
        response = client.get(url, data={})

        self.assertEqual(response.status_code, 200)

        expected_result = {
            "next": None,
            "previous": None,
            "results": [
                {
                    "uuid": label.uuid,
                    "name": "Important",
                    "parent": None,
                }
            ],
        }
        self.assertEqual(response.json(), expected_result)


class ContactsTemplatesEndpointTest(TembaTest):
    def test_contacts_templates(self):
        contact1 = self.create_contact(name="Josefina", org=self.org, user=self.user)
        contact2 = self.create_contact(name="Jospem", org=self.org, user=self.user)
        contact2.is_active = False
        contact2.save(update_fields=["is_active"])
        group = self.create_group("Customers", [contact1, contact2])

        metadata = {
            "templating": {
                "template": {"uuid": "44019537-9afe-4898-9626-a5c724d169ef", "name": "template_test"},
                "language": "por",
                "country": "PT",
                "variables": ["123"],
                "namespace": "",
            },
            "text_language": "pt-BR",
        }

        Msg.objects.create(
            org=self.org,
            direction="O",
            contact=contact1,
            contact_urn=None,
            text="Hello",
            channel=self.channel,
            topup_id=None,
            status="S",
            msg_type="",
            attachments=None,
            visibility="V",
            external_id=None,
            high_priority=None,
            created_on=timezone.now(),
            sent_on=timezone.now(),
            broadcast=None,
            metadata=metadata,
            next_attempt=None,
            template="template_test",
        )

        view = ContactsTemplatesEndpoint
        view.permission_classes = []

        self.client.force_login(self.user)
        url = reverse("api.v2.contact_templates") + ".json"

        # Verify filter by contact
        response = self.client.get(url, data={"contact": contact1.uuid})

        self.assertEqual(response.status_code, 200)

        # verify filter by group
        response = self.client.get(url, data={"group": group.uuid})

        self.assertEqual(response.status_code, 200)

        # verify filter by template
        response = self.client.get(url, data={"template": "template_test"})

        self.assertEqual(response.status_code, 200)

        # verify filter by limit
        response = self.client.get(url, data={"template": "template_test", "limit": "1"})

        self.assertEqual(response.status_code, 200)

        # verify filter by offset
        response = self.client.get(url, data={"template": "template_test", "offset": "1"})

        self.assertEqual(response.status_code, 200)

        # verify filter by before
        response = self.client.get(
            url, data={"template": "template_test", "before": format_datetime(contact1.modified_on)}
        )

        self.assertEqual(response.status_code, 200)

        # verify filter by after
        response = self.client.get(
            url, data={"template": "template_test", "after": format_datetime(contact1.modified_on)}
        )

        self.assertEqual(response.status_code, 200)

    def test_contacts_templates_status_unknown(self):

        contact1 = self.create_contact(name="Jospem", org=self.org, user=self.user)

        metadata = {
            "templating": {
                "template": {"uuid": "44019537-9afe-4898-9626-a5c724d169ef", "name": "template_test_2"},
                "language": "eng",
                "country": "ENG",
                "variables": ["123"],
                "namespace": "",
            },
            "text_language": "pt-BR",
        }

        # A status that not exist
        Msg.objects.create(
            org=self.org,
            direction="O",
            contact=contact1,
            contact_urn=None,
            text="Hello",
            channel=self.channel,
            topup_id=None,
            status="Z",
            msg_type="",
            attachments=None,
            visibility="V",
            external_id=None,
            high_priority=None,
            created_on=timezone.now(),
            sent_on=timezone.now(),
            broadcast=None,
            metadata=metadata,
            next_attempt=None,
        )

        view = ContactsTemplatesEndpoint
        view.permission_classes = []

        self.client.force_login(self.user)
        url = reverse("api.v2.contact_templates") + ".json"
        response = self.client.get(url, data={"contact": contact1.uuid})

        self.assertEqual(response.status_code, 200)


class FilterTemplatesEndpointTest(TembaTest):
    def test_filter_templates(self):
        contact = self.create_contact(name="Martinelli", org=self.org, user=self.user)

        metadata = {
            "templating": {
                "template": {"uuid": "44019537-9afe-4898-9626-a5c724d169gh", "name": "template_test_2"},
                "language": "eng",
                "country": "USA",
                "variables": ["321"],
                "namespace": "",
            },
            "text_language": "eng-US",
        }

        Msg.objects.create(
            org=self.org,
            direction="O",
            contact=contact,
            contact_urn=None,
            text="Hello My friend",
            channel=self.channel,
            topup_id=None,
            status="S",
            msg_type="",
            attachments=None,
            visibility="V",
            external_id=None,
            high_priority=None,
            created_on=timezone.now(),
            sent_on=timezone.now(),
            broadcast=None,
            metadata=metadata,
            next_attempt=None,
        )

        view = FilterTemplatesEndpoint
        view.permission_classes = []

        self.client.force_login(self.user)
        url = reverse("api.v2.filter_templates") + ".json"

        # verify filter by template
        response = self.client.get(url, data={"template": "template_test"})

        self.assertEqual(response.status_code, 200)

        # verify filter with page size
        response = self.client.get(url, data={"template": "template_test", "page_size": "1"})

        self.assertEqual(response.status_code, 200)

        # verify filter by offset
        response = self.client.get(url, data={"template": "template_test", "offset": "1"})

        self.assertEqual(response.status_code, 200)

        # verify filter with before
        response = self.client.get(url, data={"template": "template_test", "before": "2024-03-08"})

        self.assertEqual(response.status_code, 200)

        # verify filter with after
        response = self.client.get(url, data={"template": "template_test", "after": "2024-03-05"})

        self.assertEqual(response.status_code, 200)


class WhatsappFlowsEndpointViewSetTest(TembaTest):
    def test_whatsapp_flow(self):
        WhatsappFlow.objects.all().delete()
        view = WhatsappFlowsEndpoint
        view.permission_classes = []

        self.client.force_login(self.user)
        url = reverse("api.v2.whatsapp_flows") + ".json"

        channel = self.create_channel(
            "WAC",
            "WhatsApp: 1234",
            "1234",
            org=self.org,
            config={
                Channel.CONFIG_BASE_URL: "https://nyaruka.com/whatsapp",
                Channel.CONFIG_USERNAME: "temba",
                Channel.CONFIG_PASSWORD: "tembapasswd2",
                Channel.CONFIG_AUTH_TOKEN: "authtoken123",
                CONFIG_FB_BUSINESS_ID: "1234",
                CONFIG_FB_ACCESS_TOKEN: "token123",
                CONFIG_FB_NAMESPACE: "my-custom-app-2",
                CONFIG_FB_TEMPLATE_LIST_DOMAIN: "graph.facebook.com",
            },
        )

        WhatsappFlow.objects.create(
            facebook_flow_id="123456789",
            category=["cat1"],
            status="active",
            name="Flow 1",
            validation_errors=[],
            screens={"id": "screen_1", "data": {"var1": "value1", "var2": "value2"}},
            variables={"screens": ["screen_1"], "variables": ["var1", "var2"]},
            org=self.org,
            channel=channel,
            is_active=True,
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        response = self.client.get(url, data={"id": "123456789"})
        self.assertEqual(response.status_code, 200)

        response = self.client.get(url, data={"name": "Flow 1"})
        self.assertEqual(response.status_code, 200)


class EventsEndpointTest(APITest):
    @patch("temba.api.v2.views.get_events")
    def test_events_endpoint(self, mock_get_events):
        url = reverse("api.v2.events")
        self.org.proj_uuid = uuid.uuid4()
        self.org.save()

        mock_get_events.return_value = [{"event": "test"}]

        self.login(self.admin)

        start_date = "2024-01-01T00:00:00Z"
        end_date = "2024-01-31T23:59:59Z"
        query = f"date_start={start_date}&date_end={end_date}"

        response = self.fetchJSON(url, query)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"event": "test"}])

        mock_get_events.assert_called_once()
        call_args, call_kwargs = mock_get_events.call_args
        self.assertEqual(call_kwargs["project"], str(self.org.proj_uuid))
        self.assertEqual(call_kwargs["date_start"], iso8601.parse_date(start_date))
        self.assertEqual(call_kwargs["date_end"], iso8601.parse_date(end_date))

    @patch("temba.api.v2.views.get_events")
    def test_json_payload_parsing(self, mock_get_events):
        url = reverse("api.v2.events")
        self.org.proj_uuid = uuid.uuid4()
        self.org.save()

        mock_get_events.return_value = [{"payload": '{"key": "value"}'}]

        self.login(self.admin)

        start_date = "2024-01-01T00:00:00Z"
        end_date = "2024-01-31T23:59:59Z"
        query = f"date_start={start_date}&date_end={end_date}"

        response = self.fetchJSON(url, query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"payload": {"key": "value"}}])

    @patch("temba.api.v2.views.get_events")
    def test_invalid_json_payload(self, mock_get_events):
        url = reverse("api.v2.events")
        self.org.proj_uuid = uuid.uuid4()
        self.org.save()

        mock_get_events.return_value = [{"payload": '{"key": "value"invalid}'}]

        self.login(self.admin)
        start_date = "2024-01-01T00:00:00Z"
        end_date = "2024-01-31T23:59:59Z"
        query = f"date_start={start_date}&date_end={end_date}"

        response = self.fetchJSON(url, query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"payload": '{"key": "value"invalid}'}])

    @patch("temba.api.v2.views.get_events")
    def test_get_events_exception(self, mock_get_events):
        url = reverse("api.v2.events")
        self.org.proj_uuid = uuid.uuid4()
        self.org.save()

        error_message = "Something went wrong"
        mock_get_events.side_effect = Exception(error_message)

        self.login(self.admin)
        start_date = "2024-01-01T00:00:00Z"
        end_date = "2024-01-31T23:59:59Z"
        query = f"date_start={start_date}&date_end={end_date}"

        response = self.fetchJSON(url, query)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": error_message})

    @patch("temba.api.v2.views.get_events")
    def test_non_json_string_in_payload(self, mock_get_events):
        self.login(self.admin)
        self.org.proj_uuid = uuid.uuid4()
        self.org.save()

        mock_get_events.return_value = [{"key": "non-json-string"}]

        url = reverse("api.v2.events")
        query = "date_start=2025-06-03T00:00:00Z&date_end=2025-06-20T23:59:59Z"

        response = self.fetchJSON(url, query)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"key": "non-json-string"}])

    @patch("temba.api.v2.views.get_events")
    def test_payload_with_other_types(self, mock_get_events):
        self.login(self.admin)
        self.org.proj_uuid = uuid.uuid4()
        self.org.save()

        mock_get_events.return_value = [{"key_int": 123, "key_bool": False, "key_none": None}]

        url = reverse("api.v2.events")
        query = "date_start=2025-06-03T00:00:00Z&date_end=2025-06-20T23:59:59Z"

        response = self.fetchJSON(url, query)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"key_int": 123, "key_bool": False, "key_none": None}])
