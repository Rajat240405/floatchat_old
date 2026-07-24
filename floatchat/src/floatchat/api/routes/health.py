"""Health route — GET /health (HTTP wiring only).

Cleanup M3: moved from ``api/main.py`` into the route layer. Path, payload,
and status semantics are unchanged.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from floatchat.api.services.health_service import build_health_payload

router = APIRouter()


@router.get("/health")
def health() -> JSONResponse:
    return JSONResponse(content=build_health_payload())
