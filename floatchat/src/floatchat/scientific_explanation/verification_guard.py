"""Strict numeric grounding guard for scientific narration.

The guard validates an already-parsed ``NarratorOutput`` exclusively against a
``ScientificFacts`` object. It never receives or inspects NetCDF datasets,
NumPy arrays, or pandas DataFrames.
"""

from __future__ import annotations

import logging
import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from floatchat.exceptions import NarrationVerificationError
from floatchat.scientific_explanation.schemas import NarratorOutput, ScientificFacts

logger = logging.getLogger(__name__)

_NUMBER_PATTERN = re.compile(
    r"(?<![\d.])"
    r"(?P<number>[+\-−]?"
    r"(?:"
    r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"|\.\d+"
    r")"
    r"(?:[eE][+\-]?\d+)?"
    r")"
)


class VerificationGuard:
    """Reject narrator output containing numbers absent from the facts allowlist."""

    def verify(self, output: NarratorOutput, facts: ScientificFacts) -> NarratorOutput:
        """Return ``output`` only when every narrated number is grounded.

        Matching permits only an exact fact value or deterministic decimal
        rounding to the precision used in the narration. It does not permit
        tolerance-based matching, new arithmetic, or unit conversion.
        """
        if not isinstance(output, NarratorOutput):
            raise TypeError("VerificationGuard output must be NarratorOutput")
        if not isinstance(facts, ScientificFacts):
            raise TypeError("VerificationGuard facts must be ScientificFacts")

        allowed: set[Decimal] = set()
        claims: list[tuple[str, Decimal]] = []
        try:
            allowed = self._allowed_decimals(facts.numeric_allowlist())
            narrated_text = "\n".join([output.explanation, *output.key_findings])
            narrated_text = self._mask_numeric_identifiers_and_units(narrated_text, facts)
            narrated_text = self._mask_grounded_dates(narrated_text, facts)
            narrated_text = self._mask_semantic_depth_references(narrated_text, facts)
            claims = self._extract_numeric_claims(narrated_text)

            unsupported: list[str] = []
            for token, value in claims:
                is_grounded = self._matches_grounded_value(token, value, allowed)
                if not is_grounded and token not in unsupported:
                    unsupported.append(token)

            if unsupported:
                raise NarrationVerificationError(
                    "Narrator output contains numeric claims not grounded in ScientificFacts.",
                    details={
                        "unsupported_numbers": unsupported,
                        "numeric_claim_count": len(claims),
                    },
                )
        except NarrationVerificationError as exc:
            logger.warning(
                "Narration verification rejected: unsupported_numbers=%s "
                "numeric_claim_count=%d allowlist_size=%d",
                exc.details.get("unsupported_numbers", []),
                exc.details.get("numeric_claim_count", len(claims)),
                len(allowed),
            )
            logger.debug(
                "Rejected parsed NarratorOutput: %s",
                output.model_dump(mode="json"),
            )
            raise

        # Phase 4: Post-numeric variable check.
        # Verify the narrator doesn't mention variables that weren't queried.
        narrated_full = "\n".join([output.explanation, *output.key_findings]).lower()
        _VAR_ALIASES = {
            "TEMP": ["temperature", "temp ", "sst"],
            "PSAL": ["salinity", "psal", "salt "],
            "DOXY": ["oxygen", "doxy", "dissolved o2", "o2"],
            "CHLA": ["chlorophyll", "chla", "chl"],
            "NITRATE": ["nitrate", "no3"],
            "BBP700": ["backscatter", "bbp"],
            "PH_IN_SITU_TOTAL": ["ph level", "acidity"],
        }
        queried = set()
        for v in facts.variables_requested:
            queried.add(v.upper())
            queried.add(v.upper().replace("_ADJUSTED", ""))
        for var_code, aliases in _VAR_ALIASES.items():
            if var_code not in queried and var_code.replace("_IN_SITU_TOTAL", "") not in queried:
                for alias in aliases:
                    if alias in narrated_full:
                        logger.warning(
                            "Narrator mentioned %r (%s) which was not in queried variables %s — "
                            "this is a potential variable mislabel",
                            alias, var_code, facts.variables_requested,
                        )
                        break

        return output

    @staticmethod
    def _allowed_decimals(allowlist: Any) -> set[Decimal]:
        if not isinstance(allowlist, dict):
            raise NarrationVerificationError(
                "ScientificFacts numeric allowlist is invalid.",
                details={"reason": "allowlist_not_object"},
            )

        allowed: set[Decimal] = set()
        for values in allowlist.values():
            if not isinstance(values, list):
                raise NarrationVerificationError(
                    "ScientificFacts numeric allowlist is invalid.",
                    details={"reason": "allowlist_group_not_list"},
                )
            for value in values:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise NarrationVerificationError(
                        "ScientificFacts numeric allowlist is invalid.",
                        details={"reason": "allowlist_value_not_numeric"},
                    )
                if not math.isfinite(float(value)):
                    raise NarrationVerificationError(
                        "ScientificFacts numeric allowlist is invalid.",
                        details={"reason": "allowlist_value_not_finite"},
                    )
                allowed.add(Decimal(str(value)))
        return allowed

    @staticmethod
    def _matches_grounded_value(
        token: str,
        value: Decimal,
        allowed: set[Decimal],
    ) -> bool:
        """Match a narrated value against the numeric allowlist.

        Two acceptance paths:

        1. **Exact match** — the value is in the allowlist verbatim.
        2. **Quantum-precision rounding** — the value matches any allowlist
           value after rounding to the token's decimal precision
           (e.g. ``"25"`` with quantum 1 may match ``25.0`` rounded
           to ``25``; ``"25.1"`` with quantum 0.1 may match ``25.123``
           rounded to ``25.1``).

        The guard does not permit tolerance-based matching, derived
        arithmetic, or unit conversion. A value of ``125.4`` does not
        authorize narration of ``125.5`` even if both represent the same
        measurement — the LLM is instructed not to independently round.
        Hallucinated values (e.g. ``999`` when only ``1000`` is grounded)
        remain rejected.
        """
        if value in allowed:
            return True

        normalized = token.replace(",", "").replace("−", "-")
        if "e" in normalized.lower():
            return False

        unsigned = normalized.lstrip("+-")
        if "." in unsigned:
            decimal_places = len(unsigned.rsplit(".", 1)[1])
            quantum = Decimal(1).scaleb(-decimal_places)
        else:
            trailing_zeros = len(unsigned) - len(unsigned.rstrip("0"))
            quantum = (
                Decimal(1).scaleb(trailing_zeros)
                if trailing_zeros and unsigned.rstrip("0")
                else Decimal(1)
            )

        for grounded in allowed:
            try:
                if grounded.quantize(quantum, rounding=ROUND_HALF_UP) == value:
                    return True
            except InvalidOperation:
                continue
        return False

    @staticmethod
    def _extract_numeric_claims(text: str) -> list[tuple[str, Decimal]]:
        claims: list[tuple[str, Decimal]] = []
        for match in _NUMBER_PATTERN.finditer(text):
            token = match.group("number")
            normalized = token.replace(",", "").replace("−", "-")
            try:
                value = Decimal(normalized)
            except InvalidOperation as exc:  # defensive: regex should prevent this
                raise NarrationVerificationError(
                    "Narrator output contains an unreadable numeric claim.",
                    details={"numeric_token": token},
                ) from exc
            if not value.is_finite():
                raise NarrationVerificationError(
                    "Narrator output contains a non-finite numeric claim.",
                    details={"numeric_token": token},
                )
            claims.append((token, value))
        return claims

    @staticmethod
    def _mask_numeric_identifiers_and_units(text: str, facts: ScientificFacts) -> str:
        """Mask digits that belong to known variable names or unit exponents.

        Names such as ``BBP700`` and units such as ``m^-1`` contain digits but
        are identifiers, not narrated measurement values. Only exact tokens
        supplied by ``ScientificFacts`` receive this treatment.
        """
        identifiers = {
            *facts.variables_requested,
            *(stat.variable for stat in facts.stats),
            *(feature.feature for feature in facts.features),
        }
        if facts.float_id:
            identifiers.add(facts.float_id)
        for profile in facts.profiles:
            identifiers.add(profile.float_id)
            if profile.source_file:
                identifiers.add(profile.source_file)
                identifiers.add(profile.source_file.rsplit("/", 1)[-1])
        for file_path in facts.provenance.gdac_files:
            identifiers.add(file_path)
            identifiers.add(file_path.rsplit("/", 1)[-1])

        units = {stat.units for stat in facts.stats}

        masked = text
        for token in sorted(identifiers, key=len, reverse=True):
            if not token or not any(character.isdigit() for character in token):
                continue
            pattern = re.compile(
                rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])",
                re.IGNORECASE,
            )
            masked = pattern.sub(" ", masked)

        for unit in sorted(units, key=len, reverse=True):
            if not unit or not any(character.isdigit() for character in unit):
                continue
            masked = re.sub(re.escape(unit), " ", masked, flags=re.IGNORECASE)

        return masked

    @staticmethod
    def _mask_grounded_dates(text: str, facts: ScientificFacts) -> str:
        """Mask only date strings that already occur in ``ScientificFacts``.

        Date tokens are otherwise treated as numeric claims. This lets a
        narrator cite an observed profile date while retaining rejection of a
        fabricated observation date.
        """
        date_strings = {
            value[:10]
            for value in (
                facts.provenance.date_start,
                facts.provenance.date_end,
                *(profile.profile_date for profile in facts.profiles),
            )
            if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.*)?", value)
        }
        masked = text
        for date_string in sorted(date_strings, key=len, reverse=True):
            masked = re.sub(
                rf"(?<![\d]){re.escape(date_string)}(?![\d])",
                " ",
                masked,
            )
        return masked

    @staticmethod
    def _mask_semantic_depth_references(text: str, facts: ScientificFacts) -> str:
        """Mask non-measurement reference syntax with deterministic support.

        Numeric values attached to depth/pressure units and percentages are
        deliberately *not* masked: they must be present in the factual numeric
        allowlist. This preserves rejection of fabricated depths and QC
        percentages. The only exceptions are schema-defined reference horizons
        and literature citations, neither of which claims a sampled value.
        """
        masked = text

        # Literature citation years in parentheses.
        # Examples: "(1982)", "(1982, p. 10)", "(1982; 2009)",
        #           "(Paulmier & Ruiz-Pino, 2009)", "(Levitus 1982)".
        masked = re.sub(
            r"\(\s*[12]\d{3}[a-z]?(?:\s*[,;]\s*[^)]*?[12]\d{3}[a-z]?)?\s*\)",
            " ",
            masked,
        )
        # Standalone year citations after a capitalised name and space:
        # e.g. "Levitus 1982", "Paulmier 2009". Uses a capture group
        # (not a variable-width lookbehind, which Python ``re`` rejects).
        masked = re.sub(
            r"\b([A-Z][a-z]{2,})\s+([12]\d{3}[a-z]?)\b",
            r"\1 ",
            masked,
        )

        # Schema-defined depth horizons (kept for backward compatibility).
        if any(stat.surface_mean_0_10m is not None for stat in facts.stats):
            surface_patterns = (
                r"(?<![A-Za-z0-9_])~?\s*0\s*(?:-|–|—|to)\s*10\s*"
                r"(?:m\b|meters?\b|metres?\b)",
                r"(?<![A-Za-z0-9_])surface(?:[-\s]+(?:layer|waters?|zone))?\s*"
                r"(?:\(|of\s+|in\s+|within\s+)?10\s*(?:m\b|meters?\b|metres?\b)",
                r"(?<![A-Za-z0-9_])(?:upper|top|first)\s+10\s*"
                r"(?:m\b|meters?\b|metres?\b)",
                r"(?<![A-Za-z0-9_])10\s*(?:m\b|meters?\b|metres?\b)\s+"
                r"(?:surface|near-surface)(?:[-\s]+(?:layer|waters?|zone))?",
            )
            for pattern in surface_patterns:
                masked = re.sub(pattern, " ", masked, flags=re.IGNORECASE)
        if any(stat.deep_mean_below_200m is not None for stat in facts.stats):
            masked = re.sub(
                r"(?<![A-Za-z0-9_])below\s+200\s*(?:m\b|meters?\b|metres?\b)",
                " ",
                masked,
                flags=re.IGNORECASE,
            )
        return masked


__all__ = ["VerificationGuard"]
