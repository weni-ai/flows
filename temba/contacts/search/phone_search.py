import json
import re

from temba.utils.whatsapp.ninth_digit import get_number_search_terms

from .mailroom import SearchResults, search_contacts

WHATSAPP_SCHEME = "whatsapp"
TEL_SCHEME = "tel"

_CONTACTQL_HINTS = re.compile(r"[~>=]|(?:^|\s)(?:and|or|not)\s", re.I)
_SCHEME_HINTS = re.compile(r"(?:^|\s)(?:tel|whatsapp|twitter|email|facebook|instagram|telegram|discord)\s*[=~]", re.I)
_IMPLICIT_PHONE = re.compile(r"^\+?[-\d]{4,}$")


class ContactSearchOutcome:
    __slots__ = ("results", "phone_fallback")

    def __init__(self, results: SearchResults, phone_fallback: bool = False):
        self.results = results
        self.phone_fallback = phone_fallback


def is_bare_phone_search(query: str, org) -> bool:
    """
    Returns whether the query is a bare phone number rather than a contactql expression.
    """
    query = (query or "").strip()
    if not query or _SCHEME_HINTS.search(query) or _CONTACTQL_HINTS.search(query):
        return False

    if _IMPLICIT_PHONE.match(query):
        return True

    from temba.contacts.models import URN

    return URN.looks_like_phone(query, org.default_country_code)


def build_phone_urn_query(scheme: str, raw_query: str) -> str:
    """
    Builds a contactql partial URN query for the given scheme and phone-like input.
    """
    terms = get_number_search_terms(raw_query)
    digits = terms["literal"]
    if not digits:
        raise ValueError("phone search requires digits")

    clauses = [f"{scheme} ~ {json.dumps(digits)}"]

    if scheme == WHATSAPP_SCHEME and terms["whatsapp_variant"]:
        clauses.append(f"{scheme} ~ {json.dumps(terms['whatsapp_variant'])}")

    if len(clauses) == 1:
        return clauses[0]

    return f"({' OR '.join(clauses)})"


def search_contacts_resolving_phone(
    org, query: str, *, group=None, sort: str = None, offset: int = None, exclude_ids=()
) -> ContactSearchOutcome:
    """
    Runs contact search, resolving bare phone numbers on WhatsApp URNs first and tel URNs second.
    """
    if not is_bare_phone_search(query, org):
        return ContactSearchOutcome(
            search_contacts(org, query, group=group, sort=sort, offset=offset, exclude_ids=exclude_ids)
        )

    search_kwargs = dict(group=group, sort=sort, offset=offset, exclude_ids=exclude_ids)

    whatsapp_query = build_phone_urn_query(WHATSAPP_SCHEME, query)
    whatsapp_results = search_contacts(org, whatsapp_query, **search_kwargs)
    if whatsapp_results.total > 0:
        return ContactSearchOutcome(whatsapp_results)

    tel_query = build_phone_urn_query(TEL_SCHEME, query)
    tel_results = search_contacts(org, tel_query, **search_kwargs)
    return ContactSearchOutcome(tel_results, phone_fallback=True)
