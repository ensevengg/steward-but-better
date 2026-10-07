"""Opt-in real provider check. Never exports credentials or raw provider errors."""

import argparse
import json
from pathlib import Path
import time
from src.brain.contracts import CaseInput
from src.brain.judging import assess
from src.brain.providers import review_with_opencode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:4096")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, default=Path("test-results/provider.json"))
    args = parser.parse_args()
    case = CaseInput.model_validate_json(Path("benchmarks/sao_paulo_2025.json").read_text(encoding="utf-8"))
    results = []
    variants = [case, case.model_copy(update={"evidence_mode": "telemetry_only", "observations": []})]
    for variant in variants:
        started = time.monotonic()
        row = {"evidence_mode": variant.evidence_mode, "provider": args.provider, "model": args.model}
        try:
            result = review_with_opencode(
                assess(variant), base_url=args.url, provider=args.provider, model=args.model
            )
            row.update(
                status="reviewed",
                ruling=result["ruling"],
                penalty_seconds=result["penalty_seconds"],
                review=result["model_review"],
            )
            if variant.evidence_mode == "telemetry_only" and result["penalty_seconds"] is not None:
                raise AssertionError("Provider promoted incomplete evidence")
        except Exception as error:
            row.update(status="failed", error_type=type(error).__name__)
        row["elapsed_seconds"] = round(time.monotonic() - started, 2)
        results.append(row)
    report = {"benchmark_type": "live provider integration, not independent accuracy", "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if any(row["status"] != "reviewed" for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
