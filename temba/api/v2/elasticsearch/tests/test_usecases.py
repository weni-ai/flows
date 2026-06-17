from unittest.mock import Mock, patch

from django.test import override_settings

from temba.api.v2.elasticsearch.usecases import (
    URNS_PATH,
    URNS_SCHEME,
    BuildContactNumberQueryUseCase,
    SearchContactsElasticUseCase,
    get_pagination_links,
)
from temba.tests import TembaTest


class GetPaginationLinksTest(TembaTest):
    def test_first_page_with_more_pages(self):
        links = get_pagination_links("http://test/contacts", 1, 3, 10)
        self.assertEqual(links, {"next": "http://test/contacts?page_number=2&page_size=10"})

    def test_middle_page(self):
        links = get_pagination_links("http://test/contacts", 2, 3, 10)
        self.assertEqual(
            links,
            {
                "next": "http://test/contacts?page_number=3&page_size=10",
                "previous": "http://test/contacts?page_number=1&page_size=10",
            },
        )

    def test_last_page_has_no_next(self):
        links = get_pagination_links("http://test/contacts", 3, 3, 10)
        self.assertEqual(links, {"previous": "http://test/contacts?page_number=2&page_size=10"})

    def test_single_page_has_no_links(self):
        self.assertEqual(get_pagination_links("http://test/contacts", 1, 1, 10), {})

    def test_preserves_existing_query_params(self):
        links = get_pagination_links("http://test/contacts?project_uuid=abc", 1, 3, 10)
        self.assertEqual(links["next"], "http://test/contacts?project_uuid=abc&page_number=2&page_size=10")


class BuildContactNumberQueryUseCaseTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.usecase = BuildContactNumberQueryUseCase()

    def _nested_bool(self, query):
        return query.to_dict()["nested"]["query"]["bool"]

    def test_literal_only_matches_any_scheme(self):
        query = self.usecase.execute("558481204567")
        bool_query = self._nested_bool(query)

        self.assertEqual(len(bool_query["should"]), 1)
        self.assertEqual(bool_query["should"][0], {"match_phrase": {URNS_PATH: "558481204567"}})
        self.assertEqual(bool_query["must"], [{"exists": {"field": URNS_PATH}}])

    def test_literal_and_whatsapp_variant(self):
        query = self.usecase.execute("5584981204567")
        bool_query = self._nested_bool(query)

        self.assertEqual(len(bool_query["should"]), 2)
        self.assertEqual(bool_query["should"][0], {"match_phrase": {URNS_PATH: "5584981204567"}})
        self.assertEqual(
            bool_query["should"][1],
            {
                "bool": {
                    "must": [
                        {"match_phrase": {URNS_PATH: "558481204567"}},
                        {"term": {URNS_SCHEME: "whatsapp"}},
                    ]
                }
            },
        )

    def test_short_number_still_builds_literal_query(self):
        query = self.usecase.execute("123")
        bool_query = self._nested_bool(query)

        self.assertEqual(len(bool_query["should"]), 1)
        self.assertEqual(bool_query["should"][0], {"match_phrase": {URNS_PATH: "123"}})

    def test_empty_number_returns_none(self):
        self.assertIsNone(self.usecase.execute(""))
        self.assertIsNone(self.usecase.execute("abc"))

    def test_whatsapp_variant_only_path(self):
        # fragment with 9 prefix generates literal + variant
        query = self.usecase.execute("99676")
        bool_query = self._nested_bool(query)

        self.assertEqual(len(bool_query["should"]), 2)
        self.assertEqual(bool_query["should"][0], {"match_phrase": {URNS_PATH: "99676"}})
        self.assertEqual(
            bool_query["should"][1]["bool"]["must"][0],
            {"match_phrase": {URNS_PATH: "9676"}},
        )


class SearchContactsElasticUseCaseTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.client = Mock()
        self.usecase = SearchContactsElasticUseCase(client=self.client)

    @patch("temba.api.v2.elasticsearch.usecases.Search")
    def test_execute_returns_paginated_results(self, mock_search_cls):
        mock_hit = Mock()
        mock_hit.to_dict.return_value = {"name": "John", "uuid": "abc"}
        mock_response = Mock()
        mock_response.__iter__ = Mock(return_value=iter([mock_hit]))
        mock_response.hits.total.value = 25

        mock_search = mock_search_cls.return_value
        mock_search.query.return_value = mock_search
        mock_search.__getitem__.return_value = mock_search
        mock_search.execute.return_value = mock_response

        result = self.usecase.execute(
            org_id=1,
            name="John",
            page_number=2,
            page_size=10,
            base_url="http://test/contacts?page=1",
        )

        self.assertEqual(result["results"], [{"name": "John", "uuid": "abc"}])
        self.assertEqual(result["pagination"]["page_number"], 2)
        self.assertEqual(result["pagination"]["page_size"], 10)
        self.assertEqual(result["pagination"]["total_pages"], 3)
        self.assertIn("next", result["pagination"]["links"])
        self.assertIn("previous", result["pagination"]["links"])
        mock_search_cls.assert_called_once_with(using=self.client, index="contacts")

    def test_execute_rejects_invalid_pagination(self):
        with self.assertRaises(ValueError):
            self.usecase.execute(org_id=1, page_size=0)
        with self.assertRaises(ValueError):
            self.usecase.execute(org_id=1, page_number=0)

    @patch("temba.api.v2.elasticsearch.usecases.Search")
    def test_execute_first_page_has_no_previous_link(self, mock_search_cls):
        mock_response = Mock()
        mock_response.__iter__ = Mock(return_value=iter([]))
        mock_response.hits.total.value = 5

        mock_search = mock_search_cls.return_value
        mock_search.query.return_value = mock_search
        mock_search.__getitem__.return_value = mock_search
        mock_search.execute.return_value = mock_response

        result = self.usecase.execute(org_id=1, name="John", page_number=1, page_size=10)

        self.assertEqual(result["pagination"]["total_pages"], 1)
        self.assertNotIn("previous", result["pagination"]["links"])
        self.assertNotIn("next", result["pagination"]["links"])

    @patch("temba.api.v2.elasticsearch.usecases.Search")
    def test_execute_last_page_has_no_next_link(self, mock_search_cls):
        mock_response = Mock()
        mock_response.__iter__ = Mock(return_value=iter([]))
        mock_response.hits.total.value = 25

        mock_search = mock_search_cls.return_value
        mock_search.query.return_value = mock_search
        mock_search.__getitem__.return_value = mock_search
        mock_search.execute.return_value = mock_response

        result = self.usecase.execute(org_id=1, name="John", page_number=3, page_size=10)

        self.assertEqual(result["pagination"]["total_pages"], 3)
        self.assertIn("previous", result["pagination"]["links"])
        self.assertNotIn("next", result["pagination"]["links"])

    @patch("temba.api.v2.elasticsearch.usecases.Search")
    def test_execute_number_only(self, mock_search_cls):
        mock_response = Mock()
        mock_response.__iter__ = Mock(return_value=iter([]))
        mock_response.hits.total.value = 0

        mock_search = mock_search_cls.return_value
        mock_search.query.return_value = mock_search
        mock_search.__getitem__.return_value = mock_search
        mock_search.execute.return_value = mock_response

        result = self.usecase.execute(org_id=7, number="84981204567")

        self.assertEqual(result["results"], [])
        self.assertEqual(result["pagination"]["total_pages"], 0)
        mock_search.query.assert_called_once()

    @override_settings(ELASTICSEARCH_URL="http://es.test:9200", ELASTICSEARCH_TIMEOUT_REQUEST=15)
    @patch("temba.api.v2.elasticsearch.usecases.Elasticsearch")
    @patch("temba.api.v2.elasticsearch.usecases.Search")
    def test_create_client_when_not_injected(self, mock_search_cls, mock_elasticsearch_cls):
        mock_response = Mock()
        mock_response.__iter__ = Mock(return_value=iter([]))
        mock_response.hits.total.value = 0

        mock_search = mock_search_cls.return_value
        mock_search.query.return_value = mock_search
        mock_search.__getitem__.return_value = mock_search
        mock_search.execute.return_value = mock_response

        usecase = SearchContactsElasticUseCase()
        usecase.execute(org_id=1, name="John")

        mock_elasticsearch_cls.assert_called_once_with("http://es.test:9200", timeout=15)

    def test_build_filters_org_id_only(self):
        filters = self.usecase._build_filters(org_id=42, name=None, number=None)

        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0].to_dict(), {"match": {"org_id": 42}})

    def test_build_filters_name_only(self):
        filters = self.usecase._build_filters(org_id=42, name="Ana", number=None)

        self.assertEqual(len(filters), 3)
        self.assertEqual(filters[1].to_dict(), {"match_phrase": {"name": "Ana"}})
        self.assertEqual(filters[2].to_dict(), {"exists": {"field": "name"}})

    def test_build_filters_skips_invalid_number_query(self):
        number_usecase = Mock()
        number_usecase.execute.return_value = None
        usecase = SearchContactsElasticUseCase(client=self.client, number_query_usecase=number_usecase)

        filters = usecase._build_filters(org_id=42, name=None, number="abc")

        self.assertEqual(len(filters), 1)
        number_usecase.execute.assert_called_once_with("abc")

    def test_default_number_query_usecase(self):
        usecase = SearchContactsElasticUseCase(client=self.client)

        self.assertIsInstance(usecase._number_query_usecase, BuildContactNumberQueryUseCase)

    def test_build_filters_includes_name_and_number(self):
        number_usecase = Mock()
        number_usecase.execute.return_value = {"nested": "query"}
        usecase = SearchContactsElasticUseCase(client=self.client, number_query_usecase=number_usecase)

        filters = usecase._build_filters(org_id=42, name="Ana", number="84981204567")

        self.assertEqual(len(filters), 4)
        self.assertEqual(filters[0].to_dict(), {"match": {"org_id": 42}})
        self.assertEqual(filters[1].to_dict(), {"match_phrase": {"name": "Ana"}})
        self.assertEqual(filters[2].to_dict(), {"exists": {"field": "name"}})
        number_usecase.execute.assert_called_once_with("84981204567")
