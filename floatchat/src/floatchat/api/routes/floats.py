"""Float routes — deterministic /floats/* resources (HTTP wiring only).

Cleanup M3 (API layer decomposition): thin HTTP layer over
``floatchat.api.services.floats_service``. Response schemas live in
``floatchat.api.schemas``; all lake access, SQL, and formatting live in the
service module. Endpoint names, paths, docstrings, and the 422 validation
contract are unchanged.
"""

from fastapi import APIRouter, HTTPException, Query

from floatchat.api.schemas import (
    FloatAvailablePlotsResponse,
    FloatMetadataAPIResponse,
    FloatProfileAPIResponse,
    FloatRegistryResponse,
    FloatTrajectoryAPIResponse,
)
from floatchat.api.services import floats_service
from floatchat.variable_registry.registry import VariableRegistry

router = APIRouter()


@router.get("/floats/registry", response_model=FloatRegistryResponse)
def get_float_registry_endpoint():
    """Lightweight dashboard bootstrap endpoint.

    Returns every float in the local lake with:
    - latest known position
    - registry status (active / inactive / drifted) — authoritative
    - region_tag for Quick Region filters
    - network / DAC / sensors for sidebar filters

    IMPORTANT: Must NOT apply an arbitrary profile LIMIT. A previous
    ``get_profile_index(limit=10000)`` only saw floats present in the
    newest 10k profiles, which collapsed a ~1300-float registry to ~269.
    """
    return floats_service.build_float_registry_response()



@router.get("/floats/{float_id}/metadata", response_model=FloatMetadataAPIResponse)
def get_float_metadata(float_id: str):
    """Deterministic metadata lookup. No LLM. No chat routing."""
    return floats_service.build_float_metadata_response(float_id)



@router.get("/floats/{float_id}/trajectory", response_model=FloatTrajectoryAPIResponse)
def get_float_trajectory(float_id: str):
    """Deterministic trajectory + full cycle history. No LLM. No chat routing.

    Returns ALL cycles for the float (safety cap 50_000). Cycles without valid
    coordinates are still included so Cycle History is complete; the map simply
    skips plotting those points.
    """
    return floats_service.build_float_trajectory_response(float_id)



@router.get("/floats/{float_id}/latest-profile", response_model=FloatProfileAPIResponse)
def get_float_latest_profile(float_id: str):
    """Deterministic latest-profile plot. No LLM. No chat routing.

    Builds a ParsedIntent and runs the lake-only QueryEngine path with the
    scientific narrator forced off so this UI action never invokes an LLM.
    """
    return floats_service.build_latest_profile_response(float_id)



@router.get("/floats/{float_id}/available-plots", response_model=FloatAvailablePlotsResponse)
def get_float_available_plots(float_id: str):
    """List scientific variables available for a float. Deterministic. No LLM."""
    return floats_service.build_available_plots_response(float_id)



@router.get("/floats/{float_id}/plot", response_model=FloatProfileAPIResponse)
def get_float_plot(
    float_id: str,
    variable: str = "TEMP",
    profile_number: int | None = Query(default=None, ge=1),
):
    """Render a deterministic profile plot for one variable. No LLM. No chat."""
    var = str(variable or "TEMP").strip().upper()
    if not var:
        var = "TEMP"
    if not VariableRegistry.is_valid_variable(var) or var == "PRES":
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported plot variable: {var}",
        )
    return floats_service.build_float_plot_response(
        float_id=float_id, var=var, profile_number=profile_number
    )
