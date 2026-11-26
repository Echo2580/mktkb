"""C1-P2 独立验收：fail-closed 静态 + 运行时探针。

只使用合成 envelope（复用测试模块的 build_evidence），不读真实 H2 数据。
每个探针给出 expected=not proven 或 expected=proven，任何偏差都记为 fail。
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

REPO = Path(r"D:\GPT项目\市场部AI知识库")
BACKEND = REPO / "backend"
TEST_FILE = BACKEND / "tests/evaluation/test_p2_empty_scope_proof.py"
MODULE = BACKEND / "src/mktkb/evaluation/p2_empty_scope_proof.py"
OUT = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/independent/12-failclosed.json"


def load_test_module():
    sys.path.insert(0, str(BACKEND / "src"))
    sys.path.insert(0, str(BACKEND / "tests"))
    spec = importlib.util.spec_from_file_location("c1p2_test_mod_fc", TEST_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def find_events(envelope: Mapping[str, Any], kind: str) -> list[Mapping[str, Any]]:
    return [
        row
        for row in envelope["capture"]["events"]
        if isinstance(row, Mapping) and str(row.get("kind")) == kind
    ]


def main() -> int:
    mod = load_test_module()
    prove = mod.prove_empty_use_scope
    build = mod.build_evidence
    no_retrieval_snapshot = mod._no_retrieval_snapshot

    probes: list[dict[str, Any]] = []

    def record(name: str, envelope: Any, expected_proven: bool, note: str = "") -> None:
        result = prove(envelope)
        probes.append(
            {
                "name": name,
                "expected_proven": expected_proven,
                "actual_proven": result.proven,
                "pass": result.proven is expected_proven,
                "code": result.code,
                "detail": result.detail,
                "shape": result.shape,
                "usage_layers": list(result.usage_layers),
                "candidate_sources": list(result.candidate_sources),
                "note": note,
            }
        )

    # A. 非 mapping / 空输入
    for value in (None, [], {}, 0, "x", object(), True, 1.5):
        record(f"input:{type(value).__name__}:{value!r}"[:80], value, False)

    # B. 基准：默认 envelope 必须 proven（否则后续探针无意义）
    base = build()
    record("baseline_default_proven", base, True)

    # C. 11 个扩展例：逐个 usage 容器删除 → 必须 fail-closed
    extension_cases = [c for c in mod._corpus() if c.divergence and not c.stricter]
    removal_targets: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
        ("answer_result.source_ids", lambda e: find_events(e, "answer_result")[0]["payload"].pop("source_ids")),
        ("commit_observed.source_ids", lambda e: find_events(e, "commit_observed")[0]["payload"].pop("source_ids")),
        ("projection.message_sources", lambda e: e["db_projection"].pop("message_sources")),
        ("projection.units", lambda e: e["db_projection"].pop("units")),
        ("projection.unresolved_unit_ids", lambda e: e["db_projection"].pop("unresolved_unit_ids")),
        ("model_output.source_ids", lambda e: find_events(e, "model_output")[0]["payload"].pop("source_ids")),
        ("model_input.evidence", lambda e: find_events(e, "model_input")[0]["payload"].pop("evidence")),
        ("direct_rag.facts", lambda e: find_events(e, "direct_rag_answer")[0]["payload"].pop("facts")),
        ("direct_rag.fact_count", lambda e: find_events(e, "direct_rag_answer")[0]["payload"].pop("fact_count")),
        ("direct_rag.cited_unit_ids", lambda e: find_events(e, "direct_rag_answer")[0]["payload"].pop("cited_unit_ids")),
    ]
    for case in extension_cases:
        for label, mutate in removal_targets:
            env = copy.deepcopy(case.evidence)
            try:
                mutate(env)
            except (IndexError, KeyError, TypeError):
                continue
            record(f"remove:{case.name}:{label}", env, False, "usage 容器缺失必须 fail-closed")

    # D. 向每个适用的 usage 容器注入一个使用 id → 必须不 proven
    inject_targets: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
        ("answer_result.source_ids", lambda e: find_events(e, "answer_result")[0]["payload"].__setitem__("source_ids", ["u-inject"])),
        ("commit_observed.source_ids", lambda e: find_events(e, "commit_observed")[0]["payload"].__setitem__("source_ids", ["u-inject"])),
        ("projection.message_sources", lambda e: e["db_projection"].__setitem__("message_sources", [{"message_id": "msg-assistant", "source_id": "u-inject", "document_id": "doc-1", "version_id": "ver-1"}])),
        ("projection.unit_unattributable", lambda e: e["db_projection"].__setitem__("units", [{"unit_id": "u-inject"}])),
        ("projection.unresolved_unattributable", lambda e: e["db_projection"].__setitem__("unresolved_unit_ids", [{"unit_id": "u-inject", "reason": "unit_not_found"}])),
    ]
    for case in extension_cases:
        for label, mutate in inject_targets:
            env = copy.deepcopy(case.evidence)
            try:
                mutate(env)
            except (IndexError, KeyError, TypeError):
                continue
            record(f"inject:{case.name}:{label}", env, False, "使用层非空必须不 proven")
    # 注入 model evidence / model output / direct rag / entity inheritance（需要新增事件）
    for case in extension_cases:
        env = copy.deepcopy(case.evidence)
        env["capture"]["events"].append(
            {
                "seq": 900,
                "kind": "entity_inheritance",
                "payload": {
                    "request_id": "req-1",
                    "entity_type": "store",
                    "entity_key": "store-1",
                    "source_message_id": None,
                    "source_unit_id": "u-inject",
                    "source": "synthetic",
                },
            }
        )
        record(f"inject:{case.name}:entity_inheritance", env, False, "实体继承按使用处理（更严）")
        env = copy.deepcopy(case.evidence)
        env["db_projection"]["message_sources"] = [
            {"message_id": "msg-assistant", "source_id": "u-inject", "document_id": "doc-1", "version_id": "ver-1"}
        ]
        record(f"inject:{case.name}:message_sources", env, False, "DB 结果消息来源即使用")

    # E. 坏类型
    bad_type_probes: list[tuple[str, Callable[[dict[str, Any]], None]]] = []
    def set_answer_ids(value: Any) -> Callable[[dict[str, Any]], None]:
        return lambda e: find_events(e, "answer_result")[0]["payload"].__setitem__("source_ids", value)

    for value in ("u1", None, 1, True, {"u": 1}, ["", "  "], [1], [None]):
        bad_type_probes.append((f"answer_result.source_ids={value!r}"[:70], set_answer_ids(value)))

    def set_commit_ids(value: Any) -> Callable[[dict[str, Any]], None]:
        return lambda e: find_events(e, "commit_observed")[0]["payload"].__setitem__("source_ids", value)

    for value in (None, "u1", 0, [""]):
        bad_type_probes.append((f"commit_observed.source_ids={value!r}"[:70], set_commit_ids(value)))

    def set_msg_src(value: Any) -> Callable[[dict[str, Any]], None]:
        return lambda e: e["db_projection"].__setitem__("message_sources", value)

    for value in (None, "u1", {}, [{"source_id": ""}], [{"source_id": 1}], ["u1"]):
        bad_type_probes.append((f"projection.message_sources={value!r}"[:70], set_msg_src(value)))

    def set_units(value: Any) -> Callable[[dict[str, Any]], None]:
        return lambda e: e["db_projection"].__setitem__("units", value)

    for value in (None, "u1", {}, [None], [{"unit_id": ""}], [{"unit_id": 1}]):
        bad_type_probes.append((f"projection.units={value!r}"[:70], set_units(value)))

    def set_unresolved(value: Any) -> Callable[[dict[str, Any]], None]:
        return lambda e: e["db_projection"].__setitem__("unresolved_unit_ids", value)

    for value in (None, "u1", {}, [None], [{"unit_id": ""}]):
        bad_type_probes.append((f"projection.unresolved={value!r}"[:70], set_unresolved(value)))

    def set_retrieval_ids(value: Any) -> Callable[[dict[str, Any]], None]:
        def mutate(e: dict[str, Any]) -> None:
            rows = find_events(e, "retrieval_observed")
            if not rows:
                e["capture"]["events"].append(
                    {"seq": 901, "kind": "retrieval_observed", "payload": {
                        "request_id": "req-1", "scope": "legacy_retrieve_initial", "unit_ids": value,
                        "candidate": False, "truncated": False, "empty": not value}}
                )
            else:
                rows[0]["payload"]["unit_ids"] = value
        return mutate

    for value in (None, "u1", 1, [1], [None], [""]):
        bad_type_probes.append((f"retrieval.unit_ids={value!r}"[:70], set_retrieval_ids(value)))

    def set_qs_state(value: Any) -> Callable[[dict[str, Any]], None]:
        def mutate(e: dict[str, Any]) -> None:
            e["capture"]["events"].append(
                {"seq": 902, "kind": "query_state_observed", "payload": {
                    "request_id": "req-1", "user_id": "user-1", "conversation_id": "conv-1",
                    "stored_user_id": "user-1", "stored_conversation_id": "conv-1",
                    "row_present": True, "state_keys": ["candidates"], "state_json": value,
                    "pending_slot": None, "last_kind": None, "turn": 0}}
            )
        return mutate

    for value in (None, [], "x", 1, {"candidates": "u1"}, {"candidates": {}}, {"candidates": [1]}):
        bad_type_probes.append((f"query_state.state_json={value!r}"[:70], set_qs_state(value)))

    def set_qs_row_present(value: Any) -> Callable[[dict[str, Any]], None]:
        def mutate(e: dict[str, Any]) -> None:
            e["capture"]["events"].append(
                {"seq": 903, "kind": "query_state_observed", "payload": {
                    "request_id": "req-1", "user_id": "user-1", "conversation_id": "conv-1",
                    "stored_user_id": "user-1", "stored_conversation_id": "conv-1",
                    "row_present": value, "state_keys": [], "state_json": {},
                    "pending_slot": None, "last_kind": None, "turn": 0}}
            )
        return mutate

    for value in (None, 1, "true", 0):
        bad_type_probes.append((f"query_state.row_present={value!r}", set_qs_row_present(value)))

    def set_marker(value: Any) -> Callable[[dict[str, Any]], None]:
        return lambda e: e.__setitem__("runtime_snapshot", value)

    for value in (
        None,
        {},
        {"schema_version": "p2-runtime-snapshot/v0.1"},
        {"schema_version": "p2-runtime-snapshot/v0.1", "retrieval_use": {}},
        {"schema_version": "p2-runtime-snapshot/v9", "retrieval_use": no_retrieval_snapshot()["retrieval_use"]},
        {"schema_version": "p2-runtime-snapshot/v0.1", "retrieval_use": {**no_retrieval_snapshot()["retrieval_use"], "availability": "partial"}},
        {"schema_version": "p2-runtime-snapshot/v0.1", "retrieval_use": {**no_retrieval_snapshot()["retrieval_use"], "candidates": ["u1"]}},
        {"schema_version": "p2-runtime-snapshot/v0.1", "retrieval_use": {**no_retrieval_snapshot()["retrieval_use"], "reason": "x"}},
    ):
        bad_type_probes.append((f"marker={str(value)[:50]}", set_marker(value)))

    bad_type_probes.extend(
        [
            ("completeness=missing", lambda e: e.pop("completeness")),
            ("completeness=[]", lambda e: e.__setitem__("completeness", [])),
            ("completeness.status=incomplete", lambda e: e.__setitem__("completeness", {"status": "incomplete"})),
            ("capture.events=missing", lambda e: e["capture"].pop("events")),
            ("capture.events={}", lambda e: e["capture"].__setitem__("events", {})),
            ("capture.events=[None]", lambda e: e["capture"].__setitem__("events", [None])),
            ("capture.events=[{}]", lambda e: e["capture"].__setitem__("events", [{}])),
            ("capture.events=['x']", lambda e: e["capture"].__setitem__("events", ["x"])),
            ("capture.errors=missing", lambda e: e["capture"].pop("errors")),
            ("capture.errors=nonempty", lambda e: e["capture"].__setitem__("errors", [{"code": "x"}])),
            ("projection.query_states=missing", lambda e: e["db_projection"].pop("query_states")),
            ("projection.query_states={}", lambda e: e["db_projection"].__setitem__("query_states", {})),
            ("projection.query_states=[None]", lambda e: e["db_projection"].__setitem__("query_states", [None])),
            (
                "projection.query_states.state_json=[]",
                lambda e: e["db_projection"].__setitem__(
                    "query_states",
                    [{"stored_user_id": "user-1", "stored_conversation_id": "conv-1", "state_json": [], "keys": []}],
                ),
            ),
            ("projection.query_states_available=1", lambda e: e["db_projection"].__setitem__("query_states_available", 1)),
            ("projection.query_states_available=False", lambda e: e["db_projection"].__setitem__("query_states_available", False)),
            ("projection.truncations=nonempty", lambda e: e["db_projection"].__setitem__("truncations", ["units_limit"])),
            ("projection.errors=nonempty", lambda e: e["db_projection"].__setitem__("errors", ["x"])),
            ("plan.path=other", lambda e: find_events(e, "plan_observed")[0]["payload"].__setitem__("path", "other")),
            ("plan.path=missing", lambda e: find_events(e, "plan_observed")[0]["payload"].pop("path")),
            ("unknown.envelope", lambda e: e.__setitem__("extra", 1)),
            ("unknown.capture", lambda e: e["capture"].__setitem__("extra", 1)),
            ("unknown.turn", lambda e: e["turn"].__setitem__("extra", 1)),
            ("unknown.event", lambda e: e["capture"]["events"][0].__setitem__("extra", 1)),
            ("unknown.event.payload", lambda e: e["capture"]["events"][0]["payload"].__setitem__("extra", 1)),
            ("unknown.projection", lambda e: e["db_projection"].__setitem__("extra", 1)),
            ("unknown.projection.row", lambda e: e["db_projection"]["conversation"].__setitem__("extra", 1)),
            ("event.kind=unknown", lambda e: e["capture"]["events"][0].__setitem__("kind", "unknown_kind")),
            ("event.payload=missing", lambda e: e["capture"]["events"][0].pop("payload")),
            ("event.payload=[]", lambda e: e["capture"]["events"][0].__setitem__("payload", [])),
            ("required_event.missing", lambda e: e["capture"].__setitem__("events", [r for r in e["capture"]["events"] if r["kind"] != "commit_observed"])),
            ("required_event.duplicate", lambda e: e["capture"]["events"].append(copy.deepcopy(find_events(e, "answer_result")[0]))),
            ("capture_error.event", lambda e: e["capture"]["events"].append({"seq": 904, "kind": "capture_error", "payload": {"stage": "capture", "code": "x", "request_id": "req-1", "detail": "y"}})),
            ("template.mismatch", lambda e: find_events(e, "commit_observed")[0]["payload"].__setitem__("text", "任意非模板文本")),
            ("answer/commit.text.mismatch", lambda e: find_events(e, "commit_observed")[0]["payload"].__setitem__("text", "任意不一致文本")),
            ("answer/commit.kind.mismatch", lambda e: find_events(e, "commit_observed")[0]["payload"].__setitem__("kind", "no_answer")),
            ("claim.conversation.mismatch", lambda e: find_events(e, "claim_observed")[0]["payload"].__setitem__("conversation_id", "conv-2")),
            ("claim.request.mismatch", lambda e: find_events(e, "claim_observed")[0]["payload"].__setitem__("request_id", "req-2")),
            ("request.result_message.mismatch", lambda e: e["db_projection"]["request"].__setitem__("result_message_id", "msg-other")),
        ]
    )
    for label, mutate in bad_type_probes:
        env = copy.deepcopy(base)
        try:
            mutate(env)
        except (IndexError, KeyError, TypeError):
            continue
        record(f"badtype:{label}", env, False, "坏类型/缺字段/未知键必须 fail-closed")

    # F. query_state 语义探针（非差分，检查 fail-closed）
    env = copy.deepcopy(base)
    env["db_projection"]["query_states"] = [{"stored_user_id": "user-1", "stored_conversation_id": "conv-1", "state_json": {"candidates": []}, "keys": ["candidates"]}]
    record("qs.projection.empty_candidates", env, True, "显式空候选是合法空值")
    env = copy.deepcopy(base)
    env["db_projection"]["query_states"] = [{"stored_user_id": "user-1", "stored_conversation_id": "conv-1"}]
    record("qs.projection.state_json_missing", env, False, "state_json 缺失必须 fail-closed")
    env = copy.deepcopy(base)
    env["db_projection"]["query_states"] = [{"stored_user_id": "user-1", "stored_conversation_id": "conv-1", "state_json": {}, "keys": []}]
    record("qs.projection.empty_state", env, True, "显式空状态 {} 合法")
    env = copy.deepcopy(base)
    env["db_projection"]["query_states"] = [{"stored_user_id": "user-1", "stored_conversation_id": "conv-1", "state_json": {"candidates": ["u-prior"]}, "keys": ["candidates"]}]
    record("qs.projection.candidates_unused", env, True, "候选层非空、使用层空 → 本实现扩展 proven")
    env = copy.deepcopy(base)
    env["db_projection"]["query_states"] = [{"stored_user_id": "user-1", "stored_conversation_id": "conv-1", "state_json": {"candidates": [], "used_sources": ["u-hidden"]}, "keys": ["candidates", "used_sources"]}]
    record("qs.projection.unknown_key_with_source", env, True, "已知缺口：state_json 内部未知键不 fail-closed（冻结原语同）")
    env = copy.deepcopy(base)
    env["capture"]["events"].append({"seq": 905, "kind": "query_state_observed", "payload": {"request_id": "req-1", "user_id": "user-1", "conversation_id": "conv-1", "stored_user_id": "user-1", "stored_conversation_id": "conv-1", "row_present": False, "state_keys": [], "state_json": {}, "pending_slot": None, "last_kind": None, "turn": 0}})
    record("qs.event.empty_state_row_absent", env, True, "显式空 {} + row_present=False 是合法无行")
    env = copy.deepcopy(base)
    env["capture"]["events"].append({"seq": 906, "kind": "query_state_observed", "payload": {"request_id": "req-1", "user_id": "user-1", "conversation_id": "conv-1", "stored_user_id": "user-1", "stored_conversation_id": "conv-1", "row_present": False, "state_keys": ["candidates"], "state_json": {"candidates": []}, "pending_slot": None, "last_kind": None, "turn": 0}})
    record("qs.event.empty_candidates_row_absent", env, False, "行不存在却带非空状态 → 矛盾 fail-closed（冻结原语同）")

    # G. 无检索语义
    env = build(retrieval_present=False)
    record("noretr.no_marker", env, False, "无检索事件且无正标记 → fail-closed")
    env = build(retrieval_present=False, runtime_snapshot=no_retrieval_snapshot())
    record("noretr.marker_ok", env, True, "v0.3 正标记 + 使用层空 → 本实现扩展 proven")
    env = build(retrieval_present=False, runtime_snapshot=no_retrieval_snapshot(), final_source_ids=("u1",))
    record("noretr.marker_ok_but_usage", env, False, "正标记不能覆盖非空使用层")
    good_usage = no_retrieval_snapshot()["retrieval_use"]
    for label, usage in (
        ("schema_v9", None),
        ("availability_partial", {**good_usage, "availability": "partial"}),
        ("reason_nonnull", {**good_usage, "reason": "x"}),
        ("candidates_nonempty", {**good_usage, "candidates": ["u1"]}),
        ("candidate_observed", {**good_usage, "candidate_observation": {"availability": "observed", "reason": None}}),
        ("candidate_reason_other", {**good_usage, "candidate_observation": {"availability": "not_observed", "reason": "replay"}}),
    ):
        snapshot = copy.deepcopy(no_retrieval_snapshot())
        if usage is None:
            snapshot["schema_version"] = "p2-runtime-snapshot/v9"
        else:
            snapshot["retrieval_use"] = usage
        record(f"noretr.marker_{label}", build(retrieval_present=False, runtime_snapshot=snapshot), False, "坏正标记必须 fail-closed")
    env = build(retrieval_present=False, runtime_snapshot=no_retrieval_snapshot())
    env["capture"]["events"].append({"seq": 907, "kind": "model_input", "payload": {"request_id": "req-1", "purpose": "answer", "question": "q", "context_questions": [], "context_entities": {}, "evidence": [{"source_id": "u1", "text": "t", "fields": {}}]}})
    env["capture"]["events"].append({"seq": 908, "kind": "model_output", "payload": {"request_id": "req-1", "purpose": "answer", "status": "ok", "text": None, "source_ids": [], "query_terms": [], "provider_request_id": None, "usage": None, "error_code": None, "retryable": False}})
    record("noretr.marker_with_model_usage", env, False, "有模型使用 → 不 proven")

    # H. 检索候选语义
    env = build(retrieval_unit_ids=("u1",))
    record("retr.candidates_unused", env, True, "候选非空、使用层空 → 扩展 proven")
    env = build(retrieval_unit_ids=("u1",), projection_units=("u1",))
    record("retr.candidates_unused_projected", env, True, "候选投影行可归因候选层")
    env = build(retrieval_unit_ids=("u1",), projection_units=("u2",))
    record("retr.candidate_unattributable_row", env, False, "投影行不可归因 → fail-closed")
    env = build(retrieval_unit_ids=("u1",), projection_unresolved=("u2",))
    record("retr.candidate_unattributable_unresolved", env, False, "未解析行不可归因 → fail-closed")
    env = build(retrieval_unit_ids=("u1",), retrieval_candidate=True)
    record("retr.candidate_flag_true", env, True, "candidate=True 仍是候选层")

    # I. AST 静态检查
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    proven_true_nodes = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg == "proven" and isinstance(node.value, ast.Constant) and node.value.value is True
    ]
    proven_false_nodes = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg == "proven" and isinstance(node.value, ast.Constant) and node.value.value is False
    ]
    returns_true = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and node.value.value is True
    ]
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    ast_summary = {
        "proven_true_keyword_lines": proven_true_nodes,
        "proven_false_keyword_lines": proven_false_nodes,
        "return_true_lines": returns_true,
        "imports": imports,
        "imports_forbidden": [
            name for name in imports
            if any(x in name for x in ("p2_hard_evidence", "p2_evidence_capture", "p2_evidence_io", "socket", "httpx", "requests", "urllib", "http"))
        ],
        "single_proven_true": len(proven_true_nodes) == 1,
        "no_bare_return_true": not returns_true,
        "no_network_imports": not any(
            name in {"socket", "httpx", "requests", "urllib", "urllib.request", "http", "http.client"}
            for name in imports
        ),
    }

    failed = [p for p in probes if not p["pass"]]
    payload = {
        "schema_version": "c1p2-independent-failclosed/v0.1",
        "probe_count": len(probes),
        "failed_count": len(failed),
        "failed": failed,
        "ast": ast_summary,
        "probes": probes,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "probe_count": len(probes),
        "failed_count": len(failed),
        "failed": [{k: p[k] for k in ("name", "expected_proven", "actual_proven", "detail")} for p in failed],
        "ast": ast_summary,
    }, ensure_ascii=False, indent=1))
    return 0 if not failed and ast_summary["single_proven_true"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
