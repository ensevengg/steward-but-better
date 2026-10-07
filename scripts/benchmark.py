"""Rule-application regression, explicitly not a blind perception benchmark."""

import argparse
import json
from pathlib import Path
from src.brain.contracts import CaseInput
from src.brain.judging import assess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("test-results/benchmark.json"))
    args = parser.parse_args()
    case = CaseInput.model_validate_json(
        (ROOT / "benchmarks/sao_paulo_2025.json").read_text(encoding="utf-8")
    )
    # Labels are evaluator-only; neither assessor nor provider sees this file.
    labels = json.loads((ROOT / "benchmarks/reference_outcomes.json").read_text(encoding="utf-8"))
    reference = labels[case.id]
    result = assess(case)
    rows = [
        {
            "case": "FIA document reconstruction",
            "expected": reference["penalty_seconds"],
            "actual": result["penalty_seconds"],
            "ruling": result["ruling"],
            "passed": result["penalty_seconds"] == reference["penalty_seconds"],
        }
    ]
    for observation in case.observations:
        partial = case.model_copy(
            update={"observations": [e for e in case.observations if e.id != observation.id]}
        )
        assessed = assess(partial)
        rows.append(
            {
                "case": f"Synthetic missing {observation.predicate}",
                "expected": None,
                "actual": assessed["penalty_seconds"],
                "ruling": assessed["ruling"],
                "passed": assessed["penalty_seconds"] is None,
            }
        )
    telemetry = assess(case.model_copy(update={"evidence_mode": "telemetry_only", "observations": []}))
    rows.append(
        {
            "case": "Retrospectively selected telemetry-only window",
            "expected": None,
            "actual": telemetry["penalty_seconds"],
            "ruling": telemetry["ruling"],
            "passed": telemetry["ruling"] == "INSUFFICIENT_EVIDENCE",
        }
    )
    report = {
        "benchmark_type": "document reconstruction plus synthetic regression controls",
        "independent_accuracy_claim": False,
        "automatic_detection_of_known_collision": False,
        "reference_document": reference["reference_document"],
        "results": rows,
        "passed": sum(row["passed"] for row in rows),
        "total": len(rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
