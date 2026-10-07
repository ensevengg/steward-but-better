import json
import httpx
import pytest

from src.brain.contracts import ModelReview
from src.brain.judging import assess
from src.brain.providers import optional_review, review_with_opencode


def review(result):
    return ModelReview(
        conditions=result["conditions"],
        rule_ids=[r["id"] for r in result["rules"]],
        summary="Evidence checked.",
        alternative_explanation="External cause considered.",
        missing_facts=[],
    ).model_dump()


def test_opencode_structured_contract_redaction_and_cleanup(reviewed_case):
    result = assess(reviewed_case)
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/session":
            assert json.loads(request.content)["permission"][0]["action"] == "deny"
            return httpx.Response(200, json={"id": "review1"})
        if request.url.path.endswith("/message"):
            body = json.loads(request.content)
            assert body["format"]["type"] == "json_schema"
            assert not any(body["tools"].values())
            evidence = json.loads(body["parts"][0]["text"])
            assert "penalty_seconds" not in evidence and "ruling" not in evidence
            assert "title" not in evidence and "source_ref" not in evidence["observations"][0]
            assert reviewed_case.driver not in body["parts"][0]["text"]
            return httpx.Response(200, json={"info": {"structured_output": review(result)}})
        return httpx.Response(200, json=True)

    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
        judged = review_with_opencode(
            result, base_url="http://test", provider="test", model="test", client=client
        )
    assert judged["penalty_seconds"] == 10
    assert judged["model_review"]["status"] == "reviewed"
    assert [(r.method, r.url.path) for r in requests[-2:]] == [
        ("POST", "/session/review1/abort"),
        ("DELETE", "/session/review1"),
    ]


@pytest.mark.parametrize(
    "response", [{"info": {"error": {"message": "failed"}}}, {"info": {"structured_output": {}}}, {}]
)
def test_malformed_model_output_never_becomes_a_penalty(reviewed_case, response):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"id": "r"} if request.url.path == "/session" else response)

    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises((ValueError, KeyError)):
            review_with_opencode(
                assess(reviewed_case), base_url="http://test", provider="test", model="test", client=client
            )
    assert calls[-1] == "/session/r"


@pytest.mark.parametrize("error", [httpx.ReadTimeout("timeout"), ValueError("invalid"), KeyError("output")])
def test_provider_failure_downgrades_to_review(monkeypatch, reviewed_case, error):
    monkeypatch.setenv("STEWARD_OPENCODE_URL", "http://test")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("src.brain.providers.review_with_opencode", fail)
    result = optional_review(assess(reviewed_case))
    assert result["ruling"] == "REVIEW_REQUIRED"
    assert result["penalty_seconds"] is None
    assert result["model_review"]["status"] == "unavailable"


def test_disabled_provider_does_not_make_network_call(reviewed_case):
    result = assess(reviewed_case)
    assert optional_review(result) is result
