"""Profile plot implementation — Phase 6 fixed for separate graphs.

Renders one or more BGC variables versus pressure.
Fix: Shows separate subplots per variable in grid layout (max 3 cols), each with QC-aware colors.
"""

import json
import logging
import math
import time
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from floatchat.exceptions import VisualizationError
from floatchat.models import ParsedIntent
from floatchat.visualization_engine.base import AbstractVisualizationEngine

logger = logging.getLogger(__name__)

_VAR_TITLES: dict[str, str] = {
    "DOXY": "Dissolved Oxygen (µmol kg⁻¹)",
    "CHLA": "Chlorophyll-A (mg m⁻³)",
    "BBP700": "Particle Backscattering 700 nm (m⁻¹)",
    "NITRATE": "Nitrate (µmol kg⁻¹)",
    "PH_IN_SITU_TOTAL": "pH (total scale)",
    "DOWNWELLING_PAR": "Downwelling PAR (µmol photons m⁻² s⁻¹)",
    "DOWN_IRRADIANCE380": "Irradiance 380 nm",
    "DOWN_IRRADIANCE412": "Irradiance 412 nm",
    "DOWN_IRRADIANCE490": "Irradiance 490 nm",
    "TEMP": "Temperature (°C)",
    "PSAL": "Practical Salinity",
}

_COLOURS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f"]


def _qc_to_alpha(qc: str) -> float:
    mapping = {"1": 1.0, "2": 0.8, "3": 0.4, "4": 0.2}
    return mapping.get(str(qc).strip(), 0.5)


def _compact_figure_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove Plotly defaults that do not change the rendered figure.

    Scientific values, hover text, styling, and subplot layout are retained.
    ``showlegend=True`` is Plotly's default for these traces. Explicit axis
    references are retained for compatibility with existing subplot consumers.
    """
    traces = payload.get("data", []) or []
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        if trace.get("showlegend") is True:
            trace.pop("showlegend", None)
        # Keep explicit axis references for compatibility with existing
        # subplot consumers and regression tests, even for one-axis figures.
    return payload


def _figure_metrics(payload: dict[str, Any]) -> tuple[int, int, int]:
    """Return (trace_count, plotted_points, serialized_bytes) for diagnostics."""
    traces = payload.get("data", []) or []
    points = 0
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        points += max(len(trace.get("x", []) or []), len(trace.get("y", []) or []))
    serialized_bytes = len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return len(traces), points, serialized_bytes


def _hex_to_rgba(hex_colour: str, alpha: float) -> str:
    r = int(hex_colour[1:3], 16)
    g = int(hex_colour[3:5], 16)
    b = int(hex_colour[5:7], 16)
    return f"rgba({r},{g},{b},{alpha:.2f})"


def _sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, tuple):
        return [_sanitize_for_json(v) for v in obj]
    if hasattr(obj, "tolist") and callable(obj.tolist):
        return _sanitize_for_json(obj.tolist())
    if hasattr(obj, "isoformat") and callable(obj.isoformat):
        return obj.isoformat()
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if pd.isna(obj):
        return None
    return obj


class ProfileVisualizationEngine(AbstractVisualizationEngine):
    def render(self, intent: ParsedIntent, df: pd.DataFrame) -> dict[str, Any] | None:
        if intent.intent == "trajectory":
            return None
        if intent.intent == "time_series":
            return _sanitize_for_json(self._render_time_series(intent, df))
        if intent.intent == "hovmoller":
            return _sanitize_for_json(self._render_hovmoller(intent, df))
        if intent.intent == "ts_diagram":
            return _sanitize_for_json(self._render_ts_diagram(intent, df))
        if intent.intent in ("comparison", "comparison_plot"):
            return _sanitize_for_json(self._render_comparison(intent, df))

        if df.empty:
            raise VisualizationError("DataFrame is empty")
        if "PRES" not in df.columns:
            raise VisualizationError("Missing PRES")

        t_plot_start = time.perf_counter()
        t_prepare_start = t_plot_start
        variables = intent.variables or []
        if not variables:
            # Sprint 1 (Bug 8): identifiers, coordinates and time columns are
            # numeric but are NOT plottable variables. Letting them through
            # inflated n_vars to ~20, and with a fixed vertical spacing the
            # subplot grid became geometrically impossible (Plotly raises
            # "vertical spacing cannot be greater than 1/(rows-1)").
            exclude = {
                "PRES", "profile_idx", "level_idx",
                "float_id", "cycle_number", "year", "month", "date",
                "lat", "lon", "latitude", "longitude",
            }
            variables = [
                c for c in df.columns
                if c not in exclude and not c.endswith("_QC") and not c.endswith("_ADJUSTED") and not c.endswith("_ADJUSTED_QC")
                and pd.api.types.is_numeric_dtype(df[c])
            ]

        # Build list of actually present variables (support ADJUSTED fallback)
        available = []
        for v in variables:
            if v in df.columns and df[v].notna().any():
                available.append(v)
            elif f"{v}_ADJUSTED" in df.columns and df[f"{v}_ADJUSTED"].notna().any():
                available.append(v)

        # Dedup preserve order
        available = list(dict.fromkeys(available))

        if not available and not intent.variables:
            # Fallback to any known var that exists
            for cand in ["TEMP", "PSAL", "DOXY", "CHLA", "BBP700", "NITRATE", "PH_IN_SITU_TOTAL", "DOWNWELLING_PAR"]:
                if cand in df.columns and df[cand].notna().any():
                    available.append(cand)
                elif f"{cand}_ADJUSTED" in df.columns and df[f"{cand}_ADJUSTED"].notna().any():
                    available.append(cand)

        if not available:
            raise VisualizationError(f"No requested vars found: {variables}", details={"columns": list(df.columns)})

        t_prepare_end = time.perf_counter()
        n_vars = len(available)
        cols = min(3, n_vars)
        rows = math.ceil(n_vars / cols)

        # Sprint 1 (Bug 8): Plotly requires vertical_spacing <= 1/(rows-1).
        # Clamp the nominal 0.18 so the figure renders no matter how many
        # variables are requested (0.9 factor keeps a safety margin).
        v_spacing = min(0.18, 0.9 / (rows - 1)) if rows > 1 else 0.18

        t_construct_start = time.perf_counter()
        fig = make_subplots(
            rows=rows,
            cols=cols,
            shared_yaxes=False,
            shared_xaxes=False,
            horizontal_spacing=0.10,
            vertical_spacing=v_spacing,
            subplot_titles=[_VAR_TITLES.get(v, v) for v in available],
        )

        # A scientific profile is identified by (float_id, cycle_number), not
        # by float alone. Keep the composite key local to visualization so
        # multiple cycles cannot be merged into one trace.
        plot_df = df
        if "float_id" in df.columns and "cycle_number" in df.columns:
            plot_df = df.copy()
            plot_df["_plot_profile_key"] = (
                plot_df["float_id"].astype(str) + "::" + plot_df["cycle_number"].astype(str)
            )
            group_col = "_plot_profile_key"
        else:
            group_col = "float_id" if "float_id" in df.columns else "profile_idx"
        groups = sorted(plot_df[group_col].dropna().unique())[:8]

        for idx, var in enumerate(available):
            r = idx // cols + 1
            c = idx % cols + 1

            actual_col = var if var in df.columns and df[var].notna().any() else f"{var}_ADJUSTED"
            qc_col = f"{var}_QC"
            if qc_col not in df.columns:
                # try ADJUSTED QC
                if f"{actual_col}_QC" in df.columns:
                    qc_col = f"{actual_col}_QC"
                elif f"{var}_ADJUSTED_QC" in df.columns:
                    qc_col = f"{var}_ADJUSTED_QC"
                else:
                    qc_col = None

            has_qc = qc_col is not None and qc_col in df.columns

            for g_idx, g_val in enumerate(groups):
                sub = plot_df[plot_df[group_col] == g_val].sort_values("PRES", ascending=True)
                sub = sub.dropna(subset=[actual_col, "PRES"])
                if sub.empty:
                    continue
                pres = sub["PRES"].astype(float).values
                vals = sub[actual_col].astype(float).values

                if g_idx == 0 and var not in ("TEMP", "PSAL") and len(vals) > 20:
                    # Keep within 1-99 percentile for BGC to avoid spike overlay mess
                    lo, hi = np.percentile(vals, [1, 99])
                    mask = (vals >= lo) & (vals <= hi)
                    pres = pres[mask]
                    vals = vals[mask]

                if group_col == "float_id":
                    hover_template = f"Float: {g_val}<br>PRES: %{{y:.1f}}<br>{var}: %{{x:.3f}}<extra></extra>"
                    name = f"Float {g_val}"
                elif group_col == "_plot_profile_key":
                    profile_float, profile_cycle = str(g_val).split("::", 1)
                    hover_template = f"Float: {profile_float}<br>Cycle: {profile_cycle}<br>PRES: %{{y:.1f}}<br>{var}: %{{x:.3f}}<extra></extra>"
                    name = f"Float {profile_float} · Cycle {profile_cycle}"
                else:
                    hover_template = f"Profile: {g_val}<br>PRES: %{{y:.1f}}<br>{var}: %{{x:.3f}}<extra></extra>"
                    name = f"Profile {g_val}"

                colour = _COLOURS[g_idx % len(_COLOURS)]

                if has_qc:
                    alphas = sub[qc_col].apply(_qc_to_alpha).to_numpy(dtype=float)
                    # Need to align alphas with filtered pres/vals if we filtered outliers
                    # Simplification: if outlier filtered, use uniform alpha 1.0 for that filtered set
                    if len(alphas) != len(vals):
                        # outliers filtered case - use 0.8 uniform
                        marker_colors = [_hex_to_rgba(colour, 0.8) for _ in range(len(vals))]
                    else:
                        marker_colors = []
                        for i in range(len(pres)):
                            if np.isnan(vals[i]) or np.isnan(pres[i]):
                                marker_colors.append("rgba(0,0,0,0)")
                            else:
                                marker_colors.append(_hex_to_rgba(colour, alphas[i]))

                    fig.add_trace(
                        go.Scatter(
                            x=vals, y=pres,
                            mode="lines+markers",
                            name=name,
                            line=dict(color=colour, width=1.6),
                            marker=dict(color=marker_colors, size=6),
                            hovertemplate=hover_template,
                            showlegend=True,
                        ),
                        row=r, col=c,
                    )
                else:
                    fig.add_trace(
                        go.Scatter(
                            x=vals, y=pres,
                            mode="lines+markers",
                            name=name,
                            line=dict(color=colour, width=1.6),
                            marker=dict(size=5),
                            hovertemplate=hover_template,
                            showlegend=True,
                        ),
                        row=r, col=c,
                    )

            fig.update_xaxes(title_text=_VAR_TITLES.get(var, var), row=r, col=c)
            fig.update_yaxes(title_text="Pressure (dbar)" if c == 1 else "", autorange="reversed", row=r, col=c)

        fig.update_layout(
            title_text=self._build_title(intent),
            height=380 * rows + 100,
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=-0.18),
            margin=dict(l=70, r=30, t=80, b=100),
        )

        t_construct_end = time.perf_counter()
        t_serialize_start = time.perf_counter()
        payload = _compact_figure_payload(_sanitize_for_json(fig.to_dict()))
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
        t_serialize_end = time.perf_counter()
        trace_count, plotted_points, payload_bytes = _figure_metrics(payload)
        logger.info(
            "PIPELINE plot: data_preparation=%.3fs figure_construction=%.3fs "
            "figure_json_serialization=%.3fs traces=%d plotted_points=%d "
            "payload=%.2fKB input_rows=%d",
            t_prepare_end - t_prepare_start,
            t_construct_end - t_construct_start,
            t_serialize_end - t_serialize_start,
            trace_count,
            plotted_points,
            payload_bytes / 1024,
            len(df),
        )
        return payload

    def render_per_variable(self, intent: ParsedIntent, df: pd.DataFrame) -> list[dict[str, Any]]:
        """Render a list of standalone per-variable figures for the stacked plot drawer.

        Each returned dict is a single-variable Plotly figure augmented with a
        ``variable`` key (the canonical Argo variable code) so the client can
        title and organize plots. Reuses the same discovery + QC logic as
        :meth:`render`. Non-profile intents that don't decompose cleanly into
        per-variable vertical profiles (time_series, hovmoller, ts_diagram,
        comparison, trajectory) return an empty list.
        """
        t_per_var_start = time.perf_counter()
        if intent.intent in (
            "trajectory",
            "time_series",
            "hovmoller",
            "ts_diagram",
            "comparison",
            "comparison_plot",
        ):
            return []
        if df is None or df.empty or "PRES" not in df.columns:
            return []

        variables = intent.variables or []
        if not variables:
            exclude = {"PRES", "profile_idx", "level_idx"}
            variables = [
                c for c in df.columns
                if c not in exclude and not c.endswith("_QC") and not c.endswith("_ADJUSTED") and not c.endswith("_ADJUSTED_QC")
                and pd.api.types.is_numeric_dtype(df[c])
            ]

        available: list[str] = []
        for v in variables:
            if v in df.columns and df[v].notna().any():
                available.append(v)
            elif f"{v}_ADJUSTED" in df.columns and df[f"{v}_ADJUSTED"].notna().any():
                available.append(v)
        available = list(dict.fromkeys(available))

        if not available and not intent.variables:
            for cand in ["TEMP", "PSAL", "DOXY", "CHLA", "BBP700", "NITRATE", "PH_IN_SITU_TOTAL", "DOWNWELLING_PAR"]:
                if cand in df.columns and df[cand].notna().any():
                    available.append(cand)
                elif f"{cand}_ADJUSTED" in df.columns and df[f"{cand}_ADJUSTED"].notna().any():
                    available.append(cand)
        if not available:
            return []

        # A scientific profile is identified by (float_id, cycle_number), not
        # by float alone. Keep the composite key local to visualization so
        # multiple cycles cannot be merged into one trace.
        plot_df = df
        if "float_id" in df.columns and "cycle_number" in df.columns:
            plot_df = df.copy()
            plot_df["_plot_profile_key"] = (
                plot_df["float_id"].astype(str) + "::" + plot_df["cycle_number"].astype(str)
            )
            group_col = "_plot_profile_key"
        else:
            group_col = "float_id" if "float_id" in df.columns else "profile_idx"
        groups = sorted(plot_df[group_col].dropna().unique())[:8]

        figures: list[dict[str, Any]] = []
        for var in available:
            actual_col = var if var in df.columns and df[var].notna().any() else f"{var}_ADJUSTED"
            qc_col = f"{var}_QC"
            if qc_col not in df.columns:
                if f"{actual_col}_QC" in df.columns:
                    qc_col = f"{actual_col}_QC"
                elif f"{var}_ADJUSTED_QC" in df.columns:
                    qc_col = f"{var}_ADJUSTED_QC"
                else:
                    qc_col = None
            has_qc = qc_col is not None and qc_col in df.columns

            fig = go.Figure()
            for g_idx, g_val in enumerate(groups):
                sub = plot_df[plot_df[group_col] == g_val].sort_values("PRES", ascending=True)
                sub = sub.dropna(subset=[actual_col, "PRES"])
                if sub.empty:
                    continue
                pres = sub["PRES"].astype(float).values
                vals = sub[actual_col].astype(float).values

                if var not in ("TEMP", "PSAL") and len(vals) > 20:
                    lo, hi = np.percentile(vals, [1, 99])
                    mask = (vals >= lo) & (vals <= hi)
                    pres = pres[mask]
                    vals = vals[mask]

                if group_col == "float_id":
                    hover_template = f"Float: {g_val}<br>PRES: %{{y:.1f}}<br>{var}: %{{x:.3f}}<extra></extra>"
                    name = f"Float {g_val}"
                elif group_col == "_plot_profile_key":
                    profile_float, profile_cycle = str(g_val).split("::", 1)
                    hover_template = f"Float: {profile_float}<br>Cycle: {profile_cycle}<br>PRES: %{{y:.1f}}<br>{var}: %{{x:.3f}}<extra></extra>"
                    name = f"Float {profile_float} · Cycle {profile_cycle}"
                else:
                    hover_template = f"Profile: {g_val}<br>PRES: %{{y:.1f}}<br>{var}: %{{x:.3f}}<extra></extra>"
                    name = f"Profile {g_val}"

                colour = _COLOURS[g_idx % len(_COLOURS)]
                marker = dict(size=5)
                if has_qc:
                    alphas = sub[qc_col].apply(_qc_to_alpha).to_numpy(dtype=float)
                    if len(alphas) != len(vals):
                        marker_colors = [_hex_to_rgba(colour, 0.8) for _ in range(len(vals))]
                    else:
                        marker_colors = []
                        for i in range(len(pres)):
                            if np.isnan(vals[i]) or np.isnan(pres[i]):
                                marker_colors.append("rgba(0,0,0,0)")
                            else:
                                marker_colors.append(_hex_to_rgba(colour, alphas[i]))
                    marker = dict(color=marker_colors, size=6)

                fig.add_trace(
                    go.Scatter(
                        x=vals, y=pres,
                        mode="lines+markers",
                        name=name,
                        line=dict(color=colour, width=1.6),
                        marker=marker,
                        hovertext=hover,
                        hoverinfo="text",
                        showlegend=True,
                    )
                )

            fig.update_xaxes(title_text=_VAR_TITLES.get(var, var))
            fig.update_yaxes(title_text="Pressure (dbar)", autorange="reversed")
            fig.update_layout(
                title_text=_VAR_TITLES.get(var, var),
                height=420,
                template="plotly_white",
                legend=dict(orientation="h", yanchor="bottom", y=-0.22),
                margin=dict(l=70, r=30, t=50, b=70),
            )
            payload = _compact_figure_payload(_sanitize_for_json(fig.to_dict()))
            payload["variable"] = var
            figures.append(payload)

        total_traces = 0
        total_points = 0
        total_bytes = 0
        for payload in figures:
            traces, points, size = _figure_metrics(payload)
            total_traces += traces
            total_points += points
            total_bytes += size
        logger.info(
            "PIPELINE per_variable_plots: total=%.3fs figures=%d traces=%d "
            "plotted_points=%d payload=%.2fKB input_rows=%d",
            time.perf_counter() - t_per_var_start,
            len(figures),
            total_traces,
            total_points,
            total_bytes / 1024,
            len(df),
        )
        return figures

    @staticmethod
    def _build_title(intent: ParsedIntent) -> str:
        parts = []
        if intent.region:
            parts.append(intent.region.replace("_", " ").title())
        if intent.float_id:
            parts.append(f"Float {intent.float_id}")
        if intent.year:
            parts.append(str(intent.year))
        vars_str = ", ".join(intent.variables) if intent.variables else "Variables"
        return f"{vars_str} Profile — {' '.join(parts)}" if parts else f"{vars_str} Profile"

    def _render_time_series(self, intent: ParsedIntent, df: pd.DataFrame):
        if df.empty:
            raise VisualizationError("empty")
        date_col = "profile_date" if "profile_date" in df.columns else ("date" if "date" in df.columns else None)
        if not date_col:
            raise VisualizationError("missing date")
        sub = df.copy()
        sub[date_col] = pd.to_datetime(sub[date_col], errors="coerce")
        sub = sub.dropna(subset=[date_col])
        if "PRES" in sub.columns:
            if intent.depth_min is not None or intent.depth_max is not None:
                if intent.depth_min is not None:
                    sub = sub[sub["PRES"] >= intent.depth_min]
                if intent.depth_max is not None:
                    sub = sub[sub["PRES"] <= intent.depth_max]
            else:
                sub = sub[sub["PRES"] <= 20]

        variables = [v for v in (intent.variables or ["TEMP"]) if v in sub.columns or f"{v}_ADJUSTED" in sub.columns]
        if not variables:
            variables = [c for c in sub.columns if pd.api.types.is_numeric_dtype(sub[c]) and c not in ("PRES", "profile_idx", "level_idx", "lat", "lon", "latitude", "longitude")]

        fig = go.Figure()
        for idx, var in enumerate(variables):
            col = f"{var}_ADJUSTED" if f"{var}_ADJUSTED" in sub.columns and sub[f"{var}_ADJUSTED"].notna().any() else var
            if col not in sub.columns:
                continue
            grouped = sub.groupby(date_col)[col].mean().reset_index().sort_values(date_col)
            if grouped.empty:
                continue
            colour = _COLOURS[idx % len(_COLOURS)]
            fig.add_trace(go.Scatter(x=grouped[date_col], y=grouped[col], mode="lines+markers", name=_VAR_TITLES.get(var, var), line=dict(color=colour, width=2), marker=dict(size=6)))

        fig.update_layout(title_text=self._build_title(intent), xaxis=dict(title="Date"), yaxis=dict(title=_VAR_TITLES.get(variables[0], variables[0]) if len(variables)==1 else "Value"), template="plotly_white", height=500, margin=dict(l=80, r=40, t=80, b=80))
        return _sanitize_for_json(fig.to_dict())

    def _render_hovmoller(self, intent, df):
        if df.empty or "PRES" not in df.columns:
            raise VisualizationError("Missing PRES")
        date_col = "profile_date" if "profile_date" in df.columns else ("date" if "date" in df.columns else None)
        if not date_col:
            raise VisualizationError("missing date")
        var = intent.variables[0] if intent.variables else "TEMP"
        val_col = f"{var}_ADJUSTED" if f"{var}_ADJUSTED" in df.columns and df[f"{var}_ADJUSTED"].notna().any() else var
        if val_col not in df.columns:
            raise VisualizationError(f"Variable {var} not found")
        sub = df.copy()
        sub[date_col] = pd.to_datetime(sub[date_col], errors="coerce")
        sub = sub.dropna(subset=[date_col, "PRES", val_col])
        if sub.empty:
            raise VisualizationError("No obs")
        max_pres = sub["PRES"].max()
        max_pres = max_pres if pd.notna(max_pres) and max_pres>0 else 1000.0
        bins = np.arange(0, int(max_pres)+20, 10)
        depth_centers = 0.5*(bins[:-1]+bins[1:])
        dates = sorted(sub[date_col].dt.date.unique())
        if not dates:
            raise VisualizationError("No dates")
        sub["_bin"] = pd.cut(sub["PRES"], bins=bins, labels=False)
        z = np.full((len(depth_centers), len(dates)), np.nan)
        for j,d in enumerate(dates):
            d_sub = sub[sub[date_col].dt.date==d]
            means = d_sub.groupby("_bin")[val_col].mean()
            for b_idx,val in means.items():
                if pd.notna(b_idx) and 0 <= int(b_idx) < len(depth_centers):
                    z[int(b_idx), j] = val
        colorscale = "RdBu_r" if "TEMP" in var.upper() else "Viridis"
        fig = go.Figure(data=go.Heatmap(x=[d.isoformat() for d in dates], y=depth_centers, z=z, colorscale=colorscale, colorbar=dict(title=_VAR_TITLES.get(var,var))))
        fig.update_layout(title_text=f"Hovmöller — {_VAR_TITLES.get(var,var)}", xaxis=dict(title="Date"), yaxis=dict(title="Pressure (dbar)", autorange="reversed"), template="plotly_white", height=600, margin=dict(l=80,r=40,t=80,b=80))
        return _sanitize_for_json(fig.to_dict())

    def _render_ts_diagram(self, intent, df):
        if df.empty or "PRES" not in df.columns:
            raise VisualizationError("Missing PRES")
        t_col = "TEMP_ADJUSTED" if "TEMP_ADJUSTED" in df.columns and df["TEMP_ADJUSTED"].notna().any() else "TEMP"
        s_col = "PSAL_ADJUSTED" if "PSAL_ADJUSTED" in df.columns and df["PSAL_ADJUSTED"].notna().any() else "PSAL"
        if t_col not in df.columns or s_col not in df.columns:
            raise VisualizationError("Missing TEMP/PSAL")
        sub = df[[t_col,s_col,"PRES"]].dropna()
        if sub.empty:
            raise VisualizationError("No T-S")
        fig = go.Figure(data=go.Scatter(x=sub[s_col], y=sub[t_col], mode="markers", marker=dict(color=sub["PRES"], colorscale="Viridis", reversescale=True, colorbar=dict(title="Pressure (dbar)"), size=6, opacity=0.8), hovertext=[f"Salinity: {s:.2f}<br>Temp: {t:.2f}<br>PRES: {p:.1f}" for s,t,p in zip(sub[s_col], sub[t_col], sub["PRES"])], hoverinfo="text", name="T-S"))
        fig.update_layout(title_text=self._build_title(intent), xaxis=dict(title="Practical Salinity (PSU)"), yaxis=dict(title="Temperature (°C)"), template="plotly_white", height=600, width=650, margin=dict(l=80,r=40,t=80,b=80))
        return _sanitize_for_json(fig.to_dict())

    def _render_comparison(self, intent, df):
        if df.empty or "PRES" not in df.columns:
            raise VisualizationError("Missing PRES")

        requested = intent.variables or ["TEMP","PSAL"]
        available = []
        for v in requested:
            if v in df.columns and df[v].notna().any():
                available.append(v)
            elif f"{v}_ADJUSTED" in df.columns and df[f"{v}_ADJUSTED"].notna().any():
                available.append(v)

        if not available:
            for cand in ["TEMP","PSAL","DOXY","CHLA","BBP700","NITRATE","PH_IN_SITU_TOTAL"]:
                if cand in df.columns and df[cand].notna().any():
                    available.append(cand)
                elif f"{cand}_ADJUSTED" in df.columns and df[f"{cand}_ADJUSTED"].notna().any():
                    available.append(cand)

        if not available:
            raise VisualizationError("No numeric vars for comparison")

        priority = ["TEMP","PSAL","DOXY","CHLA","BBP700","NITRATE","PH_IN_SITU_TOTAL","DOWNWELLING_PAR"]
        available_sorted = sorted(available, key=lambda x: priority.index(x) if x in priority else 99)
        available = available_sorted[:6]

        n_vars = len(available)
        cols = min(2, n_vars)
        rows = math.ceil(n_vars / cols)

        # Sprint 1 (Bug 8): same geometric clamp as the main profile render —
        # Plotly requires vertical_spacing <= 1/(rows-1).
        v_spacing = min(0.15, 0.9 / (rows - 1)) if rows > 1 else 0.15

        fig = make_subplots(
            rows=rows, cols=cols,
            shared_yaxes=False,
            shared_xaxes=False,
            horizontal_spacing=0.12,
            vertical_spacing=v_spacing,
            subplot_titles=[_VAR_TITLES.get(v,v) for v in available],
        )

        fids = intent.comparison_float_ids or sorted(df["float_id"].dropna().unique().astype(str).tolist())[:4]

        for idx, var in enumerate(available):
            r = idx // cols + 1
            c = idx % cols + 1
            col = f"{var}_ADJUSTED" if f"{var}_ADJUSTED" in df.columns and df[f"{var}_ADJUSTED"].notna().any() else var
            if col not in df.columns:
                continue

            for f_i, fid in enumerate(fids):
                sub = df[df["float_id"].astype(str) == str(fid)].sort_values("PRES")
                sub = sub.dropna(subset=[col, "PRES"])
                if sub.empty:
                    continue
                vals = sub[col].astype(float).values
                pres = sub["PRES"].astype(float).values
                if var not in ("TEMP","PSAL") and len(vals)>10:
                    lo, hi = np.percentile(vals, [1,99])
                    mask = (vals>=lo)&(vals<=hi)
                    vals = vals[mask]
                    pres = pres[mask]

                colour = _COLOURS[f_i % len(_COLOURS)]
                fig.add_trace(
                    go.Scatter(
                        x=vals, y=pres,
                        mode="lines+markers",
                        name=f"Float {fid}",
                        line=dict(color=colour, width=2),
                        marker=dict(size=5),
                        legendgroup=f"{fid}",
                        showlegend=(idx==0),
                    ),
                    row=r, col=c
                )

            fig.update_xaxes(title_text=_VAR_TITLES.get(var,var), row=r, col=c)
            fig.update_yaxes(title_text="Pressure (dbar)", autorange="reversed", row=r, col=c)

        title = f"Comparison — {', '.join(fids)}"
        fig.update_layout(
            title_text=title,
            height=380*rows + 100,
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=-0.12),
            margin=dict(l=70, r=30, t=80, b=100),
        )
        return _sanitize_for_json(fig.to_dict())
