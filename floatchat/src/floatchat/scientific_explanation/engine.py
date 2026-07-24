"""Scientific Explanation Engine.

Generates rich, context-aware scientific explanations for every successful query.
Uses Argo knowledge base facts and runtime data. Never hallucinates.

Phase 25.4: Final stabilization for consistency, conversational robustness,
and scientific accuracy.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..config import settings
from ..models.intent import ParsedIntent
from ..models.metadata import MetadataRecord
from ..variable_registry.registry import VariableRegistry

if TYPE_CHECKING:
    from .features import ScientificFeatureExtractor
    from .narrator import ScientificNarrator
    from .output_parser import NarratorOutputParser
    from .prompt_builder import PromptBuilder
    from .schemas import ScientificFacts
    from .verification_guard import VerificationGuard

logger = logging.getLogger(__name__)


class ScientificExplanationEngine:
    """Generates scientific explanations for query results.

    Designed to be called by QueryEngine after successful data retrieval.
    """

    def __init__(
        self,
        *,
        feature_extractor: ScientificFeatureExtractor | None = None,
        prompt_builder: PromptBuilder | None = None,
        narrator: ScientificNarrator | None = None,
        output_parser: NarratorOutputParser | None = None,
        verification_guard: VerificationGuard | None = None,
        narrator_enabled: bool | None = None,
    ) -> None:
        """Create an explanation engine with optional narration dependencies.

        When any narration dependency is absent, or narration is disabled, the
        existing deterministic explanation remains authoritative. Concrete
        implementations are supplied by the application's composition root.
        """
        self.feature_extractor = feature_extractor
        self.prompt_builder = prompt_builder
        self.narrator = narrator
        self.output_parser = output_parser
        self.verification_guard = verification_guard
        self.narrator_enabled = narrator_enabled

        self.kb = {
            "DOXY": "Dissolved oxygen (DOXY) is measured by optodes. Adjusted values (DOXY_ADJUSTED) are preferred for scientific use.",
            "CHLA": "Chlorophyll-a (CHLA) indicates phytoplankton biomass. Deep Chlorophyll Maximum (DCM) at 50-150 m is common in stratified waters.",
            "TEMP": "Temperature controls density, stratification, oxygen solubility and metabolic rates.",
            "PSAL": "Salinity indicates evaporation-precipitation balance. High surface salinity in Arabian Sea due to evaporation dominance.",
            "QC": "QC flag 1 = good; 2 = probably good; 3 = bad but correctable; 4 = bad. Always prefer adjusted variables in delayed-mode (D) files.",
            "DELAYED_MODE": "Delayed-mode (D) data has expert QC and adjustments. Real-time (R) data is preliminary and may contain sensor drift.",
            "OMZ": "Arabian Sea and Bay of Bengal naturally contain Oxygen Minimum Zones (OMZs) between ~100-1000 m due to high respiration and limited ventilation.",
            "NITRATE": "Nitrate is a macronutrient used by phytoplankton; its vertical structure reflects uptake near the surface and remineralization at depth.",
            "BBP700": "Particle backscattering at 700 nm is an optical proxy for suspended particulate material and particle abundance.",
            "PH_IN_SITU_TOTAL": "In-situ pH on the total scale describes seawater acid-base conditions and is reported without physical concentration units.",
            "DOWNWELLING_PAR": "Downwelling PAR measures photosynthetically active light in the water column and generally decreases with depth.",
        }

    def _get_variable_column(self, df: pd.DataFrame, var_name: str) -> Optional[str]:
        """Find the best available column, using adjusted data only when usable."""
        adj_col = f"{var_name}_ADJUSTED"
        if adj_col in df.columns and self._has_finite_values(df, adj_col):
            return adj_col
        if var_name in df.columns:
            return var_name
        return None

    @staticmethod
    def _has_finite_values(df: pd.DataFrame, column: str) -> bool:
        """Return whether *column* contains at least one finite numeric value."""
        values = pd.to_numeric(df[column], errors="coerce")
        return bool(np.isfinite(values).any())

    def _compute_stats(self, df: pd.DataFrame, variables: List[str]) -> Dict[str, Any]:
        """Compute descriptive statistics for each requested variable.

        To ensure consistency across different query compositions, statistics are
        computed per profile and then averaged. This avoids 'composite profile'
        artifacts that shift thermocline/halocline depths.
        """
        aggregated_stats: Dict[str, Any] = {}
        
        if "PRES" not in df.columns:
            return aggregated_stats
        
        # Group by profile to compute stats per-profile first.
        # Use 'source_file' as the unique identifier for each profile to avoid
        # 'composite profile' artifacts when multiple profiles are retrieved.
        if "source_file" in df.columns:
            profile_ids = df["source_file"].unique()
        elif "float_id" in df.columns:
            profile_ids = df["float_id"].unique()
        else:
            profile_ids = [0]
        
        all_profile_stats: List[Dict[str, Any]] = []

        for pid in profile_ids:
            if "source_file" in df.columns:
                pdf = df[df["source_file"] == pid]
            elif "float_id" in df.columns:
                pdf = df[df["float_id"] == pid]
            else:
                pdf = df
            pdf = pdf.sort_values("PRES")

            
            p_stats = {}
            for var in variables:
                col = self._get_variable_column(pdf, var)
                if col is None: continue
                
                valid_mask = pdf[col].notna()
                series = pdf.loc[valid_mask, col]
                pres_series = pdf.loc[valid_mask, "PRES"]
                
                if series.empty: continue
                
                v_s = {
                    "min": float(series.min()),
                    "max": float(series.max()),
                    "median": float(series.median()),
                    "mean": float(series.mean()),
                    "count": int(series.count()),
                    "surface": float(series.iloc[:5].mean()),
                    "deep": float(series.iloc[-5:].mean()),
                    "deepest_pres": float(pres_series.max()),
                    "deepest_val": float(series.iloc[-1]),
                }
                
                # Gradient Analysis (ignore surface noise < 20 dbar)
                mask_deep = pres_series > 20
                s_deep = series[mask_deep]
                p_deep = pres_series[mask_deep]
                
                if len(s_deep) > 1:
                    gradient = s_deep.diff() / p_deep.diff()
                    if "TEMP" in var.upper():
                        v_s["grad_depth"] = float(p_deep.loc[gradient.idxmin()])
                    elif "PSAL" in var.upper():
                        v_s["grad_depth"] = float(p_deep.loc[gradient.abs().idxmax()])
                    elif "DOXY" in var.upper():
                        v_s["min_val_depth"] = float(p_deep.loc[s_deep.idxmin()])
                    elif "CHLA" in var.upper():
                        v_s["max_val_depth"] = float(p_deep.loc[s_deep.idxmax()])
                
                p_stats[var] = v_s
            all_profile_stats.append(p_stats)

        # Aggregate per-profile stats into a global average
        for var in variables:
            relevant_stats = [ps[var] for ps in all_profile_stats if var in ps]
            if not relevant_stats: continue
            
            # Aggregate scalar observations across valid profiles. The
            # descriptive values retain the legacy per-profile averaging;
            # count is a total, because it represents actual observations.
            agg = {
                "min": float(np.nanmin([s["min"] for s in relevant_stats])),
                "max": float(np.nanmax([s["max"] for s in relevant_stats])),
                "median": float(np.nanmedian([s["median"] for s in relevant_stats])),
                "mean": float(np.nanmean([s["mean"] for s in relevant_stats])),
                "count": int(sum(s["count"] for s in relevant_stats)),
                "surface": float(np.nanmean([s["surface"] for s in relevant_stats])),
                "deep": float(np.nanmean([s["deep"] for s in relevant_stats])),
                "deepest_pres": float(np.nanmean([s["deepest_pres"] for s in relevant_stats])),
                "deepest_val": float(np.nanmean([s["deepest_val"] for s in relevant_stats])),
            }
            
            # Average the depths (weighted or simple mean)
            # Fix: Check if ANY profile had the depth, not just the first one.
            depth_keys = ["grad_depth", "min_val_depth", "max_val_depth"]
            for dk in depth_keys:
                depths = [s[dk] for s in relevant_stats if dk in s]
                if depths: 
                    agg[dk] = float(np.nanmean(depths))
                
            aggregated_stats[var] = agg
            
        return aggregated_stats

    def _generate_kb_explanation(
        self,
        intent: ParsedIntent,
        records: List[MetadataRecord],
        variables: List[str],
        data_summary: Dict[str, Any],
    ) -> str:
        """KB-based fallback."""
        parts = ["General scientific context:"]
        vars_upper = {v.upper() for v in variables}
        for v in vars_upper:
            if v in self.kb: parts.append(self.kb[v])
        return " ".join(parts)

    def _humanize_feature(self, feature: str) -> str:
        """Render a ``VerticalFeature.feature`` token for narrative prose.

        Inlined to avoid the runtime circular import with
        ``ScientificFeatureExtractor`` (which itself imports this module
        to access ``_compute_stats``). The mapping mirrors
        ``features._FEATURE_HUMAN_NAME`` and falls back to title-cased
        rendering for unknown feature tokens.
        """
        names = {
            "thermocline": "thermocline",
            "halocline": "halocline",
            "oxygen_minimum": "Oxygen minimum",
            "dcm": "Deep chlorophyll maximum",
        }
        return names.get(feature, feature.replace("_", " ").title())

    @staticmethod
    def _format_scientific_value(value: float) -> str:
        """Use compact, magnitude-aware display precision in fallback prose."""
        return format(value, ".4g")

    def _format_prose_from_facts(
        self,
        facts: ScientificFacts,
        records: list[MetadataRecord],
    ) -> str:
        """Render a concise, evidence-bounded deterministic fallback.

        This path is used after an LLM failure, so it must read as a short
        scientific report rather than as a field dump. It uses only supplied
        facts and makes no causal or mechanism claims.
        """
        paragraphs: list[str] = []

        if facts.cross_variable_notes:
            paragraphs.append(" ".join(facts.cross_variable_notes[:3]))

        feature_phrases: list[str] = []
        for feature in facts.features:
            name = self._humanize_feature(feature.feature)
            leading_word = feature.prominence or name
            article = "an" if leading_word[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
            descriptor = (
                f"{article} {feature.prominence} {name}"
                if feature.prominence
                else f"{article} {name}"
            )
            if feature.depth_dbar is not None:
                feature_phrases.append(f"{descriptor} near {feature.depth_dbar:.0f} dbar")
            else:
                feature_phrases.append(descriptor)
        if feature_phrases:
            paragraphs.append(
                "The identified vertical structure includes "
                + "; ".join(feature_phrases)
                + "."
            )

        structure_sentences: list[str] = []
        for stat in facts.stats:
            name = stat.variable.replace("_ADJUSTED", "").replace("_", " ")
            if (
                stat.surface_mean_0_10m is not None
                and stat.deep_mean_below_200m is not None
            ):
                direction = (
                    "decreases"
                    if stat.deep_mean_below_200m < stat.surface_mean_0_10m
                    else "increases"
                    if stat.deep_mean_below_200m > stat.surface_mean_0_10m
                    else "is similar"
                )
                structure_sentences.append(
                    f"{name} {direction} from "
                    f"{self._format_scientific_value(stat.surface_mean_0_10m)} {stat.units} "
                    f"near the surface to "
                    f"{self._format_scientific_value(stat.deep_mean_below_200m)} {stat.units} "
                    "in the deep reference layer."
                )
            elif stat.min_val is not None and stat.max_val is not None:
                structure_sentences.append(
                    f"{name} spans {self._format_scientific_value(stat.min_val)} to "
                    f"{self._format_scientific_value(stat.max_val)} {stat.units} "
                    "across the sampled profile."
                )
        if structure_sentences:
            paragraphs.append(" ".join(structure_sentences))

        delayed_pct = facts.qc.delayed_mode_pct
        if delayed_pct >= 80.0:
            quality = "predominantly delayed-mode quality-controlled"
        elif delayed_pct >= 50.0:
            quality = "mostly delayed-mode, with some real-time profiles"
        else:
            quality = "a mixed real-time and delayed-mode collection"
        paragraphs.append(
            f"The quality context is {quality} ({delayed_pct:.0f}% delayed-mode); "
            "the observations establish the reported vertical patterns but do not, "
            "by themselves, identify their dominant mechanisms."
        )

        return "\n\n".join(paragraphs)

    def _generate_data_driven_explanation(
        self,
        intent: ParsedIntent,
        records: List[MetadataRecord],
        variables: List[str],
        df: pd.DataFrame,
        facts: Optional["ScientificFacts"] = None,
    ) -> str:
        """Generate the deterministic scientific explanation.

        When ``facts`` is provided (Phase 1+2+3 enriched), consumes it and
        produces discussion-quality prose that uses pre-classified feature
        prominences, feature strengths, and cross-variable relationship
        notes. Otherwise, falls back to the legacy bullet-style path that
        computes stats directly from ``df``.

        Public callers should pass ``facts=None`` only when no
        ``ScientificFeatureExtractor`` is wired into this engine.
        """
        if facts is not None:
            return self._format_prose_from_facts(facts, records)

        # Legacy path: compute stats directly from the DataFrame. Preserved
        # for backwards compatibility with callers that do not have a
        # ScientificFeatureExtractor wired (e.g. production wiring tests).
        stats = self._compute_stats(df, variables)

        # 1. Summary section
        summary_parts: List[str] = []
        for var in variables:
            if var not in stats:
                continue
            s = stats[var]
            definition = VariableRegistry.get(var)
            v_name = definition.display_label if definition else var.replace("_", " ").title()

            if "TEMP" in var.upper():
                if math.isfinite(s["surface"]):
                    summary_parts.append(f"• Surface {v_name}: {s['surface']:.1f}°C")
                if "grad_depth" in s and math.isfinite(s["grad_depth"]):
                    summary_parts.append(f"• Thermocline: {s['grad_depth']:.0f} dbar")
            elif "PSAL" in var.upper():
                if math.isfinite(s["surface"]):
                    summary_parts.append(f"• Surface {v_name}: {s['surface']:.2f} PSU")
                if "grad_depth" in s and math.isfinite(s["grad_depth"]):
                    summary_parts.append(f"• Halocline: {s['grad_depth']:.0f} dbar")
            elif "DOXY" in var.upper():
                if math.isfinite(s["surface"]):
                    summary_parts.append(
                        f"• Surface {v_name}: {s['surface']:.1f} µmol/kg"
                    )
                if "min_val_depth" in s and math.isfinite(s["min_val_depth"]):
                    summary_parts.append(
                        f"• Oxygen Minimum: {s['min_val_depth']:.0f} dbar"
                    )
            elif "CHLA" in var.upper():
                if math.isfinite(s["surface"]):
                    summary_parts.append(
                        f"• Surface {v_name}: {s['surface']:.3f} mg/m³"
                    )
                if "max_val_depth" in s and math.isfinite(s["max_val_depth"]):
                    summary_parts.append(f"• DCM Depth: {s['max_val_depth']:.0f} dbar")
            elif "BBP700" in var.upper():
                if math.isfinite(s["surface"]):
                    summary_parts.append(
                        f"• Surface {v_name}: {s['surface']:.4f} m^-1"
                    )

        summary_text = "\n" + "\n".join(summary_parts) if summary_parts else ""

        # 2. Interpretation section
        interp_parts: List[str] = []

        # Variable-specific narratives
        for var in variables:
            if var not in stats:
                continue
            s = stats[var]

            if "TEMP" in var.upper():
                if (
                    math.isfinite(s["surface"])
                    and math.isfinite(s["deepest_val"])
                    and math.isfinite(s["deepest_pres"])
                ):
                    delta = s["surface"] - s["deepest_val"]
                    interp_parts.append(
                        f"Surface waters average {s['surface']:.1f}°C, cooling to {s['deepest_val']:.1f}°C "
                        f"at {s['deepest_pres']:.0f} dbar. A total decrease of {delta:.1f}°C "
                        f"indicates strong vertical stratification."
                    )
            elif "PSAL" in var.upper():
                if (
                    math.isfinite(s["min"])
                    and math.isfinite(s["max"])
                    and math.isfinite(s["surface"])
                    and math.isfinite(s["deepest_val"])
                ):
                    delta = abs(s["surface"] - s["deepest_val"])
                    interp_parts.append(
                        f"Salinity ranges from {s['min']:.2f} to {s['max']:.2f} PSU (global range), "
                        f"with an average change of {delta:.2f} PSU from surface to deep waters, "
                        f"reflecting regional evaporation and precipitation patterns."
                    )

            elif "DOXY" in var.upper():
                if (
                    "min_val_depth" in s
                    and math.isfinite(s["min_val_depth"])
                    and math.isfinite(s["min"])
                ):
                    if s["min"] < 100:
                        interp_parts.append(
                            f"A pronounced Oxygen Minimum Zone (OMZ) is observed at {s['min_val_depth']:.0f} dbar "
                            f"with concentrations falling to {s['min']:.1f} µmol/kg."
                        )
                    else:
                        interp_parts.append(
                            f"Lowest oxygen ({s['min']:.1f} µmol/kg) occurs near {s['min_val_depth']:.0f} dbar, "
                            f"but concentrations remain relatively high throughout the water column."
                        )
            elif "CHLA" in var.upper():
                if (
                    "max_val_depth" in s
                    and math.isfinite(s["max_val_depth"])
                    and s["max_val_depth"] > 15
                ):
                    interp_parts.append(
                        f"A genuine Deep Chlorophyll Maximum (DCM) is detected at {s['max_val_depth']:.0f} dbar, "
                        f"indicating a subsurface peak in primary productivity."
                    )
                else:
                    interp_parts.append(
                        "The maximum chlorophyll concentration is located near the surface."
                    )
            elif "BBP700" in var.upper():
                if math.isfinite(s["deepest_val"]) and math.isfinite(s["surface"]):
                    delta = s["deepest_val"] - s["surface"]
                    trend = "increasing" if delta > 0 else "decreasing"
                    interp_parts.append(
                        f"Particle backscatter shows a {trend} trend with depth, "
                        f"changing from {s['surface']:.4f} to {s['deepest_val']:.4f} m^-1, "
                        f"reflecting variations in particle size and concentration."
                    )

        # Integrated Multi-variable reasoning
        core_vars: Dict[str, str] = {}
        for v in variables:
            if "TEMP" in v.upper():
                core_vars["TEMP"] = v
            if "PSAL" in v.upper():
                core_vars["PSAL"] = v
            if "DOXY" in v.upper():
                core_vars["DOXY"] = v
            if "CHLA" in v.upper():
                core_vars["CHLA"] = v

        if "TEMP" in core_vars and "DOXY" in core_vars:
            t_var, d_var = core_vars["TEMP"], core_vars["DOXY"]
            if t_var in stats and d_var in stats:
                s_t, s_d = stats[t_var], stats[d_var]
                if math.isfinite(s_t["surface"]) and math.isfinite(s_d["min"]):
                    grad_depth = s_t.get("grad_depth", 0)
                    grad_str = f"{grad_depth:.0f}" if math.isfinite(grad_depth) else "unknown"
                    interp_parts.append(
                        f"Warm surface waters ({s_t['surface']:.1f}°C) correspond to higher oxygen levels, "
                        f"while the oxygen minimum ({s_d['min']:.1f} µmol/kg) typically emerges below the "
                        f"thermocline ({grad_str} dbar), indicating limited ventilation."
                    )

        if "TEMP" in core_vars and "CHLA" in core_vars:
            t_var, c_var = core_vars["TEMP"], core_vars["CHLA"]
            if t_var in stats and c_var in stats:
                s_t, s_c = stats[t_var], stats[c_var]
                if "grad_depth" in s_t and "max_val_depth" in s_c:
                    t_depth, c_depth = s_t["grad_depth"], s_c["max_val_depth"]
                    if (
                        math.isfinite(t_depth)
                        and math.isfinite(c_depth)
                        and abs(t_depth - c_depth) < 50
                    ):
                        interp_parts.append(
                            f"The chlorophyll maximum ({c_depth:.0f} dbar) is closely aligned with the "
                            f"thermocline ({t_depth:.0f} dbar), a common feature in stratified oceans."
                        )

        if "TEMP" in core_vars and "PSAL" in core_vars:
            t_var, p_var = core_vars["TEMP"], core_vars["PSAL"]
            if t_var in stats and p_var in stats:
                s_t, s_p = stats[t_var], stats[p_var]
                if (
                    math.isfinite(s_t["surface"])
                    and math.isfinite(s_p["surface"])
                    and s_t["surface"] > 20
                    and s_p["surface"] > 35
                ):
                    interp_parts.append(
                        "The combination of high surface temperature and high salinity suggests "
                        "strong evaporative forcing in this region."
                    )

        interpretation_text = (
            "\n\nInterpretation\n" + " ".join(interp_parts) if interp_parts else ""
        )

        # 3. Concise Data Quality
        qc_parts: List[str] = []
        has_real_time = any("R" in (r.parameter_data_mode or "") for r in records)
        if has_real_time:
            qc_parts.append("Some profiles contain real-time data (preliminary).")
        else:
            qc_parts.append("Most measurements are delayed-mode quality-controlled.")

        qc_text = "\n\nData quality\n" + " ".join(qc_parts)

        return f"{summary_text}\n{interpretation_text}\n{qc_text}"

    def generate_explanation(
        self,
        intent: ParsedIntent,
        records: List[MetadataRecord],
        variables: List[str],
        data_summary: Dict[str, Any],
        df: Optional[pd.DataFrame] = None,
    ) -> str:
        """Generate guarded LLM narration or the enriched deterministic fallback.

        Execution order:

        1. If ``df`` is empty or ``None`` → KB explanation.
        2. If narration is **explicitly disabled** (operator setting) →
           return the legacy bullet-style output without consulting the
           feature extractor. The ``sci_narrator_enabled = False`` path is
           the documented "off switch" and must remain bit-stable.
        3. If narration is enabled but the pipeline is incomplete
           (no feature_extractor / prompt_builder / narrator / etc.) →
           return the legacy bullet-style output.
        4. Build ``ScientificFacts`` (deterministic; failure tolerated).
        5. Try the LLM pipeline (narrate → parse → verify).
        6. On any failure, return the **enriched** fallback that consumes
           the Phase 1+2+3 ``ScientificFacts`` (cross_variable_notes,
           pre-classified prominences, strengths). When facts could not
           be built, the legacy path is used.
        """
        if df is None or df.empty:
            return self._generate_kb_explanation(intent, records, variables, data_summary)

        if not self._narration_is_enabled():
            return self._generate_data_driven_explanation(
                intent, records, variables, df=df, facts=None
            )

        if not self._narration_pipeline_is_ready():
            facts = self._safe_extract_facts(df, variables, intent, records)
            return self._generate_data_driven_explanation(
                intent, records, variables, df=df, facts=facts
            )

        # Build facts first (deterministic; failure tolerated).
        facts = self._safe_extract_facts(df, variables, intent, records)

        # Try the LLM pipeline.
        if facts is not None:
            try:
                prompt = self.prompt_builder.build(facts)
                logger.info(
                    "Scientific narration final prompt size_bytes=%d",
                    len(prompt.encode("utf-8")),
                )
                raw_output = self.narrator.generate(prompt)
                parsed_output = self.output_parser.parse(raw_output)
                verified_output = self.verification_guard.verify(parsed_output, facts)
                return verified_output.explanation
            except Exception as exc:
                logger.warning(
                    "Scientific narration failed; using deterministic template: %s",
                    type(exc).__name__,
                )

        # Fallback: enriched (facts-aware) if facts were built; legacy otherwise.
        return self._generate_data_driven_explanation(
            intent, records, variables, df=df, facts=facts
        )

    def _safe_extract_facts(
        self,
        df: pd.DataFrame,
        variables: List[str],
        intent: ParsedIntent,
        records: List[MetadataRecord],
    ) -> Optional["ScientificFacts"]:
        """Extract ``ScientificFacts`` defensively; return ``None`` on failure."""
        if self.feature_extractor is None:
            return None
        try:
            return self.feature_extractor.extract(df, variables, intent, records)
        except Exception as exc:
            logger.warning(
                "Feature extraction failed; falling back to raw stats: %s",
                type(exc).__name__,
            )
            return None

    def _narration_is_enabled(self) -> bool:
        if self.narrator_enabled is not None:
            return self.narrator_enabled
        return settings.sci_narrator_enabled

    def _narration_pipeline_is_ready(self) -> bool:
        return all(
            component is not None
            for component in (
                self.feature_extractor,
                self.prompt_builder,
                self.narrator,
                self.output_parser,
                self.verification_guard,
            )
        )
