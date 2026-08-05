from unittest.mock import patch

from temba.contacts.models import URN
from temba.mailroom import MailroomException
from temba.tests import TembaTest, mock_mailroom

from . import SearchException, SearchResults, elastic
from .phone_search import build_phone_urn_query, is_bare_phone_search, search_contacts_resolving_phone


class PhoneSearchTest(TembaTest):
    def test_is_bare_phone_search(self):
        self.assertTrue(is_bare_phone_search("987654321", self.org))
        self.assertTrue(is_bare_phone_search("+250781111111", self.org))
        self.assertFalse(is_bare_phone_search("Joe", self.org))
        self.assertFalse(is_bare_phone_search("age = 18", self.org))
        self.assertFalse(is_bare_phone_search("tel ~ 1234", self.org))
        self.assertFalse(is_bare_phone_search("whatsapp:5586987654321", self.org))
        self.assertFalse(is_bare_phone_search("BR.35029025746744354", self.org))

    def test_build_phone_urn_query(self):
        self.assertEqual(build_phone_urn_query(URN.WHATSAPP_SCHEME, "987654321"), 'whatsapp ~ "987654321"')
        self.assertEqual(build_phone_urn_query(URN.TEL_SCHEME, "987654321"), 'tel ~ "987654321"')

    @patch("temba.contacts.search.phone_search.search_contacts")
    def test_search_contacts_resolving_phone(self, mock_search_contacts):
        whatsapp_query = build_phone_urn_query(URN.WHATSAPP_SCHEME, "987654321")
        tel_query = build_phone_urn_query(URN.TEL_SCHEME, "987654321")

        mock_search_contacts.side_effect = [
            SearchResults(query=whatsapp_query, total=1, contact_ids=[1]),
            SearchResults(query=tel_query, total=1, contact_ids=[2]),
            SearchResults(query='name ~ "Joe"', total=1, contact_ids=[3]),
        ]

        outcome = search_contacts_resolving_phone(self.org, "987654321")
        self.assertFalse(outcome.phone_fallback)
        self.assertEqual(outcome.results.contact_ids, [1])
        mock_search_contacts.assert_called_once_with(
            self.org, whatsapp_query, group=None, sort=None, offset=None, exclude_ids=()
        )

        mock_search_contacts.reset_mock()
        mock_search_contacts.side_effect = [
            SearchResults(query=whatsapp_query, total=0, contact_ids=[]),
            SearchResults(query=tel_query, total=1, contact_ids=[2]),
        ]

        outcome = search_contacts_resolving_phone(self.org, "987654321")
        self.assertTrue(outcome.phone_fallback)
        self.assertEqual(outcome.results.contact_ids, [2])
        self.assertEqual(mock_search_contacts.call_count, 2)

        mock_search_contacts.reset_mock()
        mock_search_contacts.return_value = SearchResults(query='name ~ "Joe"', total=1, contact_ids=[3])

        outcome = search_contacts_resolving_phone(self.org, "Joe")
        self.assertFalse(outcome.phone_fallback)
        mock_search_contacts.assert_called_once_with(
            self.org, "Joe", group=None, sort=None, offset=None, exclude_ids=()
        )


class SearchExceptionTest(TembaTest):
    def test_str(self):
        tests = (
            (
                {
                    "error": "mismatched input '$' expecting {'(', TEXT, STRING}",
                    "code": "unexpected_token",
                    "extra": {"token": "$"},
                },
                "Invalid query syntax at '$'",
            ),
            (
                {"error": "can't convert 'XZ' to a number", "code": "invalid_number", "extra": {"value": "XZ"}},
                "Unable to convert 'XZ' to a number",
            ),
            (
                {"error": "can't convert 'AB' to a date", "code": "invalid_date", "extra": {"value": "AB"}},
                "Unable to convert 'AB' to a date",
            ),
            (
                {
                    "error": "'Cool Kids' is not a valid group name",
                    "code": "invalid_group",
                    "extra": {"value": "Cool Kids"},
                },
                "'Cool Kids' is not a valid group name",
            ),
            (
                {
                    "error": "'zzzzzz' is not a valid language code",
                    "code": "invalid_language",
                    "extra": {"value": "zzzz"},
                },
                "'zzzz' is not a valid language code",
            ),
            (
                {
                    "error": "contains operator on name requires token of minimum length 2",
                    "code": "invalid_partial_name",
                    "extra": {"min_token_length": "2"},
                },
                "Using ~ with name requires token of at least 2 characters",
            ),
            (
                {
                    "error": "contains operator on URN requires value of minimum length 3",
                    "code": "invalid_partial_urn",
                    "extra": {"min_value_length": "3"},
                },
                "Using ~ with URN requires value of at least 3 characters",
            ),
            (
                {
                    "error": "contains conditions can only be used with name or URN values",
                    "code": "unsupported_contains",
                    "extra": {"property": "uuid"},
                },
                "Can only use ~ with name or URN values",
            ),
            (
                {
                    "error": "comparisons with > can only be used with date and number fields",
                    "code": "unsupported_comparison",
                    "extra": {"property": "uuid", "operator": ">"},
                },
                "Can only use > with number or date values",
            ),
            (
                {
                    "error": "can't check whether 'uuid' is set or not set",
                    "code": "unsupported_setcheck",
                    "extra": {"property": "uuid", "operator": "!="},
                },
                "Can't check whether 'uuid' is set or not set",
            ),
            (
                {
                    "error": "can't resolve 'beers' to attribute, scheme or field",
                    "code": "unknown_property",
                    "extra": {"property": "beers"},
                },
                "Can't resolve 'beers' to a field or URN scheme",
            ),
            (
                {"error": "cannot query on redacted URNs", "code": "redacted_urns"},
                "Can't query on URNs in an anonymous workspace",
            ),
            ({"error": "no code here"}, "no code here"),
        )

        for response, message in tests:
            e = MailroomException("parse_query", None, response)
            e = SearchException.from_mailroom_exception(e)

            self.assertEqual(message, str(e))


class TestElastic(TembaTest):
    @mock_mailroom
    def test_query_elasticsearch_for_ids_bad_query(self, mr_mocks):
        with self.assertRaises(SearchException):
            mr_mocks.error("bad field <> error")
            elastic.query_contact_ids(self.org, "bad_field <> error")
