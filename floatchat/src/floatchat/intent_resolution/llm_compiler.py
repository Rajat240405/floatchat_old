"""LLM intent compiler — the resolver's single LLM fallback path.

Relocated from the removed ``entity_extractor`` package during Cleanup M2
(legacy LLM fallback removal). The class body is verbatim: prompts, merge
rules, and graceful-degradation behavior are unchanged.

Ownership: ``IntentResolver`` is the ONLY runtime caller. The compiler is
invoked only when the deterministic regex parser cannot fill intent fields;
it emits ParsedIntent JSON directly and can never overwrite deterministic
seed values.
"""

import json
import logging

from floatchat.config import settings

logger = logging.getLogger(__name__)


class LLMIntentCompiler:
    """Fallback LLM compiler that emits ParsedIntent JSON directly."""

    _SYSTEM = """You are a fallback intent compiler for FloatChat.
Return ONLY JSON matching ParsedIntent. Do not return QuerySpec, English rewrites,
SQL, or explanations. Fill only fields that are missing from the deterministic
seed. Preserve every non-null seed value exactly. Variables must use canonical
Argo names. Allowed intents include profile_plot, region_search, time_series,
hovmoller, ts_diagram, comparison_plot, trajectory, nearest_float,
radius_search, metadata_lookup, count_aggregate, or unknown."""

    def __init__(self, service=None) -> None:
        self._service = service
        self._tried = service is not None

    def _get_service(self):
        if self._service is None and not self._tried:
            self._tried = True
            try:
                from floatchat.llm_service.factory import build_compiler_llm_service
                self._service = build_compiler_llm_service()
            except Exception as exc:
                logger.warning("Could not build intent compiler service: %s", exc)
        return self._service

    def compile(self, message: str, seed=None):
        if not settings.extractor_model:
            return None
        service = self._get_service()
        if service is None:
            return None
        seed_json = seed.model_dump(exclude_none=True) if seed is not None else {}
        prompt = (
            f"Compile this user request into ParsedIntent JSON:\n{message}\n\n"
            f"Deterministic seed (preserve non-null fields):\n{json.dumps(seed_json)}"
        )
        try:
            raw = service.generate(prompt, system=self._SYSTEM)
            data = json.loads(raw)
            from floatchat.models import ParsedIntent
            candidate = ParsedIntent.model_validate(data)
            if seed is None:
                return candidate
            # Compiler cannot overwrite deterministic fields.
            merged = seed.model_dump()
            for name in type(seed).model_fields:
                if merged.get(name) in (None, []) and getattr(candidate, name) not in (None, []):
                    merged[name] = getattr(candidate, name)
            return ParsedIntent.model_validate(merged)
        except Exception as exc:
            logger.warning("Intent compiler failed: %s", exc)
            return None
