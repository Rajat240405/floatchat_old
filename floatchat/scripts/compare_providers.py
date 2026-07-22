#!/usr/bin/env python3
"""compare_providers.py — A/B/C test harness for Ollama vs Gemini vs Groq.

Run the SAME queries through each provider and print a side-by-side decision
table so you can diagnose model hallucination vs code-design issues.

USAGE (from the floatchat/ package dir):
    # Ollama baseline (must have `ollama serve` running + qwen2.5:3b pulled)
    python scripts/compare_providers.py --provider ollama

    # Gemini (get a key from https://aistudio.google.com/apikey)
    export GEMINI_API_KEY=...
    python scripts/compare_providers.py --provider gemini

    # Groq with OpenAI GPT-OSS-120B (get a key from https://console.groq.com)
    export GROQ_API_KEY=...
    python scripts/compare_providers.py --provider groq

Run all three, then diff the JSON outputs to compare. Or pass --all to attempt
all providers and skip any that are unavailable.

This harness calls ONLY the entity extractor (the LLM job most prone to
hallucination). It does NOT touch the data lake or GDAC — pure extractor A/B.
"""
import argparse
import json
import os
import sys
import time

# Ensure src/ is importable when run from the package root.
sys.path.insert(0, "src")

from floatchat.config import settings  # noqa: E402
from floatchat.entity_extractor.extractor import LLMEntityExtractor  # noqa: E402
from floatchat.llm_service.factory import build_extractor_llm_service  # noqa: E402


# The 11 canonical test queries + the tricky ones that broke in production.
TEST_QUERIES = [
    "temperature in Arabian Sea 2024",
    "salinity in Bay of Bengal",
    "show floats near Sri Lanka",
    "oxygen in Arabian Sea 2024",
    "chlorophyll in Bay of Bengal",
    "Show me floats that were alive near Goa around the last monsoon",
    "floats alive near Goa last summer",
    "deep oxygen in Bay of Bengal",
    "temperature in Arabian Sea during monsoon",
    # Ambiguous queries that stress the extractor:
    "what about chlorophyll there",
    "compare that with the Indian Ocean",
]


def run_provider(provider: str) -> list[dict]:
    """Run all test queries through *provider*'s extractor, return results."""
    print(f"\n{'='*70}")
    print(f"  Provider: {provider.upper()}")
    print(f"{'='*70}")

    # Build the extractor with this provider's service injected.
    try:
        # Force the provider via env so the factory picks it up.
        os.environ["FLOATCHAT_LLM_PROVIDER"] = provider
        # Reload settings so the env change takes effect.
        import importlib
        import floatchat.config as c
        importlib.reload(c)
        import floatchat.llm_service.factory as f
        importlib.reload(f)
        from floatchat.llm_service.factory import build_extractor_llm_service
        service = build_extractor_llm_service()
    except Exception as exc:
        print(f"  [SKIP] provider unavailable: {exc}")
        return []

    actual_provider = type(service).__name__
    actual_model = getattr(service, "model", "?")
    print(f"  Service: {actual_provider} | model: {actual_model}\n")

    extractor = LLMEntityExtractor(service=service)

    results = []
    for q in TEST_QUERIES:
        t0 = time.perf_counter()
        try:
            spec = extractor.extract(q)
            elapsed = time.perf_counter() - t0
            if spec is None:
                row = {"query": q, "provider": provider, "service": actual_provider,
                       "model": actual_model, "result": None, "elapsed_s": round(elapsed, 2),
                       "error": None}
            else:
                row = {"query": q, "provider": provider, "service": actual_provider,
                       "model": actual_model, "elapsed_s": round(elapsed, 2),
                       "result": spec.model_dump(), "error": None}
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            row = {"query": q, "provider": provider, "service": actual_provider,
                   "model": actual_model, "result": None, "elapsed_s": round(elapsed, 2),
                   "error": str(exc)}

        # Compact on-screen summary
        if row["result"] is None:
            print(f"  • {q!r}")
            print(f"      -> None (no meaningful extraction) [{row['elapsed_s']}s]")
        else:
            r = row["result"]
            print(f"  • {q!r}")
            print(f"      -> action={r.get('action')} vars={r.get('variables')} "
                  f"spatial={r.get('spatial_filter')} time={r.get('time_filter')} "
                  f"float={r.get('float_id')} op={r.get('operational_filter')} "
                  f"conf={r.get('confidence')} [{row['elapsed_s']}s]")
        if row["error"]:
            print(f"      ERROR: {row['error']}")
        results.append(row)

    return results


def main():
    ap = argparse.ArgumentParser(description="A/B/C compare LLM extractor providers.")
    ap.add_argument("--provider", choices=["ollama", "gemini", "groq"],
                    help="Which provider to test.")
    ap.add_argument("--all", action="store_true",
                    help="Run all three providers, skipping unavailable ones.")
    ap.add_argument("--out", default=None,
                    help="Write JSON results to this file (default: provider_results_<name>.json).")
    args = ap.parse_args()

    if not args.provider and not args.all:
        ap.error("specify --provider <name> or --all")

    providers = ["ollama", "gemini", "groq"] if args.all else [args.provider]
    all_results = {}
    for p in providers:
        all_results[p] = run_provider(p)

    # Write JSON for easy diffing
    out_file = args.out or f"provider_results.json"
    with open(out_file, "w") as fh:
        json.dump(all_results, fh, indent=2)
    print(f"\n{'='*70}")
    print(f"Results written to {out_file}")
    print(f"{'='*70}")
    print("\nTIP: run with each provider, then compare the JSON outputs:")
    print("  - Same query, different results across providers = model quality issue")
    print("  - Same query, same WRONG result across providers = code design issue")
    print("  - Look for: invented regions (bay_of_bengal on Goa queries),")
    print("    dropped variables, placeholder time_filter ('year', '>=').")


if __name__ == "__main__":
    main()
