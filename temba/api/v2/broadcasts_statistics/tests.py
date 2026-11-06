import uuid
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

from django.contrib.auth.models import Group
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from temba.api.models import APIToken
from temba.api.v2.tests import APIJSONMixin
from temba.msgs.models import Broadcast, BroadcastStatistics
from temba.templates.models import Template
from temba.tests import TembaTest

ITEM_FIELDS = {
    "id",
    "name",
    "created_by",
    "created_on",
    "modified_on",
    "text",
    "media",
    "broadcast_type",
    "groups",
    "status",
    "statistics",
    "template",
}
NONEXISTENT_TEMPLATE_ID = 999999
STATISTICS_FIELDS = {
    "processed",
    "sent",
    "delivered",
    "failed",
    "contact_count",
    "read",
    "cost",
    "currency",
    "template_price",
    "created_on",
    "modified_on",
}


class BroadcastsStatisticsEndpointTest(APIJSONMixin, TembaTest):
    def setUp(self):
        super().setUp()

        self.url = reverse("api.v2.broadcasts_statistics")

        self.org.proj_uuid = uuid.uuid4()
        self.org.save(update_fields=("proj_uuid",))
        self.org2.proj_uuid = uuid.uuid4()
        self.org2.save(update_fields=("proj_uuid",))

        self.contact = self.create_contact("Ann", urns=["tel:+250788000001"])
        self.org2_contact = self.create_contact("Bob", urns=["tel:+250788000002"], org=self.org2)

        # error responses mark the request transaction for rollback, which would break the test's own transaction
        connection.settings_dict["ATOMIC_REQUESTS"] = False

    def tearDown(self):
        super().tearDown()

        connection.settings_dict["ATOMIC_REQUESTS"] = True

    def create_bulk_broadcast(self, name, days_ago, org=None, user=None, template_id=None, is_bulk_send=True):
        org = org or self.org
        contact = self.contact if org == self.org else self.org2_contact
        broadcast = Broadcast.create(
            org, user or self.admin, text="Hello", contacts=[contact], is_bulk_send=is_bulk_send
        )
        broadcast.name = name
        broadcast.created_on = timezone.now() - timedelta(days=days_ago)
        broadcast.template_id = template_id
        broadcast.save(update_fields=("name", "created_on", "template_id"))
        return broadcast

    def request(self, query="", readonly_models: set = None, **headers):
        url = f"{self.url}.json"
        if query:
            url += f"?{query}"
        with self.mockReadOnly(assert_models=readonly_models):
            return self.client.get(url, HTTP_X_FORWARDED_HTTPS="https", **headers)

    def request_by_token(self, token, query="", readonly_models: set = None):
        return self.request(query, readonly_models=readonly_models, HTTP_AUTHORIZATION=f"Token {token.key}")

    def request_by_jwt(self, payload, query=""):
        with override_settings(JWT_PUBLIC_KEY="fake-public-key"), patch(
            "temba.api.auth.jwt.jwt.decode", return_value=payload
        ):
            return self.request(query, HTTP_AUTHORIZATION="Bearer valid.jwt.token")

    def result_ids(self, response):
        self.assertEqual(200, response.status_code, response.content)
        return [r["id"] for r in response.json()["results"]]

    def test_api_key_lists_workspace_bulk_broadcasts_with_statistics(self):
        template = Template.objects.create(org=self.org, name="Welcome")
        older = self.create_bulk_broadcast("Older", days_ago=5, template_id=template.id)
        newer = self.create_bulk_broadcast("Newer", days_ago=1)
        self.create_bulk_broadcast("Not bulk", days_ago=1, is_bulk_send=False)
        self.create_bulk_broadcast("Other org", days_ago=1, org=self.org2, user=self.admin2)

        BroadcastStatistics.objects.create(
            broadcast=older,
            org=self.org,
            processed=5,
            sent=4,
            delivered=3,
            failed=1,
            read=2,
            contact_count=5,
            cost=1,
            template_price=0.5,
            currency="USD",
        )

        token = APIToken.get_or_create(self.org, self.admin, Group.objects.get(name="Administrators"))

        response = self.request_by_token(token, readonly_models={Broadcast})

        self.assertEqual([newer.id, older.id], self.result_ids(response))

        body = response.json()
        self.assertEqual(2, body["count"])
        self.assertIsNone(body["next"])
        self.assertIsNone(body["previous"])

        newer_item, older_item = body["results"]
        self.assertEqual(ITEM_FIELDS, set(older_item.keys()))
        self.assertEqual(STATISTICS_FIELDS, set(older_item["statistics"].keys()))
        self.assertEqual("Older", older_item["name"])
        self.assertEqual(self.admin.email, older_item["created_by"])
        self.assertEqual({"id": template.id, "name": "Welcome"}, older_item["template"])
        self.assertEqual(4, older_item["statistics"]["sent"])
        self.assertEqual(2, older_item["statistics"]["read"])
        self.assertEqual("USD", older_item["statistics"]["currency"])

        # a broadcast without statistics gets the same defaults as the internal endpoint
        self.assertIsNone(newer_item["template"])
        self.assertEqual(0, newer_item["statistics"]["sent"])
        self.assertEqual("BRL", newer_item["statistics"]["currency"])
        self.assertIsNone(newer_item["statistics"]["created_on"])

    def test_representation_matches_internal_endpoint(self):
        template = Template.objects.create(org=self.org, name="Welcome")
        broadcast = self.create_bulk_broadcast("Same", days_ago=1, template_id=template.id)
        BroadcastStatistics.objects.create(broadcast=broadcast, org=self.org, sent=3, delivered=2)

        self.login(self.admin)
        public = self.request().json()["results"]

        with patch(
            "temba.api.v2.internals.broadcasts.views.InternalBroadcastStatisticsEndpoint.authentication_classes", []
        ), patch("temba.api.v2.internals.broadcasts.views.InternalBroadcastStatisticsEndpoint.permission_classes", []):
            internal = self.client.get(
                "/api/v2/internals/broadcasts-statistics", {"project_uuid": str(self.org.proj_uuid)}
            ).json()["results"]

        self.assertEqual(internal, public)

    def test_missing_template_and_template_of_other_org_are_null(self):
        other_org_template = Template.objects.create(org=self.org2, name="Not yours")
        self.create_bulk_broadcast("Deleted template", days_ago=2, template_id=NONEXISTENT_TEMPLATE_ID)
        self.create_bulk_broadcast("Foreign template", days_ago=1, template_id=other_org_template.id)

        self.login(self.admin)
        results = self.request().json()["results"]

        self.assertEqual([None, None], [r["template"] for r in results])

    def test_broadcast_without_creator(self):
        broadcast = self.create_bulk_broadcast("Orphan", days_ago=1)
        Broadcast.objects.filter(id=broadcast.id).update(created_by=None)

        self.login(self.admin)
        results = self.request().json()["results"]

        self.assertIsNone(results[0]["created_by"])

    def test_api_key_ignores_project_of_another_workspace(self):
        mine = self.create_bulk_broadcast("Mine", days_ago=1)
        self.create_bulk_broadcast("Theirs", days_ago=1, org=self.org2, user=self.admin2)

        token = APIToken.get_or_create(self.org, self.admin, Group.objects.get(name="Administrators"))
        response = self.request_by_token(token, f"project_uuid={self.org2.proj_uuid}")

        self.assertEqual([mine.id], self.result_ids(response))

    def test_jwt_resolves_workspace_from_token_claims_only(self):
        mine = self.create_bulk_broadcast("Mine", days_ago=1)
        self.create_bulk_broadcast("Theirs", days_ago=1, org=self.org2, user=self.admin2)

        response = self.request_by_jwt({"project_uuid": str(self.org.proj_uuid)})
        self.assertEqual([mine.id], self.result_ids(response))

        response = self.request_by_jwt(
            {"project_uuid": str(self.org.proj_uuid)}, f"project_uuid={self.org2.proj_uuid}"
        )
        self.assertEqual([mine.id], self.result_ids(response))

    def test_jwt_with_unknown_or_missing_project(self):
        self.create_bulk_broadcast("Theirs", days_ago=1, org=self.org2, user=self.admin2)

        response = self.request_by_jwt({"project_uuid": str(uuid.uuid4())})
        self.assertEqual(400, response.status_code)

        response = self.request_by_jwt({"sub": "service"})
        self.assertEqual(400, response.status_code)

        # without tenant claims, a query parameter cannot pick the workspace
        response = self.request_by_jwt({"sub": "service"}, f"project_uuid={self.org2.proj_uuid}")
        self.assertEqual(400, response.status_code)

    def test_every_workspace_role_can_read(self):
        broadcast = self.create_bulk_broadcast("Shared", days_ago=1)

        for user in (self.admin, self.editor, self.agent, self.user, self.surveyor):
            self.login(user)
            self.assertEqual([broadcast.id], self.result_ids(self.request()), user.username)
            self.client.logout()

        marketing = self.create_user("Marketer")
        self.org.marketing.add(marketing)
        self.login(marketing)
        self.assertEqual([broadcast.id], self.result_ids(self.request()))
        self.client.logout()

        surveyor_token = APIToken.get_or_create(self.org, self.surveyor, Group.objects.get(name="Surveyors"))
        self.assertEqual([broadcast.id], self.result_ids(self.request_by_token(surveyor_token)))

    def test_new_permission_does_not_open_other_broadcast_endpoints(self):
        broadcasts_url = reverse("api.v2.broadcasts")

        self.login(self.user)
        response = self.client.get(f"{broadcasts_url}.json", HTTP_X_FORWARDED_HTTPS="https")
        self.assertEqual(403, response.status_code)
        self.client.logout()

        surveyor_token = APIToken.get_or_create(self.org, self.surveyor, Group.objects.get(name="Surveyors"))
        response = self.client.get(
            f"{broadcasts_url}.json",
            HTTP_X_FORWARDED_HTTPS="https",
            HTTP_AUTHORIZATION=f"Token {surveyor_token.key}",
        )
        self.assertEqual(403, response.status_code)

    def test_access_denied(self):
        self.assertEqual(403, self.request().status_code)

        self.assertEqual(403, self.request(HTTP_AUTHORIZATION="Token invalidtoken").status_code)

        self.login(self.non_org_user)
        self.assertEqual(403, self.request().status_code)

    def test_unsupported_methods(self):
        self.login(self.admin)

        self.assertEqual(405, self.postJSON(self.url, None, {}).status_code)
        self.assertEqual(405, self.client.options(f"{self.url}.json", HTTP_X_FORWARDED_HTTPS="https").status_code)

    def test_filters(self):
        alpha = self.create_bulk_broadcast("Alpha", days_ago=40)
        beta = self.create_bulk_broadcast("Beta", days_ago=10)
        gamma = self.create_bulk_broadcast("Gamma", days_ago=1)

        self.login(self.admin)

        def fetch_ids(**params):
            return self.result_ids(self.fetchJSON(self.url, urlencode(params)))

        start = (timezone.now() - timedelta(days=30)).isoformat()
        end = (timezone.now() - timedelta(days=5)).isoformat()

        self.assertEqual([gamma.id, beta.id], fetch_ids(start_date=start))
        self.assertEqual([beta.id, alpha.id], fetch_ids(end_date=end))
        self.assertEqual([beta.id], fetch_ids(start_date=start, end_date=end))
        self.assertEqual([beta.id], fetch_ids(name="bet"))
        self.assertEqual([alpha.id], fetch_ids(id=alpha.id))

        # date-only values are accepted, as on the internal endpoint
        self.assertEqual([gamma.id, beta.id], fetch_ids(start_date=(timezone.now() - timedelta(days=30)).date()))

        # empty values are ignored
        self.assertEqual([gamma.id, beta.id, alpha.id], fetch_ids(start_date="", id="", name=""))

    def test_pagination(self):
        broadcasts = [self.create_bulk_broadcast(f"B{i}", days_ago=i + 1) for i in range(5)]

        self.login(self.admin)
        response = self.fetchJSON(self.url, "limit=2&offset=2")

        self.assertEqual([broadcasts[2].id, broadcasts[3].id], self.result_ids(response))
        body = response.json()
        self.assertEqual(5, body["count"])
        self.assertIn("offset=4", body["next"])
        self.assertIsNotNone(body["previous"])

    def test_invalid_filters(self):
        self.login(self.admin)

        response = self.fetchJSON(self.url, "start_date=not-a-date")
        self.assertEqual(400, response.status_code)
        self.assertIn("start_date", response.json())

        response = self.fetchJSON(self.url, "end_date=31/10/2026")
        self.assertEqual(400, response.status_code)
        self.assertIn("end_date", response.json())

        response = self.fetchJSON(self.url, "start_date=2026-10-10&end_date=2026-10-01")
        self.assertEqual(400, response.status_code)
        self.assertIn("start_date", response.json())

        response = self.fetchJSON(self.url, "id=abc")
        self.assertEqual(400, response.status_code)
        self.assertIn("id", response.json())

    def test_query_count_does_not_grow_with_page_size(self):
        template = Template.objects.create(org=self.org, name="Welcome")
        group = self.create_group("Customers", contacts=[self.contact])

        def add_broadcast(index):
            broadcast = self.create_bulk_broadcast(f"B{index}", days_ago=index + 1, template_id=template.id)
            broadcast.groups.add(group)
            BroadcastStatistics.objects.create(broadcast=broadcast, org=self.org, sent=index)

        token = APIToken.get_or_create(self.org, self.admin, Group.objects.get(name="Administrators"))

        def count_queries():
            self.request_by_token(token)  # warm up token and org caches
            with CaptureQueriesContext(connection) as ctx:
                response = self.request_by_token(token)
            self.assertEqual(200, response.status_code)
            return len(ctx.captured_queries)

        add_broadcast(0)
        single = count_queries()

        for index in range(1, 5):
            add_broadcast(index)
        several = count_queries()

        self.assertEqual(single, several)

    def test_listed_in_root_explorer_and_docs(self):
        self.login(self.admin)

        response = self.client.get(reverse("api.v2") + ".json", HTTP_X_FORWARDED_HTTPS="https")
        self.assertIn("broadcasts_statistics", response.json())

        response = self.client.get(reverse("api.v2.explorer"))
        self.assertContains(response, "List Broadcasts Statistics")

        with self.mockReadOnly(), CaptureQueriesContext(connection) as ctx:
            response = self.fetchHTML(self.url)
        self.assertContains(response, "Listing Broadcasts Statistics")
        self.assertFalse(any('"msgs_broadcast"' in q["sql"] for q in ctx.captured_queries))
