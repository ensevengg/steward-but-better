import json
from pathlib import Path
import pytest
from src.brain.contracts import CaseInput

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def reviewed_case():
    return CaseInput.model_validate(
        json.loads((ROOT / "benchmarks/sao_paulo_2025.json").read_text(encoding="utf-8"))
    )


@pytest.fixture(autouse=True)
def no_live_provider(monkeypatch):
    monkeypatch.delenv("STEWARD_OPENCODE_URL", raising=False)
