"""CLI for evidence-based assessment. Run as python -m src.brain.steward_agent."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
from .contracts import CaseInput
from .judging import assess
from .providers import optional_review


def run_steward_agent(incident: dict) -> dict:
    return optional_review(assess(CaseInput.model_validate(incident)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    args = parser.parse_args()
    print(json.dumps(run_steward_agent(json.loads(args.case.read_text(encoding="utf-8"))), indent=2))
