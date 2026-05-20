import os
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status as http_status  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel, model_validator  # noqa: E402

import django  # noqa: E402

from temba.fastapi_app.auth import verify_jwt  # noqa: E402
from temba.fastapi_app.events_context import resolve_org_and_user_for_events  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "temba.settings")


django.setup()


# Defaults mirror DefaultLimitOffsetPagination used by the Django EventsV2Endpoint.
DEFAULT_LIMIT = 10
MAX_LIMIT = 100


app = FastAPI(title="Temba Events V2 (prototype)", version="0")
app_fastapi = APIRouter(prefix="/fastapi")


@app.get("/")
@app.get("/health")
@app_fastapi.get("/")
@app_fastapi.get("/health")
def health():
    return {"status": "ok"}


class EventsFilters(BaseModel):
    date_start: datetime
    date_end: datetime
    key: Optional[str] = None
    contact_urn: Optional[str] = None
    value_type: Optional[str] = None
    value: Optional[str] = None
    metadata: Optional[str] = None
    event_name: Optional[str] = None
    metadata_key: Optional[str] = None
    metadata_value: Optional[str] = None
    group_by: Optional[str] = None
    limit: Optional[int] = None
    offset: Optional[int] = None
    silver: bool = False
    table: Optional[str] = None

    @model_validator(mode="after")
    def _silver_requires_table(self) -> "EventsFilters":
        if self.silver and not self.table:
            raise ValueError("table is required when silver=true")
        return self


@app_fastapi.get("/events")
def get_events(
    filters: Annotated[EventsFilters, Query()],
    project_uuid: Annotated[Optional[str], Query()] = None,
    jwt_payload: dict = Depends(verify_jwt),
):
    """
    GET mirrors EventsV2Endpoint: validates query params, resolves the project's
    internal user, and proxies to fetch_events_for_org.
    """
    resolved_project_uuid = jwt_payload.get("project_uuid") or jwt_payload.get("project") or project_uuid

    try:
        _, user = resolve_org_and_user_for_events(project_uuid=resolved_project_uuid)
    except ValueError as e:
        msg = str(e)
        if msg == "Project not found":
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail={"error": msg})
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail={"error": msg})

    params = filters.model_dump(exclude_none=True)
    limit = params.get("limit", DEFAULT_LIMIT)
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    params["limit"] = limit
    params.setdefault("offset", 0)

    try:
        from temba.api.v2.services.events import fetch_events_for_org

        processed_events = fetch_events_for_org(user, **params)
        return JSONResponse(content=processed_events, status_code=http_status.HTTP_200_OK)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


app.include_router(app_fastapi)
