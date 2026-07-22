"""FastAPI application factory.

Uses lifespan events to eagerly load the metadata index at startup.
Phase 23: Cleans up expired NetCDF cache files on startup.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from floatchat.api.dependencies import get_metadata_service
from floatchat.api.routes import router
from floatchat.exceptions import (
    FloatChatError,
    IntentParseError,
    MetadataError,
    NetCDFReadError,
    RepositoryError,
    VisualizationError,
)
from floatchat.logging_config import configure_logging
from floatchat.models import ErrorResponse
from floatchat.repository_service.gdac_http import cleanup_expired_netcdf_cache

# Mapping of domain exceptions to HTTP status codes.
_EXCEPTION_STATUS_MAP: dict[type[FloatChatError], int] = {
    IntentParseError: 400,
    MetadataError: 503,
    RepositoryError: 502,
    NetCDFReadError: 500,
    VisualizationError: 500,
}


def _make_exception_handler(status_code: int):
    """Factory returning a FastAPI exception handler for FloatChatError."""
    def _handler(request: Request, exc: FloatChatError) -> JSONResponse:
        body = ErrorResponse(
            error=type(exc).__name__,
            message=exc.message,
            details=exc.details,
        )
        return JSONResponse(status_code=status_code, content=body.model_dump())
    return _handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler.

    Phase 23: Cleans expired NetCDF cache, then loads metadata.
    """
    configure_logging()

    # --- Phase 23: NetCDF cache cleanup ---------------------------------- #
    cleanup_expired_netcdf_cache()

    # --- Metadata load --------------------------------------------------- #
    metadata = get_metadata_service()
    metadata.load()
    yield
    # Shutdown: nothing to clean up explicitly.


def create_app() -> FastAPI:
    """Factory that returns a configured FastAPI application."""
    app = FastAPI(
        title="FloatChat",
        description="AI-powered conversational backend for Argo BGC data",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — allow frontend dev server to connect directly.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register domain exception handlers so routes can raise freely.
    for exc_cls, status in _EXCEPTION_STATUS_MAP.items():
        app.add_exception_handler(exc_cls, _make_exception_handler(status))

    # Catch-all for unhandled exceptions — never leak raw tracebacks.
    @app.exception_handler(Exception)
    def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        import logging as _logging
        _logging.getLogger("floatchat.api").exception("Unhandled exception: %s", exc)
        body = ErrorResponse(
            error="InternalServerError",
            message="An unexpected error occurred. Please try again later.",
            details={},
        )
        return JSONResponse(status_code=500, content=body.model_dump())

    app.include_router(router, prefix="/api/v1")

    @app.get("/health")
    def health() -> JSONResponse:
        metadata = get_metadata_service()
        return JSONResponse(
            content={
                "status": "ok",
                "metadata_loaded": metadata.is_loaded(),
            }
        )

    return app


# Uvicorn entrypoint
app = create_app()
