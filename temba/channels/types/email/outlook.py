import base64
import hashlib
import logging
import re
import secrets
from urllib.parse import urlencode

import jwt
import requests
import sentry_sdk

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone

from temba.channels.models import Channel

logger = logging.getLogger(__name__)

CONSENT_ATTEMPT_TTL_SECONDS = 900
MICROSOFT_HTTP_TIMEOUT_SECONDS = 10
OAUTH_PROVIDER_MICROSOFT = "microsoft"
OAUTH_STATUS_ACTIVE = "active"
OAUTH_STATUS_NEEDS_RECONNECT = "needs_reconnect"

IMAP_HOST = "outlook.office365.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.office365.com"
SMTP_HOST_PERSONAL = "smtp-mail.outlook.com"
SMTP_PORT = 587

SCOPES = (
    "offline_access",
    "https://outlook.office.com/IMAP.AccessAsUser.All",
    "https://outlook.office.com/SMTP.Send",
)

AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
JWKS_URL = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
OUTLOOK_AUDIENCE = "https://outlook.office.com"
ADMIN_CONSENT_URL = "https://login.microsoftonline.com/common/adminconsent"
ATTEMPT_KEY_PREFIX = "outlook-email-consent:"
ISSUER_PREFIX = "https://login.microsoftonline.com/"
MAILBOX_CLAIMS = ("upn", "preferred_username", "unique_name")
_SAFE_ERROR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,80}")


class ConsentError(Exception):
    def __init__(
        self,
        code,
        *,
        description=None,
        show_description=False,
        admin_consent=False,
        log=True,
        report=False,
        logged_code=None,
    ):
        super().__init__(code)
        self.code = code
        self.description = description
        self.show_description = show_description
        self.admin_consent = admin_consent
        self.log = log
        self.report = report
        self.logged_code = logged_code or code


def safe_error_code(error_code):
    code = str(error_code or "")
    if _SAFE_ERROR_CODE.fullmatch(code):
        return code
    return "error"


def attempt_key(state):
    return f"{ATTEMPT_KEY_PREFIX}{state}"


def normalize_mailbox(value):
    if value is None:
        return None
    mailbox = str(value).strip().lower()
    if "@" not in mailbox:
        return None
    return mailbox


def put_attempt(org_id, user_id, username, code_verifier):
    state = secrets.token_urlsafe(32)
    cache.set(
        attempt_key(state),
        {
            "org_id": org_id,
            "user_id": user_id,
            "username": username,
            "code_verifier": code_verifier,
        },
        CONSENT_ATTEMPT_TTL_SECONDS,
    )
    return state


def pop_attempt(state):
    if not state:
        return None
    key = attempt_key(state)
    payload = cache.get(key)
    if payload is None:
        return None
    cache.delete(key)
    return payload


def code_challenge_for(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def admin_consent_link():
    return f"{ADMIN_CONSENT_URL}?client_id={settings.APP_MICROSOFT_CLIENT_ID}"


def account_identifier(org):
    project_id = getattr(org, "proj_uuid", None)
    if project_id:
        return str(project_id)
    return None


def correlation_identifier(request):
    return request.META.get("HTTP_X_REQUEST_ID") or request.META.get("HTTP_X_CORRELATION_ID") or None


def needs_admin_consent(error, description):
    if error == "consent_required":
        return True
    text = f"{error or ''} {description or ''}"
    return "AADSTS65001" in text


def record_failure(org_id, user_id, error_code, account_id=None, correlation_id=None, report=False):
    code = safe_error_code(error_code)
    log = logger.warning if report else logger.info
    log("outlook consent failed org_id=%s user_id=%s error=%s", org_id, user_id, code)
    if not report:
        return
    with sentry_sdk.push_scope() as scope:
        scope.set_tag("org_id", org_id)
        scope.set_tag("user_id", user_id)
        scope.set_tag("microsoft_error", code)
        if account_id:
            scope.set_tag("account_id", account_id)
        if correlation_id:
            scope.set_tag("correlation_id", correlation_id)
        sentry_sdk.capture_message("outlook consent failed")


def begin(org, user, username, redirect_uri):
    mailbox = normalize_mailbox(username)
    if not mailbox:
        raise ConsentError("invalid_address", log=False)
    verifier = secrets.token_urlsafe(64)
    state = put_attempt(org.id, user.id, mailbox, verifier)
    return _authorize_url(redirect_uri, state, code_challenge_for(verifier))


def rejection_from_provider(error, description):
    code = safe_error_code(error)
    if needs_admin_consent(error, description):
        return ConsentError(code, admin_consent=True, log=False)
    if description:
        return ConsentError(code, description=description, show_description=True, log=False)
    return ConsentError(code, log=False)


def complete(org, user, code, state, redirect_uri, account_id=None, correlation_id=None):
    try:
        return _complete(org, user, code, state, redirect_uri)
    except ConsentError as exc:
        if exc.log:
            record_failure(
                org.id,
                user.id,
                exc.logged_code,
                account_id=account_id,
                correlation_id=correlation_id,
                report=exc.report,
            )
        raise


def _authorize_url(redirect_uri, state, challenge):
    query = urlencode(
        {
            "client_id": settings.APP_MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(SCOPES),
            "state": state,
            "prompt": "select_account",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def _complete(org, user, code, state, redirect_uri):
    attempt = pop_attempt(state)
    if attempt is None or not code:
        raise ConsentError("state")
    if attempt["org_id"] != org.id or attempt["user_id"] != user.id:
        raise ConsentError("state")

    access_token, refresh_token = _exchange_code(code, attempt["code_verifier"], redirect_uri)
    mailbox = _mailbox_from_access_token(access_token)
    if mailbox is not None and mailbox != attempt["username"]:
        raise ConsentError("mailbox_mismatch")
    return _save_channel(
        org, user, attempt["username"], access_token, refresh_token, _smtp_host(access_token)
    )


def _exchange_code(code, verifier, redirect_uri):
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": settings.APP_MICROSOFT_CLIENT_ID,
                "client_secret": settings.APP_MICROSOFT_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=MICROSOFT_HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        raise ConsentError("token", report=True)

    try:
        payload = response.json()
    except ValueError:
        raise ConsentError("token", report=True)

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if response.status_code != 200 or not access_token or not refresh_token:
        raise ConsentError("token", report=True, logged_code=safe_error_code(payload.get("error") or "token"))
    return access_token, refresh_token


def _is_jwt(access_token):
    return isinstance(access_token, str) and access_token.count(".") == 2


def _smtp_host(access_token):
    if _is_jwt(access_token):
        return SMTP_HOST
    return SMTP_HOST_PERSONAL


def _mailbox_from_access_token(access_token):
    # Personal Microsoft accounts receive an opaque (non-JWT) access token for
    # the Outlook resource, so the mailbox cannot be read from it. The caller
    # then trusts the address the admin confirmed before the redirect.
    if not _is_jwt(access_token):
        return None

    try:
        signing_key = jwt.PyJWKClient(JWKS_URL).get_signing_key_from_jwt(access_token)
        claims = jwt.decode(
            access_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=OUTLOOK_AUDIENCE,
            options={"verify_iss": False},
        )
    except jwt.InvalidAudienceError:
        raise ConsentError("invalid_token", report=True, logged_code="token_audience")
    except jwt.PyJWTError:
        raise ConsentError("invalid_token", report=True, logged_code="token_signature")

    issuer = claims.get("iss") or ""
    if not (issuer.startswith(ISSUER_PREFIX) and issuer.endswith("/v2.0")):
        raise ConsentError("invalid_token", report=True, logged_code="token_issuer")

    mailbox = _mailbox_claim(claims)
    if not mailbox:
        raise ConsentError("invalid_token", report=True, logged_code="token_mailbox")
    return mailbox


def _mailbox_claim(claims):
    for key in MAILBOX_CLAIMS:
        value = claims.get(key)
        if isinstance(value, str) and "@" in value:
            return value.strip().lower()
    return None


def _save_channel(org, user, username, access_token, refresh_token, smtp_host):
    with transaction.atomic():
        _lock_mailbox(org.id, username)
        existing = (
            Channel.objects.select_for_update()
            .filter(org=org, is_active=True, channel_type="EM", address__iexact=username)
            .first()
        )
        if existing:
            config = dict(existing.config or {})
            if (
                config.get("oauth_provider") == OAUTH_PROVIDER_MICROSOFT
                and config.get("oauth_status") == OAUTH_STATUS_NEEDS_RECONNECT
            ):
                config["access_token"] = access_token
                config["refresh_token"] = refresh_token
                config["smtp_host"] = smtp_host
                config["oauth_status"] = OAUTH_STATUS_ACTIVE
                config["password"] = ""
                existing.config = config
                existing.modified_by = user
                existing.modified_on = timezone.now()
                existing.save(update_fields=("config", "modified_by", "modified_on"))
                return existing
            raise ConsentError("already_connected")

        return Channel.create(
            org,
            user,
            None,
            "EM",
            name=username,
            address=username,
            config=_channel_config(username, access_token, refresh_token, smtp_host),
        )


def _channel_config(username, access_token, refresh_token, smtp_host):
    return {
        "username": username,
        "password": "",
        "smtp_host": smtp_host,
        "smtp_port": SMTP_PORT,
        "imap_host": IMAP_HOST,
        "imap_port": IMAP_PORT,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "oauth_provider": OAUTH_PROVIDER_MICROSOFT,
        "oauth_status": OAUTH_STATUS_ACTIVE,
        "callback_domain": settings.HOSTNAME,
    }


def _lock_mailbox(org_id, address):
    raw = int(hashlib.sha256(address.encode("utf-8")).hexdigest()[:8], 16)
    if raw >= 2**31:
        raw -= 2**32
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [int(org_id), int(raw)])
