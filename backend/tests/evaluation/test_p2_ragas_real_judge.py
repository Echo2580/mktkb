"""Real judge entry with fixed-path temporary funding and a zero-network transport."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance.support.netguard import t09_network_guard
import test_p2_authorization as fixtures
from mktkb.evaluation import p2_authorization as p2a


pytestmark = pytest.mark.usefixtures("t09_network_guard")
SENTINEL = "public-fixture-sentinel-7ae1"
TOKENIZER = "b" * 64
TOKEN_TEMPLATE = "c" * 64


def test_real_judge_module_exists():
    assert importlib.util.find_spec("mktkb.evaluation.ragas_real_judge") is not None


def public_batch(cases=1):
    return {
        "schema_version": "t208-public-batch/v0.1",
        "mode": "real_judge",
        "run_id": "public-judge-test-01",
        "source": {
            "kind": "public_fixture",
            "run_id": "completed-public-run",
            "version": "public-run-v1",
            "sha256": "a" * 64,
        },
        "cases": [
            {"case_id": f"PUBLIC-{i}", "question": SENTINEL, "answer": "A public fact.",
             "contexts": ["A public fact."], "reference": "A public fact.", "refusal": False,
             "hard_failure": "public-disagreement" if i == 1 else None}
            for i in range(1, cases + 1)
        ],
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    pytest.importorskip("ragas")
    from mktkb.evaluation import ragas_real_judge as live

    ledger, budget, go = (tmp_path / name for name in ("ledger.jsonl", "budget.json", "go.json"))
    fixtures._write_ledger(ledger)
    fixtures._write_budget(budget)
    for name, path in (("P2_LEDGER_PATH", ledger), ("P2_BUDGET_PATH", budget), ("P2_GO_PATH", go)):
        monkeypatch.setattr(p2a, name, path)
    monkeypatch.setenv(fixtures.live_authorization.TOTAL_LIMIT_ENV, str(fixtures.TOTAL_LIMIT_CNY))
    monkeypatch.setenv("MKTKB_MODEL_API_KEY", "fixture-key-no-network")
    meter = SimpleNamespace(tokenizer_sha256=TOKENIZER, template_sha256=TOKEN_TEMPLATE,
                            prompt_token_upper_bound=lambda system, user: 1200)
    monkeypatch.setattr(live, "_load_judge_meter", lambda: meter)
    monkeypatch.setattr(live, "_utcnow", lambda: fixtures.NOW)
    return SimpleNamespace(live=live, ledger=ledger, go=go, meter=meter)


def freeze(env, batch):
    preview = env.live.preview_real_judge(batch)
    assert preview["status"] == "preview", preview
    plan = fixtures._plan(
        plan_id=preview["required_plan_id"],
        max_requests="unlimited",
        items=[fixtures._item(item["item_id"], "judge", item["case_id"], turn=item["sequence"])
               for item in preview["required_items"]],
    )
    fixtures._write_go(env.go, ledger_prefix=fixtures._prefix_sha(env.ledger),
                       plan=plan, ledger_path=env.ledger, scope={"max_requests": "unlimited"})
    return plan


def mock_provider(env, monkeypatch, *, fail_at=None, mode=None, order=None, input_tokens=1200, replies=None):
    calls = []
    responses = (
        {"statements": ["A public fact."]},
        {"statements": [{"statement": "A public fact.", "reason": "Supported.", "verdict": 1}]},
        {"claims": ["A public fact."]},
    )
    if replies is None:
        replies = [responses[index] for index in (0, 1, 2, 1, 2, 1)]

    async def handle(request):
        calls.append(request)
        if order is not None:
            order.append("post")
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-flash"
        assert payload["response_format"] == {"type": "json_object"}
        assert "JSON" in payload["messages"][0]["content"]
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["stream"] is False and payload["max_tokens"] == 800
        content = json.dumps(replies[(len(calls) - 1) % len(replies)])
        usage = {"prompt_tokens": input_tokens, "completion_tokens": 200, "total_tokens": input_tokens + 200,
                 "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": input_tokens,
                 "prompt_tokens_details": {"cached_tokens": 0},
                 "completion_tokens_details": {"reasoning_tokens": 0}}
        if len(calls) == fail_at:
            if mode == "timeout":
                raise httpx.ReadTimeout(SENTINEL)
            if mode == "429":
                return httpx.Response(429, content=SENTINEL.encode())
            if mode == "bad_json":
                content = "."
            if mode == "empty":
                content = " "
            if mode == "bad_schema":
                content = '{"unexpected":true}'
            if mode == "missing_usage":
                usage = None
            if mode == "bad_usage":
                usage["total_tokens"] = 1
        return httpx.Response(200, json={"id": f"public-mock-{len(calls)}", "model": "deepseek-flash",
            "choices": [{"finish_reason": "stop", "message": {"content": content}}], "usage": usage})

    monkeypatch.setattr(env.live, "_open_http_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False))
    return calls


def run(env, batch, plan, *, enabled=True):
    return asyncio.run(env.live.score_real_judge(batch, plan, enabled=enabled))


def events(env, kind):
    return [event for event in fixtures._events(env.ledger) if event.get("event") == kind]


def test_real_ragas_metrics_use_six_gated_posts(env, monkeypatch, t09_network_guard):
    batch = public_batch()
    plan = freeze(env, batch)
    order = []
    for name in ("begin", "confirm_before_send", "settle_success"):
        original = getattr(p2a.P2Gate, name)

        def spy(*args, _name=name, _original=original, **kwargs):
            result = _original(*args, **kwargs)
            order.append(_name)
            return result

        monkeypatch.setattr(p2a.P2Gate, name, spy)
    calls = mock_provider(env, monkeypatch, order=order)
    result = run(env, batch, plan)
    assert result["status"] == "scored", result
    assert result["cases"][0]["hard_failure"] == "public-disagreement"
    assert result["cases"][0]["faithfulness"] == result["cases"][0]["factual_correctness"] == 1
    assert order == ["begin", "confirm_before_send", "post", "settle_success"] * 6
    assert len(calls) == len(events(env, "reserved")) == len(events(env, "result")) == 6
    assert {call["reservation_id"] for call in result["calls"]} == {
        event["reservation_id"] for event in events(env, "result")
    }
    assert result["cost"]["charged_cny"] == pytest.approx(6 * 0.004)
    assert result["retry_count"] == result["embedding_calls"] == 0
    assert SENTINEL not in json.dumps(result)
    assert t09_network_guard.snapshot()["external"] == []


@pytest.mark.parametrize("mode", ["timeout", "429", "bad_json", "empty", "bad_schema", "missing_usage", "bad_usage"])
def test_first_failed_post_stops_batch_with_conservative_accounting(env, monkeypatch, mode):
    batch = public_batch(2)
    plan = freeze(env, batch)
    calls = mock_provider(env, monkeypatch, fail_at=2, mode=mode)
    result = run(env, batch, plan)
    assert result["status"] == "unknown", result
    assert [case["status"] for case in result["cases"]] == ["unknown", "unknown"]
    assert len(calls) == len(events(env, "reserved")) == len(events(env, "result")) == 2
    assert result["retry_count"] == 0
    assert result["cost"]["charged_cny"] == pytest.approx(0.004 + fixtures.CHAT_BOUND_CNY)
    assert SENTINEL not in json.dumps(result)


@pytest.mark.parametrize("change", ["disabled", "expired", "go_mismatch", "run_id", "source", "case_text", "settings", "engine"])
def test_unapproved_or_changed_scope_has_no_post_or_reservation(env, monkeypatch, change):
    batch = public_batch()
    plan = freeze(env, batch)
    calls = mock_provider(env, monkeypatch)
    if change in ("expired", "go_mismatch"):
        go = json.loads(env.go.read_text(encoding="utf-8"))
        if change == "expired":
            go["expires_utc"] = fixtures.NOW.isoformat()
        else:
            go["scope"]["plan_sha256"] = "f" * 64
        env.go.write_text(json.dumps(go), encoding="utf-8")
    if change == "run_id":
        batch["run_id"] = "public-judge-test-02"
    if change == "source":
        batch["source"]["kind"] = "holdout"
    if change == "case_text":
        batch["cases"][0]["answer"] = "Changed after scope approval."
    if change == "settings":
        env.meter.tokenizer_sha256 = "d" * 64
    if change == "engine":
        monkeypatch.setattr(env.live, "_engine_code_digest", lambda: "e" * 64)
    result = run(env, batch, plan, enabled=change != "disabled")
    assert result["status"] == "blocked", result
    assert calls == [] and events(env, "reserved") == []


def test_expiry_after_reserve_prevents_post(env, monkeypatch):
    batch = public_batch()
    plan = freeze(env, batch)
    calls = mock_provider(env, monkeypatch)
    original = p2a.P2Gate.begin

    def begin(*args, **kwargs):
        ticket = original(*args, **kwargs)
        go = json.loads(env.go.read_text(encoding="utf-8"))
        go["expires_utc"] = fixtures.NOW.isoformat()
        env.go.write_text(json.dumps(go), encoding="utf-8")
        return ticket

    monkeypatch.setattr(p2a.P2Gate, "begin", begin)
    result = run(env, batch, plan)
    assert result["status"] == "unknown", result
    assert calls == [] and len(events(env, "reserved")) == len(events(env, "result")) == 1
    assert result["calls"][0]["sent"] is False
    assert result["cost"]["charged_cny"] == pytest.approx(fixtures.CHAT_BOUND_CNY)


@pytest.mark.parametrize("change", ["empty", "over_limit", "duplicate", "provenance"])
def test_preview_rejects_invalid_batches(env, change):
    batch = public_batch(0 if change == "empty" else 6 if change == "over_limit" else 2)
    if change == "duplicate":
        batch["cases"][1]["case_id"] = batch["cases"][0]["case_id"]
    if change == "provenance":
        del batch["source"]["sha256"]
    assert env.live.preview_real_judge(batch)["status"] == "blocked"


def test_preview_and_preflight_never_open_transport_or_reserve(env, monkeypatch):
    batch = public_batch()
    plan = freeze(env, batch)
    monkeypatch.setattr(env.live, "_open_http_client", lambda: pytest.fail("preflight opened transport"))
    before = env.ledger.read_bytes()
    result = env.live.preflight_real_judge(batch, plan)
    assert result["status"] == "preflight", result
    assert env.ledger.read_bytes() == before
    env.go.unlink()
    assert run(env, batch, plan)["status"] == "blocked"
    assert env.ledger.read_bytes() == before


def test_persistent_quota_stops_replay(env, monkeypatch):
    batch = public_batch()
    plan = freeze(env, batch)
    calls = mock_provider(env, monkeypatch)
    assert run(env, batch, plan)["status"] == "scored"
    repeated = run(env, batch, plan)
    assert repeated["status"] == "unknown"
    assert repeated["reason_code"] == "attempt_quota_exhausted"
    assert len(calls) == len(events(env, "reserved")) == 6


def test_prompt_bound_rejection_precedes_first_reservation(env, monkeypatch):
    batch = public_batch()
    plan = freeze(env, batch)
    env.meter.prompt_token_upper_bound = lambda *_: 6145
    calls = mock_provider(env, monkeypatch)
    result = run(env, batch, plan)
    assert result["reason_code"] == "judge_prompt_cap_exceeded"
    assert calls == [] and events(env, "reserved") == []


def test_billed_prompt_must_fit_measured_bound(env, monkeypatch):
    batch = public_batch()
    plan = freeze(env, batch)
    calls = mock_provider(env, monkeypatch, input_tokens=1201)
    result = run(env, batch, plan)
    assert result["reason_code"] == "judge_usage_bound_anomaly"
    assert len(calls) == len(events(env, "reserved")) == len(events(env, "result")) == 1


def test_five_case_batch_leaves_refusal_unscored_without_stopping(env, monkeypatch):
    batch = public_batch(5)
    batch["cases"][1].update(refusal=True, contexts=[])
    plan = freeze(env, batch)
    calls = mock_provider(env, monkeypatch)
    result = run(env, batch, plan)
    assert result["status"] == "scored", result["reason_code"]
    assert result["complete"] is True
    assert result["cases"][1]["status"] == "unknown"
    assert result["cases"][1]["reason_code"] == "refusal_not_applicable"
    assert result["cases"][1]["judge_calls"] == 0
    assert len(calls) == len(events(env, "reserved")) == len(events(env, "result")) == 24


def test_official_meter_with_public_calibration_batch(env, monkeypatch, t09_network_guard):
    if not os.environ.get("MKTKB_T208_ARTIFACT_DIR"):
        pytest.skip("requires the isolated pinned 1017 artifact and metering dependencies")
    root = Path(__file__).resolve().parents[3]
    fixture = root / "fixtures/evaluation/t208-public-calibration-v1.json"
    if not fixture.is_file():
        pytest.skip("public calibration fixture is supplied separately by the project manager")
    monkeypatch.setattr(env.live, "_load_judge_meter", env.live.load_judge_meter)
    batch = json.loads(fixture.read_text(encoding="utf-8"))
    plan = freeze(env, batch)
    calls = mock_provider(env, monkeypatch, input_tokens=125)
    result = run(env, batch, plan)
    assert result["status"] == "scored", [(score["case_id"], score["reason_code"]) for score in result["cases"]]
    assert len(calls) == 24
    assert max(row["prompt_token_upper_bound"] for row in result["calls"]) <= 6144
    assert t09_network_guard.snapshot()["external"] == []


def nli_verdicts(statements):
    return {"statements": [{"statement": statement, "reason": "Supported.", "verdict": 1}
                           for statement in statements]}


@pytest.mark.parametrize("change,stops_after", [
    ("forward_drops_duplicate", 4), ("reverse_reuses_forward", 6), ("reverse_extra", 6),
    ("blank_claim", 3), ("valid_reordering", 6),
])
def test_factual_nli_corresponds_to_adjacent_claims(env, monkeypatch, change, stops_after):
    batch = public_batch()
    plan = freeze(env, batch)
    forward = [f"{SENTINEL}-forward", "A second claim.", f"{SENTINEL}-forward"]
    reverse = [f"{SENTINEL}-reverse", "A reverse claim."]
    replies = [{"statements": ["A statement."]}, nli_verdicts(["A statement."]),
               {"claims": forward}, nli_verdicts([forward[1], forward[0], forward[2]]),
               {"claims": reverse}, nli_verdicts(reversed(reverse))]
    if change == "forward_drops_duplicate":
        replies[3] = nli_verdicts(forward[:2])
    elif change == "reverse_reuses_forward":
        replies[5] = nli_verdicts([forward[0], reverse[1]])
    elif change == "reverse_extra":
        replies[5] = nli_verdicts(reverse + reverse[:1])
    elif change == "blank_claim":
        replies[2] = {"claims": [" \t "]}
        replies[3] = nli_verdicts([" \t "])

    calls = mock_provider(env, monkeypatch, replies=replies)
    result = run(env, batch, plan)
    assert len(calls) == len(events(env, "reserved")) == len(events(env, "result")) == stops_after
    if change == "valid_reordering":
        assert result["status"] == "scored"
        assert result["cases"][0]["factual_correctness"] == 1.0
    else:
        assert result["status"] == "unknown"
        assert result["cases"][0]["factual_correctness"] is None
        assert result["calls"][-1]["status"] == "unknown" and result["retry_count"] == 0
        assert result["cost"]["charged_cny"] == pytest.approx((stops_after - 1) * 0.004 + fixtures.CHAT_BOUND_CNY)
    assert SENTINEL not in json.dumps(result)
