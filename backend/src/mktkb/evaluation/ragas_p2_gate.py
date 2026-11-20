"""Offline-only composition of the frozen Ragas adapter and the existing P2Gate.

No provider client or funding path override lives here. Tests redirect P2Gate's
fixed paths to temporary synthetic files before opening the real gate.
"""
from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import ragas_adapter as ra
from . import p2_authorization as p2a
from .p2_authorization import P2Gate, P2GateError
from .p2_contracts import P2RunPlan
from ..rag.settlement_policy import UsageEvidence

SCHEMA_VERSION = 'p2-ragas-gate-result/v0.1'
_SEQUENCE = tuple(step for name in ('faithfulness', 'factual_correctness')
                  for step in ra.RAGAS_EXPECTED_METRIC_SEQUENCE[name])


class P2RagasJudgeBridge:
    """One distinct judge item and one versioned settlement per nested call."""

    execution_mode = 'synthetic'

    def __init__(self, *, run: ra.RagasRun, plan: P2RunPlan, gate: P2Gate,
                 judge: Any, item_ids_by_case: Mapping[str, Sequence[str]],
                 authorization: ra.RagasAuthorization | None = None) -> None:
        invalid = _validate(run, plan, gate, judge, authorization, item_ids_by_case)
        if invalid:
            raise ra.RagasAdapterError(invalid)
        self.judge_id = judge.judge_id
        self.judge_version = judge.judge_version
        self._judge = judge
        self._gate = gate
        self._plan = plan
        self._items = tuple((case.case_id, item_id, step)
            for case in run.cases if not case.refusal
            for item_id, step in zip(item_ids_by_case[case.case_id], _SEQUENCE, strict=True))
        self._cursor = 0
        self._busy = False
        self.calls: list[dict[str, Any]] = []
        self.stopped_reason: str | None = None

    def _stop(self, code: str) -> None:
        self.stopped_reason = self.stopped_reason or code
        self._gate.abort(code)

    async def complete(self, prompt: str, response_model: Any) -> Any:
        if self.stopped_reason is not None:
            raise ra.RagasJudgeError('gateway_stopped')
        if self._busy or self._cursor >= len(self._items):
            self._stop('nested_call_ceiling_exceeded')
            raise ra.RagasJudgeError('case_call_ceiling_exceeded')
        case_id, item_id, expected = self._items[self._cursor]
        if getattr(response_model, '__name__', None) != expected:
            self._stop('nested_sequence_invalid')
            raise ra.RagasJudgeError('framework_bypass_detected')
        self._busy = True
        ticket = None
        record = None
        try:
            ticket = self._gate.begin(item_id)
            record = dict(case_id=case_id, item_id=item_id, sequence=self._cursor + 1,
                response_model=expected, prompt_sha256=hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
                reservation_id=ticket.reservation_id, request_id=ticket.request_id,
                plan_id=ticket.plan_id, plan_sha256=ticket.plan_sha256, run_id=self._gate.run_id,
                model=ticket.model, judge_version=self.judge_version, cost_center=ticket.cost_center,
                reserved_cny=ticket.bound_cny, charged_cny=ticket.bound_cny,
                confirmed=False, sent=False, status='reserved')
            self.calls.append(record)
            self._gate.confirm_before_send(ticket)
            record['confirmed'] = True
            record['sent'] = True
            try:
                reply = await self._judge.complete(prompt, response_model, ticket=ticket)
            except Exception:
                self._gate.settle_failure(ticket, error_code='p2_ragas_judge_service_error')
                self._stop('judge_service_error')
                record['status'] = 'failed'
                raise ra.RagasJudgeError('judge_service_error') from None
            if not isinstance(getattr(reply, 'content', None), response_model):
                self._gate.settle_failure(ticket, error_code='p2_ragas_judge_output_invalid')
                self._stop('judge_output_invalid')
                record['status'] = 'failed'
                raise ra.RagasJudgeError('judge_output_invalid')
            evidence = getattr(reply, 'evidence', None)
            if not isinstance(evidence, UsageEvidence):
                self._gate.settle_failure(ticket, error_code='p2_ragas_usage_evidence_missing')
                self._stop('usage_evidence_missing')
                record['status'] = 'failed'
                raise ra.RagasJudgeError('judge_output_invalid')
            try:
                charge = self._gate.settle_success(ticket, evidence=evidence)
            except P2GateError:
                # settle_usage may already have appended a conservative unknown;
                # never append a second result or fabricate a release.
                self._stop('usage_settlement_refused')
                record['status'] = 'unknown'
                raise ra.RagasJudgeError('judge_output_invalid') from None
            record.update(status='succeeded', charged_cny=charge)
            self._cursor += 1
            return reply.content
        except P2GateError:
            if record is not None:
                record['status'] = 'refused_before_send'
            self._stop('p2_gate_refused')
            raise ra.RagasJudgeError('ledger_refused') from None
        except ra.RagasAdapterError:
            raise
        except Exception:
            if ticket is not None and record is not None:
                record['status'] = 'unknown'
            self._stop('wiring_internal_error')
            raise ra.RagasJudgeError('adapter_internal_error') from None
        finally:
            self._busy = False


def _validate(run: Any, plan: Any, gate: Any, judge: Any,
              authorization: Any, bindings: Any) -> str | None:
    invalid = ra._validate_run(run)
    if invalid:
        return invalid
    # A bridge must never infer case identity from prompt contents. This small
    # offline entry handles one existing case and its six explicit plan items.
    if len(run.cases) != 1:
        return 'p2_single_case_required'
    if gate is None:
        return 'p2_gate_missing'
    if not isinstance(gate, P2Gate) or not isinstance(plan, P2RunPlan):
        return 'p2_binding_invalid'
    if authorization is None:
        return 'authorization_missing'
    if not isinstance(authorization, ra.RagasAuthorization):
        return 'authorization_invalid_type'
    invalid = ra._validate_authorization(authorization)
    if invalid:
        return invalid
    invalid = ra._validate_judge(judge, authorization)
    if invalid:
        return invalid
    # Re-parse nested contracts too: dataclasses can be forged after construction.
    canonical = P2RunPlan.from_dict(plan.as_dict())
    auth = gate.authorization
    if (gate.run_id != run.run_id or authorization.run_id != run.run_id
            or auth.plan_id != run.plan_id or canonical.plan_id != run.plan_id
            or auth.plan_sha256 != run.plan_sha256 or canonical.plan_sha256 != run.plan_sha256
            or authorization.plan_id != run.plan_id or authorization.plan_sha256 != run.plan_sha256):
        return 'p2_binding_mismatch'
    ledger = Path(auth.ledger_path)
    # This entry point is deliberately unable to spend from the shared ledger.
    if (ledger.is_symlink() or not ledger.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
            or 'evidence' in {part.lower() for part in ledger.parts}):
        return 'p2_synthetic_ledger_required'
    # P2Gate has no public plan/ledger accessors. Read the actual owning objects
    # here, rather than trusting an authorization DTO beside a different ledger.
    actual_plan = P2RunPlan.from_dict(gate._plan.as_dict())
    book = gate._ledger
    if (actual_plan.plan_sha256 != canonical.plan_sha256
            or Path(book.ledger_path).resolve() != ledger.resolve()
            or ledger.resolve() != p2a.P2_LEDGER_PATH.resolve()
            or Path(book.budget_json_path).resolve() != p2a.P2_BUDGET_PATH.resolve()
            or book.run_id != run.run_id or book.stage != auth.stage
            or getattr(book._request_guard, '__self__', None) is not gate
            or getattr(book._post_reserve_guard, '__self__', None) is not gate):
        return 'p2_gate_binding_mismatch'
    if gate.stopped_reason is not None or gate.result().requests_reserved:
        return 'p2_gate_already_used'
    if not isinstance(bindings, Mapping) or set(bindings) != {c.case_id for c in run.cases}:
        return 'p2_item_binding_invalid'
    seen = set()
    for case in run.cases:
        ids = bindings[case.case_id]
        if isinstance(ids, (str, bytes)) or not isinstance(ids, (tuple, list)) or len(ids) != 6:
            return 'p2_item_binding_invalid'
        for item_id in ids:
            if item_id in seen:
                return 'p2_item_binding_invalid'
            seen.add(item_id)
            item = canonical.item(item_id)
            if (item.case_id != case.case_id or item.operation != 'judge'
                    or item.cost_center != 'judge' or item.requests != 1
                    or item.price_profile.model != getattr(judge, 'model', None)):
                return 'p2_item_binding_invalid'
    return None


def _result(status: str, reason: str | None, score: Any = None,
            bridge: P2RagasJudgeBridge | None = None) -> dict[str, Any]:
    calls = bridge.calls if bridge else []
    return dict(schema_version=SCHEMA_VERSION, status=status, reason_code=reason,
        score=score, calls=[dict(c) for c in calls], retry_count=0,
        auxiliary_only=True, quality_decision=None, production_ready=False,
        p2_cost=dict(currency='CNY', synthetic=True,
            reserved_cny=round(sum(c['reserved_cny'] for c in calls), 10),
            charged_cny=round(sum(c['charged_cny'] for c in calls), 10),
            requests_reserved=len(calls), requests_sent=sum(c['sent'] for c in calls)))


async def score_ragas_with_p2_gate(run: ra.RagasRun, *, plan: P2RunPlan, gate: P2Gate | None,
        judge: Any, authorization: ra.RagasAuthorization | None,
        item_ids_by_case: Mapping[str, Sequence[str]], enabled: bool = False,
        clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """Default-off synthetic wiring; does not open a gate or redirect its paths."""
    if enabled is not True:
        return _result('blocked', 'wiring_disabled')
    bridge = None
    try:
        invalid = _validate(run, plan, gate, judge, authorization, item_ids_by_case)
        if invalid:
            return _result('blocked', invalid)
        bridge = P2RagasJudgeBridge(run=run, plan=plan, gate=gate, judge=judge,
                                   item_ids_by_case=item_ids_by_case, authorization=authorization)
        result = await ra.score_ragas(run, judge=bridge, authorization=authorization, clock=clock)
        if result.status != 'scored' and bridge.calls:
            gate.abort('p2_ragas_incomplete')
        payload = result.to_dict()
        reason = bridge.stopped_reason or result.reason_code
        if bridge.stopped_reason:
            payload['reason_code'] = reason
            for case in payload['cases']:
                if case['status'] == 'unknown':
                    case['reason_code'] = reason
        return _result(result.status, reason, payload, bridge)
    except Exception:
        if bridge is not None and bridge.calls:
            bridge._stop('wiring_internal_error')
            return _result('unknown', 'wiring_internal_error', bridge=bridge)
        return _result('blocked', 'p2_binding_invalid')
