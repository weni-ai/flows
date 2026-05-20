import os

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, status as http_status  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from rest_framework.request import Request  # noqa: E402
from rest_framework.test import APIRequestFactory  # noqa: E402

import django  # noqa: E402

from temba.api.v2.internals.broadcasts.context import resolve_org_and_user_internal_whatsapp  # noqa: E402
from temba.api.v2.serializers import WhatsappBroadcastReadSerializer, WhatsappBroadcastWriteSerializer  # noqa: E402
from temba.fastapi_app.auth import verify_jwt  # noqa: E402

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
    jwt_payload: dict = Depends(verify_jwt),
):
    """
    POST mirrors Django InternalWhatsappBroadcastsEndpoint with DRF serializers.

    Requires a valid Bearer JWT signed with settings.JWT_PUBLIC_KEY. Any auth failure
    (missing/invalid/expired token or missing public key) returns 403 from verify_jwt.
    """
    factory = APIRequestFactory()
    django_request = factory.post(
        "/api/v2/internals/whatsapp_broadcasts",
        body,
        format="json",
    )
    drf_request = Request(django_request)
    setattr(drf_request, "jwt_payload", jwt_payload)
    project_uuid_from_jwt = jwt_payload.get("project_uuid") or jwt_payload.get("project")
    if project_uuid_from_jwt:
        setattr(drf_request, "project_uuid", project_uuid_from_jwt)

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
