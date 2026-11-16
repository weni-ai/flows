#!/usr/bin/env python3
"""Gera dois access tokens da mesma conta Outlook, gravados juntos.

O Graph e o IMAP são recursos diferentes, então a Microsoft não entrega os
dois acessos num único access_token. O login pede consentimento para os dois.
A troca do código pede o token de Mail.Send. O refresh_token, que vale para
os recursos já consentidos, pede em seguida o token de IMAP.

O redirect URI precisa estar cadastrado no app, em Authentication.
O padrão é http://localhost:8400/callback.

Exemplos:
  python get_tokens.py
  python get_tokens.py --scope Mail.Read
  python get_tokens.py --refresh
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterable

GRAPH_SCOPE_PREFIX = "https://graph.microsoft.com/"
OUTLOOK_SCOPE_PREFIX = "https://outlook.office.com/"
RESERVED_SCOPES = {"openid", "profile", "email", "offline_access"}
OUTLOOK_SHORT_NAMES = {
    "imap.accessasuser.all": "IMAP.AccessAsUser.All",
    "pop.accessasuser.all": "POP.AccessAsUser.All",
    "smtp.send": "SMTP.Send",
}
GRAPH_MAIL_SEND = "https://graph.microsoft.com/Mail.Send"
IMAP_ACCESS = "https://outlook.office.com/IMAP.AccessAsUser.All"
DEFAULT_REDIRECT_URI = "http://localhost:8400/callback"
DEFAULT_OUTPUT = "tokens.json"
AUTHORIZE_TIMEOUT_SECONDS = 180


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize_scope(raw: str) -> str:
    scope = raw.strip()
    if not scope:
        raise ValueError("escopo vazio")

    key = scope.lower()
    if key in {"offline", "offline_access"}:
        return "offline_access"
    if key in RESERVED_SCOPES:
        return key
    if key in OUTLOOK_SHORT_NAMES:
        return f"{OUTLOOK_SCOPE_PREFIX}{OUTLOOK_SHORT_NAMES[key]}"
    if "://" in scope:
        return scope
    return f"{GRAPH_SCOPE_PREFIX}{scope.lstrip('/')}"


def build_scopes(requested: Iterable[str]) -> list[str]:
    scopes = ["offline_access"]
    seen = {"offline_access"}
    for raw in requested:
        scope = normalize_scope(raw)
        if scope in seen:
            continue
        seen.add(scope)
        scopes.append(scope)
    return scopes


def is_outlook_scope(scope: str) -> bool:
    lowered = scope.lower()
    return lowered.startswith(OUTLOOK_SCOPE_PREFIX) or lowered.startswith("https://outlook.office365.com/")


def profile_scopes(requested: Iterable[str]) -> tuple[list[str], list[str]]:
    graph_extra: list[str] = []
    imap_extra: list[str] = []
    for raw in requested:
        scope = normalize_scope(raw)
        if scope == "offline_access":
            continue
        if is_outlook_scope(scope):
            imap_extra.append(scope)
        else:
            graph_extra.append(scope)
    return build_scopes([GRAPH_MAIL_SEND, *graph_extra]), build_scopes([IMAP_ACCESS, *imap_extra])


def consent_scopes(graph_scopes: Iterable[str], imap_scopes: Iterable[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for scope in [*graph_scopes, *imap_scopes]:
        if scope in seen:
            continue
        seen.add(scope)
        merged.append(scope)
    return merged


def split_scopes(value: str) -> list[str]:
    chunks = value.replace(",", " ").split()
    return [chunk for chunk in chunks if chunk]


def env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def authorize_url(
    tenant: str,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    state: str,
    code_challenge: str,
    prompt: str,
) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": prompt,
        },
        quote_via=urllib.parse.quote,
    )
    return f"https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/authorize?{query}"


def token_endpoint(tenant: str) -> str:
    return f"https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/token"


def post_form(url: str, fields: dict[str, str]) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            raise SystemExit(f"Falha no token endpoint ({exc.code}): {payload}") from exc
        description = parsed.get("error_description") or parsed.get("error") or payload
        raise SystemExit(f"Falha no token endpoint: {description}") from exc


def exchange_code(
    tenant: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
    scopes: list[str],
) -> dict:
    return post_form(
        token_endpoint(tenant),
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "scope": " ".join(scopes),
        },
    )


def refresh_tokens(
    tenant: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    scopes: list[str],
) -> dict:
    return post_form(
        token_endpoint(tenant),
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(scopes),
        },
    )


class CallbackResult:
    def __init__(self) -> None:
        self.code: str | None = None
        self.error: str | None = None
        self.error_description: str | None = None


class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def wait_for_code(redirect_uri: str, expected_state: str, timeout: int) -> str:
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise SystemExit(
            "O redirect local precisa ser http://localhost ou http://127.0.0.1. "
            "Para outro URI já cadastrado no app, rode com --paste."
        )

    host = "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    result = CallbackResult()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            incoming = urllib.parse.urlparse(self.path)
            if incoming.path != path:
                self._send(404, "Caminho inesperado. Feche esta janela e tente de novo.")
                return
            if result.code or result.error:
                self._send(200, "Login já recebido. Pode fechar esta janela.")
                return

            query = urllib.parse.parse_qs(incoming.query)
            returned_state = query.get("state", [""])[0]
            if not secrets.compare_digest(returned_state, expected_state):
                result.error = "state_mismatch"
                result.error_description = "O state do retorno não confere com o pedido."
                self._send(400, "State inválido. Volte ao terminal.")
                return

            if "error" in query:
                result.error = query["error"][0]
                result.error_description = query.get("error_description", [""])[0]
                self._send(400, "A Microsoft recusou o login. Veja o terminal.")
                return

            code = query.get("code", [None])[0]
            if not code:
                result.error = "missing_code"
                result.error_description = "O retorno não trouxe o parâmetro code."
                self._send(400, "Retorno sem code. Volte ao terminal.")
                return

            result.code = code
            self._send(200, "Login concluído. Pode fechar esta janela e voltar ao terminal.")

        def _send(self, status: int, message: str) -> None:
            body = (
                "<!doctype html><meta charset='utf-8'>"
                f"<title>Outlook OAuth</title><p>{message}</p>"
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    try:
        server = ReusableHTTPServer((host, port), Handler)
    except OSError as exc:
        raise SystemExit(
            f"Não foi possível escutar em {host}:{port} ({exc}). "
            "Feche o que estiver usando a porta ou escolha outro --redirect-uri."
        ) from exc

    server.timeout = 1
    deadline = time.time() + timeout
    print(f"Aguardando o retorno em {redirect_uri} ({timeout}s)...", file=sys.stderr)
    try:
        while time.time() < deadline and result.code is None and result.error is None:
            server.handle_request()
    finally:
        server.server_close()

    if result.error:
        detail = result.error_description or result.error
        raise SystemExit(f"Autorização recusada: {detail}")
    if not result.code:
        raise SystemExit("Tempo esgotado esperando o login no navegador.")
    return result.code


def code_from_pasted_url(expected_state: str) -> str:
    print("Cole aqui a URL completa para a qual o navegador foi redirecionado:", file=sys.stderr)
    pasted = input().strip()
    parsed = urllib.parse.urlparse(pasted)
    query = urllib.parse.parse_qs(parsed.query)
    if not query and parsed.fragment:
        query = urllib.parse.parse_qs(parsed.fragment)

    returned_state = query.get("state", [""])[0]
    if expected_state and returned_state and not secrets.compare_digest(returned_state, expected_state):
        raise SystemExit("O state da URL colada não confere com o pedido.")
    if "error" in query:
        detail = query.get("error_description", query["error"])[0]
        raise SystemExit(f"Autorização recusada: {detail}")
    code = query.get("code", [None])[0]
    if not code:
        raise SystemExit("A URL colada não contém o parâmetro code.")
    return code


def public_token_payload(token_response: dict, tenant: str, previous: dict | None = None) -> dict:
    now = int(time.time())
    expires_in = int(token_response.get("expires_in") or 0)
    refresh_token = token_response.get("refresh_token")
    if not refresh_token and previous:
        refresh_token = previous.get("refresh_token")

    payload = {
        "token_type": token_response.get("token_type"),
        "scope": token_response.get("scope"),
        "expires_in": expires_in,
        "obtained_at": now,
        "expires_at": now + expires_in if expires_in else None,
        "access_token": token_response.get("access_token"),
        "refresh_token": refresh_token,
        "tenant": tenant,
    }
    if token_response.get("id_token"):
        payload["id_token"] = token_response["id_token"]
    return payload


def write_tokens(path: str, payload: dict) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.chmod(path, 0o600)


def read_tokens(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise SystemExit(f"Arquivo de tokens não encontrado: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON inválido em {path}: {exc}") from exc


def latest_refresh_token(data: dict | None) -> str | None:
    if not isinstance(data, dict):
        return None
    if data.get("refresh_token"):
        return str(data["refresh_token"])
    for key in ("imap", "graph"):
        block = data.get(key)
        if isinstance(block, dict) and block.get("refresh_token"):
            return str(block["refresh_token"])
    return None


def nested_token(data: dict | None, key: str) -> dict | None:
    if not isinstance(data, dict):
        return None
    block = data.get(key)
    return block if isinstance(block, dict) else None


def paired_store(tenant: str, refresh_token: str | None, graph: dict, imap: dict | None) -> dict:
    payload = {
        "tenant": tenant,
        "refresh_token": refresh_token,
        "graph": graph,
    }
    if imap:
        payload["imap"] = imap
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Gera dois access tokens da mesma conta: Mail.Send no Graph para envio "
            "e IMAP.AccessAsUser.All para leitura. offline_access entra nos dois."
        ),
        epilog=(
            "No Entra ID, cadastre o redirect URI (padrão "
            f"{DEFAULT_REDIRECT_URI}) em Authentication e permita o fluxo "
            "de contas que você quer usar. O secret usado é o Value do client secret, "
            "não o Secret ID."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--client-id", help="Client ID do app. Env: CLIENT_ID ou AZURE_CLIENT_ID.")
    parser.add_argument(
        "--client-secret",
        help="Secret value do app. Env: SECRET_VALUE ou AZURE_CLIENT_SECRET.",
    )
    parser.add_argument(
        "--tenant",
        help="Tenant ID, ou common, organizations, consumers. Env: TENANT_ID. Padrão: common.",
    )
    parser.add_argument(
        "--redirect-uri",
        help=f"Redirect URI cadastrado no app. Padrão: {DEFAULT_REDIRECT_URI}.",
    )
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help=(
            "Escopo extra, repetível. Escopos do Graph vão para o token de envio. "
            "IMAP.AccessAsUser.All, SMTP.Send e URLs do outlook.office.com vão para "
            "o token de IMAP. Mail.Send e o acesso IMAP já entram sempre. "
            "Env alternativa: SCOPES, separado por espaço ou vírgula."
        ),
    )
    parser.add_argument(
        "--prompt",
        default="consent",
        choices=("consent", "select_account", "login", "none"),
        help="Parâmetro prompt do authorize. Padrão: consent, para garantir o refresh_token.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"Arquivo JSON de saída. Padrão: {DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=AUTHORIZE_TIMEOUT_SECONDS,
        help="Segundos esperando o retorno do navegador.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Não abre o navegador; só imprime a URL de autorização.",
    )
    parser.add_argument(
        "--paste",
        action="store_true",
        help="Não sobe servidor local. Depois do login, cole a URL de retorno.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Renova os access tokens de Graph e IMAP com o refresh_token salvo.",
    )
    parser.add_argument(
        "--refresh-token",
        help="Refresh token usado com --refresh. Se omitido, lê --output.",
    )
    return parser.parse_args()


def resolve_config(args: argparse.Namespace) -> dict:
    load_dotenv()
    client_id = args.client_id or env_first("CLIENT_ID", "AZURE_CLIENT_ID")
    client_secret = args.client_secret or env_first("SECRET_VALUE", "AZURE_CLIENT_SECRET")
    tenant = args.tenant or env_first("TENANT_ID", "AZURE_TENANT_ID") or "common"
    redirect_uri = args.redirect_uri or env_first("REDIRECT_URI") or DEFAULT_REDIRECT_URI
    output = args.output or env_first("TOKEN_OUTPUT") or DEFAULT_OUTPUT

    requested = list(args.scope)
    if not requested:
        from_env = env_first("SCOPES")
        requested = split_scopes(from_env) if from_env else []
    graph_scopes, imap_scopes = profile_scopes(requested)

    missing = []
    if not client_id:
        missing.append("CLIENT_ID / --client-id")
    if not client_secret:
        missing.append("SECRET_VALUE / --client-secret")
    if missing:
        raise SystemExit("Faltando: " + ", ".join(missing) + ". Veja .env.example.")

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "tenant": tenant,
        "redirect_uri": redirect_uri,
        "output": output,
        "graph_scopes": graph_scopes,
        "imap_scopes": imap_scopes,
        "consent_scopes": consent_scopes(graph_scopes, imap_scopes),
    }


def require_access_token(payload: dict, resource: str) -> None:
    if not payload.get("access_token"):
        raise SystemExit(f"A resposta de {resource} não trouxe access_token.")


def add_imap_token(config: dict, graph_payload: dict, refresh_token: str | None, previous: dict | None) -> dict:
    if not refresh_token:
        raise SystemExit(
            "A resposta do Graph não trouxe refresh_token. Sem ele não dá para "
            "pedir o token de IMAP. Confira se offline_access foi consentido."
        )
    try:
        imap_response = refresh_tokens(
            tenant=config["tenant"],
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            refresh_token=refresh_token,
            scopes=config["imap_scopes"],
        )
    except SystemExit as exc:
        partial = paired_store(
            config["tenant"],
            refresh_token,
            graph_payload,
            nested_token(previous, "imap"),
        )
        write_tokens(config["output"], partial)
        raise SystemExit(
            f"{exc}\nO token do Graph foi salvo, mas o de IMAP não. "
            "Confira o consentimento de IMAP.AccessAsUser.All e rode "
            "python3 get_tokens.py --refresh."
        ) from exc

    imap_payload = public_token_payload(imap_response, config["tenant"], nested_token(previous, "imap"))
    require_access_token(imap_payload, "IMAP")
    latest_refresh = imap_payload.get("refresh_token") or refresh_token
    return paired_store(config["tenant"], latest_refresh, graph_payload, imap_payload)


def login(args: argparse.Namespace, config: dict) -> dict:
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    url = authorize_url(
        tenant=config["tenant"],
        client_id=config["client_id"],
        redirect_uri=config["redirect_uri"],
        scopes=config["consent_scopes"],
        state=state,
        code_challenge=challenge,
        prompt=args.prompt,
    )
    print("Consentimento:", " ".join(config["consent_scopes"]), file=sys.stderr)
    print(url, file=sys.stderr)
    if not args.no_browser and not args.paste:
        webbrowser.open(url)

    if args.paste:
        code = code_from_pasted_url(state)
    else:
        code = wait_for_code(config["redirect_uri"], state, args.timeout)

    graph_response = exchange_code(
        tenant=config["tenant"],
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        redirect_uri=config["redirect_uri"],
        code=code,
        code_verifier=verifier,
        scopes=config["graph_scopes"],
    )
    graph_payload = public_token_payload(graph_response, config["tenant"])
    require_access_token(graph_payload, "Graph")
    return add_imap_token(config, graph_payload, graph_payload.get("refresh_token"), None)


def refresh(args: argparse.Namespace, config: dict) -> dict:
    previous = read_tokens(config["output"]) if os.path.exists(config["output"]) else None
    refresh_token = args.refresh_token or latest_refresh_token(previous)
    if not refresh_token:
        raise SystemExit("Nenhum refresh_token. Rode o login antes, ou passe --refresh-token.")

    graph_response = refresh_tokens(
        tenant=config["tenant"],
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        refresh_token=refresh_token,
        scopes=config["graph_scopes"],
    )
    graph_payload = public_token_payload(graph_response, config["tenant"], nested_token(previous, "graph"))
    require_access_token(graph_payload, "Graph")
    refresh_token = graph_payload.get("refresh_token") or refresh_token
    return add_imap_token(config, graph_payload, refresh_token, previous)


def main() -> None:
    args = parse_args()
    config = resolve_config(args)
    payload = refresh(args, config) if args.refresh else login(args, config)
    write_tokens(config["output"], payload)
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    print(f"Tokens salvos em {config['output']}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("\nInterrompido.") from None
