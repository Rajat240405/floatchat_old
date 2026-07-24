"""HTTP route modules (Cleanup M3 — API layer decomposition).

The former monolithic ``api/routes.py`` was split into thin routers:

    chat.py     → POST /chat                (orchestrates chat_service)
    floats.py   → GET /floats/*             (orchestrates floats_service)
    health.py   → GET /health               (orchestrates health_service)

``router`` aggregates the /api/v1 routers exactly as before, so
``from floatchat.api.routes import router`` keeps working. Endpoint names,
docstrings, response models, and paths are unchanged; the OpenAPI schema is
identical to the pre-split version.
"""

from fastapi import APIRouter

from floatchat.api.routes.chat import router as _chat_router
from floatchat.api.routes.floats import router as _floats_router

# Back-compat re-exports of the former module-level names.
from floatchat.api.schemas import (  # noqa: F401
    AvailablePlotItem,
    ChatRequest,
    FloatAvailablePlotsResponse,
    FloatMetadataAPIResponse,
    FloatProfileAPIResponse,
    FloatRegistryResponse,
    FloatTrajectoryAPIResponse,
)

router = APIRouter()
router.include_router(_chat_router)
router.include_router(_floats_router)

__all__ = ["router"]
