# FastAPI prototype for internal WhatsApp broadcasts

## What we did

- Added a new `temba/fastapi_app/` package that boots a FastAPI ASGI app
  next to the existing Django WSGI app. `main.py` calls `django.setup()` so
  Django ORM, settings and serializers are available, then exposes the
  endpoints described below.

- Exposed a public `POST /fastapi/internal/whatsapp_broadcasts` endpoint
  that mirrors Django's `InternalWhatsappBroadcastsEndpoint`:
  - Reuses `WhatsappBroadcastWriteSerializer` for validation and
    `WhatsappBroadcastReadSerializer` for the response shape.
  - Reuses the shared `resolve_org_and_user_internal_whatsapp` helper to
    resolve `org`/`user` from the JWT payload, the request body or
    `user_email`.
  - Returns the same status codes as the Django route: `201` on success,
    `400` on serializer errors, `401` for missing project/user email,
    `404` when the project UUID is unknown.

- Exposed lightweight health probes at `/`, `/health`, `/fastapi/` and
  `/fastapi/health` so the service can be checked both behind and outside
  the `/fastapi` ingress prefix.

- Added a dedicated `verify_jwt` FastAPI dependency in
  `temba/fastapi_app/auth.py` that validates the `Authorization: Bearer`
  header against `settings.JWT_PUBLIC_KEY` using RS256. Any failure
  (missing/non-Bearer header, missing public key, expired token, invalid
  token) raises `HTTPException(403)` instead of returning `None`. The
  decoded payload is passed to the route handler.

- Added unit tests in `temba/fastapi_app/tests.py` covering:
  - All four health routes via `TestClient`.
  - The broadcast handler invoked directly with arbitrary `jwt_payload`
    (project missing/not found, missing user email, serializer error,
    happy path, project UUID coming from the JWT).
  - `verify_jwt` for missing/invalid header, missing public key, invalid
    token, expired token (mocked) and the successful decode path.
  - Both `main.py` and `auth.py` reach 100% line coverage.

- Added runtime dependencies `fastapi` and `uvicorn[standard]`, plus
  `httpx` in the dev group so `fastapi.testclient.TestClient` can be used
  in tests.

## Why we did

- We wanted to benchmark and prototype an alternate ASGI runtime for the
  internal WhatsApp broadcast endpoint without rewriting business rules.
  Sharing the DRF serializers and the resolve helper guarantees parity
  with the existing Django route and keeps the surface area small.

- Django's `InternalWhatsappBroadcastsEndpoint` uses
  `OptionalJWTAuthentication` so it can fall back to OIDC. In the FastAPI
  prototype we do not chain authenticators, and the old behaviour of
  silently returning `None` on bad tokens let requests through whenever
  the body carried a valid `project` and `user_email`, which produced
  `201 Created` responses with unauthenticated callers. `verify_jwt`
  fails closed with `403` so the endpoint can never serve an unverified
  request, even when the body looks valid.

- A single auth dependency is easier to test, document and replace later
  (e.g. when we add OIDC or rotate signing keys) than scattering checks
  inside the route. Tests exercise it directly without spinning up
  `TestClient`, so we cover every error branch with cheap unit tests.

- We test the FastAPI route handler by calling it as a regular Python
  function. Going through `TestClient` would force every test into a
  `TransactionTestCase` because Starlette runs sync routes on a thread
  pool and Django `TestCase` transactions are not visible across
  threads. Direct invocation keeps the suite on `TembaTest`, which runs
  these tests in roughly one second instead of more than a minute.
