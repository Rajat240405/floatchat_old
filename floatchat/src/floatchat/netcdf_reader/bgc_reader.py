"""BGC NetCDF reader implementation.

Extracts variables from Argo BGC profile NetCDF files (e.g. ``BR*.nc``)
into tidy :class:`pandas.DataFrame` objects.
"""

import logging

import numpy as np
import pandas as pd
from netCDF4 import Dataset

from floatchat.exceptions import NetCDFReadError
from floatchat.netcdf_reader.base import AbstractNetCDFReader
from floatchat.repository_service import NetCDFDataset

logger = logging.getLogger(__name__)

# Variables that are always extracted if present (pressure / depth proxy).
_MANDATORY_VARS = ["PRES"]

# Suffixes we attempt to extract alongside each requested variable.
_SUFFIXES = ["", "_QC", "_ADJUSTED", "_ADJUSTED_QC"]

# Variable alias resolution: if the exact variable is missing, try these
# alternatives in priority order.  _ADJUSTED is preferred because it contains
# scientifically quality-controlled data.
_VARIABLE_ALIASES: dict[str, list[str]] = {
    "TEMP": ["TEMP_ADJUSTED", "TEMP"],
    "PSAL": ["PSAL_ADJUSTED", "PSAL"],
    "DOXY": ["DOXY_ADJUSTED", "DOXY"],
    "CHLA": ["CHLA_ADJUSTED", "CHLA"],
    "NITRATE": ["NITRATE_ADJUSTED", "NITRATE"],
    "BBP700": ["BBP700_ADJUSTED", "BBP700"],
    "PH_IN_SITU_TOTAL": ["PH_IN_SITU_TOTAL_ADJUSTED", "PH_IN_SITU_TOTAL"],
    "DOWNWELLING_PAR": ["DOWNWELLING_PAR_ADJUSTED", "DOWNWELLING_PAR"],
    "DOWN_IRRADIANCE380": ["DOWN_IRRADIANCE380_ADJUSTED", "DOWN_IRRADIANCE380"],
    "DOWN_IRRADIANCE412": ["DOWN_IRRADIANCE412_ADJUSTED", "DOWN_IRRADIANCE412"],
    "DOWN_IRRADIANCE490": ["DOWN_IRRADIANCE490_ADJUSTED", "DOWN_IRRADIANCE490"],
}


def _resolve_variable_aliases(
    variables: list[str], available: set[str]
) -> tuple[list[str], dict[str, str]]:
    """Map requested variables to best available names in the dataset.

    Returns:
        A tuple of (resolved_names, alias_map) where *alias_map* maps
        the original requested name to the resolved name for downstream
        reporting.
    """
    resolved: list[str] = []
    alias_map: dict[str, str] = {}
    for req in variables:
        if req in available:
            resolved.append(req)
            alias_map[req] = req
            continue
        # Try aliases in priority order
        found = False
        for alias in _VARIABLE_ALIASES.get(req, []):
            if alias in available:
                resolved.append(alias)
                alias_map[req] = alias
                logger.info(
                    "Variable alias resolved: %s → %s", req, alias
                )
                found = True
                break
        if not found:
            # Keep the original name so the caller can report it as missing
            resolved.append(req)
            alias_map[req] = req
    return resolved, alias_map


def _extract_array(ds: Dataset, var_name: str) -> np.ndarray:
    """Return a dense numpy array for *var_name*, converting masks to NaN.

    Argo QC variables are stored as character arrays; we decode them
    into plain Python strings.
    """
    if var_name not in ds.variables:
        raise NetCDFReadError(f"Variable '{var_name}' not found in dataset")

    var = ds.variables[var_name]
    data = var[:]  # may be a masked array

    if hasattr(data, "filled") and data.dtype.kind not in ("S", "U"):
        # Numeric masked array → fill with NaN
        fill = getattr(var, "_FillValue", None)
        if fill is not None:
            data = data.filled(np.nan)
        else:
            data = data.filled(np.nan)
    elif data.dtype.kind == "S":
        # Byte strings → decode to unicode, strip, and cast to object
        # so the DataFrame receives plain Python str values.
        decoded = np.char.decode(data, encoding="utf-8", errors="ignore")
        data = np.char.strip(decoded).astype(object)
    elif data.dtype.kind == "U":
        # Unicode strings → strip and cast to object
        data = np.char.strip(data).astype(object)
    elif data.dtype == np.dtype("O"):
        # Object array (sometimes occurs with char arrays)
        data = np.array([[str(v).strip() for v in row] for row in data])

    return np.asarray(data)


class BGCNetCDFReader(AbstractNetCDFReader):
    """Reader tuned for Argo BGC bio-profile NetCDF files."""

    def read(self, ncd: NetCDFDataset, variables: list[str]) -> pd.DataFrame:
        """Extract requested variables into a DataFrame."""
        ds = ncd.dataset
        if ds is None:
            raise NetCDFReadError("NetCDF dataset is closed")

        logger.debug(
            "Reading variables %s from %s",
            variables,
            ncd.relative_path,
        )

        # --- Validate dimensions ------------------------------------------ #
        if "N_PROF" not in ds.dimensions or "N_LEVELS" not in ds.dimensions:
            raise NetCDFReadError(
                "Expected dimensions N_PROF and N_LEVELS not found",
                details={"dimensions": list(ds.dimensions.keys())},
            )

        n_prof = ds.dimensions["N_PROF"].size
        n_levels = ds.dimensions["N_LEVELS"].size

        # --- Resolve variable aliases ----------------------------------- #
        available_vars = set(ds.variables.keys())
        resolved_vars, alias_map = _resolve_variable_aliases(variables, available_vars)
        missing_requested = [v for v in variables if alias_map[v] not in available_vars]
        if missing_requested:
            raise NetCDFReadError(
                f"Requested variable(s) not found in dataset: {missing_requested}",
                details={"available": list(ds.variables.keys())},
            )

        # --- Build extraction list ---------------------------------------- #
        to_extract: list[str] = []
        for base in _MANDATORY_VARS + resolved_vars:
            for suffix in _SUFFIXES:
                candidate = base + suffix
                if candidate in ds.variables and candidate not in to_extract:
                    to_extract.append(candidate)

        missing_mandatory = [v for v in _MANDATORY_VARS if v not in to_extract]
        if missing_mandatory:
            raise NetCDFReadError(
                f"Mandatory variables missing: {missing_mandatory}",
                details={"available": list(ds.variables.keys())},
            )

        # --- Extract arrays ----------------------------------------------- #
        arrays: dict[str, np.ndarray] = {}
        for var_name in to_extract:
            try:
                arr = _extract_array(ds, var_name)
            except NetCDFReadError:
                logger.warning("Skipping missing variable %s", var_name)
                continue

            # Ensure 2D shape (N_PROF, N_LEVELS)
            if arr.ndim == 1 and n_prof == 1:
                arr = arr.reshape(1, -1)
            if arr.shape != (n_prof, n_levels):
                logger.warning(
                    "Variable %s has unexpected shape %s (expected %s)",
                    var_name,
                    arr.shape,
                    (n_prof, n_levels),
                )
                # Try to broadcast / pad — if it fails, skip
                try:
                    arr = np.broadcast_to(arr, (n_prof, n_levels))
                except ValueError:
                    continue
            arrays[var_name] = arr

        # --- Build DataFrame ---------------------------------------------- #
        # Create a tidy DataFrame with one row per (profile, level).
        records: list[dict] = []
        for prof_idx in range(n_prof):
            for level_idx in range(n_levels):
                row: dict[str, object] = {
                    "profile_idx": prof_idx,
                    "level_idx": level_idx,
                }
                for var_name, arr in arrays.items():
                    row[var_name] = arr[prof_idx, level_idx]
                records.append(row)

        df = pd.DataFrame.from_records(records)

        # Drop rows where pressure is NaN (empty levels in the profile)
        if "PRES" in df.columns:
            df = df.dropna(subset=["PRES"])

        logger.info(
            "Extracted DataFrame: shape=%s, columns=%s",
            df.shape,
            list(df.columns),
        )
        return df
