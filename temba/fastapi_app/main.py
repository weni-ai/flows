import os
from typing import Annotated, Optional

from fastapi import APIRouter, Body, FastAPI, Header, HTTPException, status as http_status  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from rest_framework.request import Request  # noqa: E402
from rest_framework.test import APIRequestFactory  # noqa: E402

import django  # noqa: E402

from temba.api.auth.jwt import OptionalJWTAuthentication  # noqa: E402
from temba.api.v2.internals.broadcasts.context import resolve_org_and_user_internal_whatsapp  # noqa: E402
from temba.api.v2.serializers import WhatsappBroadcastReadSerializer, WhatsappBroadcastWriteSerializer  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "temba.settings")


django.setup()



app = FastAPI(title="Temba WhatsApp broadcasts (prototype)", version="0")
app_fastapi = APIRouter(prefix="/fastapi")


@app.get("/")
@app.get("/health")
@app_fastapi.get("/")
@app_fastapi.get("/health")
def health():
    return {"status": "ok"}


@app_fastapi.post("/internal/whatsapp_broadcasts")
def post_internal_whatsapp_broadcast(
    body: dict = Body(...),
    authorization: Annotated[Optional[str], Header()] = None,
):
    """
    Same semantics as Django InternalWhatsappBroadcastsEndpoint with DRF serializers.

    Bearer JWT behaves like OptionalJWTAuthentication on the Django route. OIDC internal auth used by Django
    is not replicated here yet.
    """
    factory = APIRequestFactory()
    headers = {}
    if authorization:
        headers["HTTP_AUTHORIZATION"] = authorization

    django_request = factory.post(
        "/api/v2/internals/whatsapp_broadcasts",
        body,
        format="json",
        **headers,
    )
    drf_request = Request(django_request)

    OptionalJWTAuthentication().authenticate(drf_request)

    try:
        org, user = resolve_org_and_user_internal_whatsapp(drf_request=drf_request, data=dict(body))
    except ValueError as e:
        msg = str(e)
        status_code = (
            http_status.HTTP_404_NOT_FOUND if msg == "Project not found" else http_status.HTTP_401_UNAUTHORIZED
        )
        raise HTTPException(status_code=status_code, detail={"error": msg})

    serializer = WhatsappBroadcastWriteSerializer(
        data=body,
        context={"request": drf_request, "org": org, "user": user},
    )
    if serializer.is_valid():
        broadcast = serializer.save()
        read_serializer = WhatsappBroadcastReadSerializer(
            instance=broadcast,
            context={"request": drf_request, "org": org, "user": user},
        )
        return JSONResponse(content=dict(read_serializer.data), status_code=http_status.HTTP_201_CREATED)

    return JSONResponse(content=serializer.errors, status_code=http_status.HTTP_400_BAD_REQUEST)


app.include_router(app_fastapi)
