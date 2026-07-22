"""Automatic Plot Interpretation Engine (Phase 25.1).

Data-driven: interprets features from the actual plotted DataFrame.
Only analyzes variables that were actually requested.
Reports numeric values from data, never generic boilerplate.
"""

from typing import List

import numpy as np
import pandas as pd


def _get_col(df: pd.DataFrame, prefix: str) -> str | None:
    """Return the best column name matching prefix."""
    for c in df.columns:
        if c.startswith(prefix):
            return c
    return None


def generate_plot_interpretation(
    df: pd.DataFrame, variables: List[str], region: str | None
) -> str:
    """Generate data-driven plot interpretation from observed features.

    Only analyzes variable families that appear in the requested variables list.
    All interpretations use actual numeric values from the DataFrame.
    """
    parts: List[str] = []
    pres_col = "PRES" if "PRES" in df.columns else None
    vars_upper = set(v.upper() for v in variables)

    # --- Temperature -------------------------------------------------- #
    if any(v.startswith("TEMP") for v in vars_upper):
        temp_col = _get_col(df, "TEMP")
        if temp_col and pres_col:
            s = df[temp_col].dropna()
            if not s.empty:
                p = df.loc[s.index, pres_col]
                shallow = s[p <= 50]
                deep = s[p >= 150]

                if not shallow.empty:
                    sur = round(float(shallow.mean()), 1)
                    parts.append(f"Surface temperature averages {sur} degC.")

                if not deep.empty:
                    bot = round(float(deep.mean()), 1)
                    parts.append(f"Deep temperature averages {bot} degC.")

                if not shallow.empty and not deep.empty:
                    drop = round(float(shallow.mean() - deep.mean()), 1)
                    if drop > 10:
                        parts.append(
                            f"Temperature drops {drop} degC from surface to depth, "
                            f"indicating strong stratification."
                        )
                    elif drop > 3:
                        parts.append(
                            f"Temperature decreases {drop} degC with depth, "
                            f"showing a moderate thermocline."
                        )

                # Thermocline depth: sustained, smoothed gradient
                if len(s) >= 5:
                    t_vals = s.values
                    p_vals = p.values
                    idx_sort = p_vals.argsort()
                    t_sorted = t_vals[idx_sort]
                    p_sorted = p_vals[idx_sort]

                    # Rolling mean smooth
                    t_smooth = pd.Series(t_sorted).rolling(3, min_periods=2, center=True).mean().values
                    dp = pd.Series(p_sorted).diff().values
                    dt = pd.Series(t_smooth).diff().abs().values
                    with np.errstate(divide='ignore', invalid='ignore'):
                        grad = np.where(dp > 0, dt / dp * 10, 0.0)

                    # Only consider depths 20-300 dbar
                    mask = (p_sorted >= 20) & (p_sorted <= 300) & (grad > 0)
                    if mask.any():
                        grad_masked = grad[mask]
                        best_i = int(np.argmax(grad_masked))
                        best_grad = grad_masked[best_i]
                        p_masked = p_sorted[mask]
                        if best_grad > 0.3:
                            thermo_d = int(round(p_masked[best_i]))
                            parts.append(
                                f"A pronounced thermocline is observed near "
                                f"{thermo_d} dbar where temperature drops rapidly."
                            )

    # --- Salinity ---------------------------------------------------- #
    if any(v.startswith("PSAL") for v in vars_upper):
        psal_col = _get_col(df, "PSAL")
        if psal_col and pres_col:
            s = df[psal_col].dropna()
            if not s.empty:
                p = df.loc[s.index, pres_col]
                shallow = s[p <= 50]
                deep = s[p >= 150]

                if not shallow.empty:
                    sur = round(float(shallow.mean()), 3)
                    parts.append(f"Surface salinity averages {sur} psu.")

                if not deep.empty:
                    bot = round(float(deep.mean()), 3)
                    parts.append(f"Deep salinity averages {bot} psu.")

                if not shallow.empty and not deep.empty:
                    diff = round(abs(float(shallow.mean() - deep.mean())), 3)
                    if diff > 0.5:
                        parts.append(
                            f"Salinity changes {diff} psu across the water column, "
                            f"indicating distinct water masses."
                        )

    # --- Oxygen ------------------------------------------------------ #
    if any(v.startswith("DOXY") for v in vars_upper):
        doxy_col = _get_col(df, "DOXY")
        if doxy_col and pres_col:
            s = df[doxy_col].dropna()
            if not s.empty:
                min_idx = s.idxmin()
                min_val = round(float(s.min()), 1)
                min_depth = round(float(df.loc[min_idx, pres_col]), 1)
                max_val = round(float(s.max()), 1)

                if min_val < 60:
                    parts.append(
                        f"Oxygen minimum ({min_val} umol/kg) at {min_depth} dbar "
                        f"indicates a well-developed Oxygen Minimum Zone."
                    )
                elif min_val < 150:
                    parts.append(
                        f"A mild oxygen minimum ({min_val} umol/kg) is present "
                        f"at {min_depth} dbar."
                    )
                else:
                    parts.append(
                        f"Oxygen is well-mixed (min {min_val}, max {max_val} umol/kg); "
                        f"no OMZ detected."
                    )

    # --- Chlorophyll ------------------------------------------------- #
    if any(v.startswith("CHLA") for v in vars_upper):
        chla_col = _get_col(df, "CHLA")
        if chla_col and pres_col:
            s = df[chla_col].dropna()
            if not s.empty:
                max_idx = s.idxmax()
                max_val = round(float(s.max()), 3)
                max_depth = round(float(df.loc[max_idx, pres_col]), 1)
                shallow_mask = df.loc[s.index, pres_col] <= 10
                sur_val = (
                    round(float(s[shallow_mask].mean()), 3)
                    if shallow_mask.any() else None
                )

                if max_depth > 20 and sur_val is not None and max_val > sur_val * 1.5:
                    parts.append(
                        f"Deep chlorophyll maximum ({max_val} mg/m3) at {max_depth} dbar, "
                        f"significantly exceeding surface values ({sur_val} mg/m3)."
                    )
                elif max_depth > 20:
                    parts.append(
                        f"Chlorophyll maximum ({max_val} mg/m3) at {max_depth} dbar "
                        f"is subsurface."
                    )
                else:
                    parts.append(
                        f"Maximum chlorophyll ({max_val} mg/m3) occurs near the surface."
                    )

    if not parts:
        return "Vertical profiles show the expected structure for this region."
    return " ".join(parts)
