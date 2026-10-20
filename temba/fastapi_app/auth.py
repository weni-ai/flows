"""
FastAPI auth dependency for the WhatsApp broadcast prototype.

Unlike DRF's OptionalJWTAuthentication, which falls through silently to allow chained
authenticators, this dependency stops the request with HTTP 403 whenever the bearer
token is absent, the public key is missing in settings, or the JWT is expired/invalid.
"""

from typing import Annotated, Optional

import jwt
from fastapi import Header, HTTPException, status as http_status

from django.conf import settings


def verify_jwt(authorization: Annotated[Optional[str], Header()] = None) -> dict:
    if not authorization or not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={"error": "Missing or invalid Authorization header"},
        )

    public_key = getattr(settings, "JWT_PUBLIC_KEY", None)
    if not public_key:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={"error": "JWT public key not configured"},
        )

    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={"error": "Token expired"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={"error": "Invalid token"},
        )

    return payload
