"""NCU manifest 回源校验器：形状 + 内容级回源（trace DB / run cases / 冻结题集 / 证据路径 SHA）。

用法：
    python -X utf8 scripts/verify_manifest.py <manifest.json>
退出码：0 = 通过；1 = 拒绝（输出 {"ok": false, "errors": [...]}，错误带固定原因码）。

回源规则（v0.2，返工 R1-1）：
- 样本数 N/C/U = 8/6/10、case_id 唯一；
- `question_sha256` 必须同时命中：冻结题集 sha256(question)、该 run `cases.jsonl` 同题哈希、
  该 `trace_id` 在 run trace DB 内的 `question_hash`；
- `evidence_paths` 每个路径必须存在，`evidence_sha256` 记录值必须与真实文件一致；
- `trace_id` 必须属于该 run 的 trace DB，且 trace 的 run/版本绑定与本 run 一致
  （trace_id 互换会因 question_hash 不符被拒）；
- R/L 类型不得混用；ADOPTED 不得带失败门禁；答案类必须有引用证据。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

PLANNED = {"N": 8, "C": 6, "U": 10}
HERE = Path(__file__).resolve()
DEFAULT_ROOT = HERE.parents[6]
ROOT = Path(os.environ.get("NCU_REPO_ROOT", str(DEFAULT_ROOT)))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else (ROOT / p)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate(m: dict) -> list[str]:
    errs: list[str] = []
    cases = m.get("cases") or []
    runs = m.get("runs") or {}
    by_run_id = {r["run_id"]: r for r in runs.values()}

    # 1) 样本数
    for g, n in PLANNED.items():
        got = [c for c in cases if c.get("group") == g]
        if len(got) != n:
            errs.append(f"SAMPLE_INSUFFICIENT:{g}:expected={n}:actual={len(got)}")

    # 2) 重复选题
    seen = set()
    for c in cases:
        cid = c.get("case_id")
        if cid in seen:
            errs.append(f"DUPLICATE_CASE:{cid}")
        seen.add(cid)

    # 缓存：run cases / frozen cases / trace DB
    run_cases_cache: dict[str, dict[str, dict]] = {}
    frozen_cache: dict[str, dict[str, dict]] = {}
    trace_cache: dict[str, dict[str, dict]] = {}

    for c in cases:
        cid = c.get("case_id")
        basis = c.get("basis")
        paths = c.get("evidence_paths") or {}
        shas = c.get("evidence_sha256") or {}

        # 证据路径存在性 + SHA（对所有 case 生效，包括 B2 类）
        for name, raw in paths.items():
            p = resolve(str(raw))
            if not p.exists():
                errs.append(f"EVIDENCE_PATH_MISSING:{cid}:{name}")
                continue
            if name in shas:
                actual = sha256_file(p)
                if actual != shas[name]:
                    errs.append(f"EVIDENCE_SHA_MISMATCH:{cid}:{name}")
        if basis == "L":
            if c.get("run_id") or c.get("trace_id") or c.get("index_revision_binding") is not None:
                errs.append(f"U_TYPE_MIXED:{cid}:L_basis_with_run_evidence")
            continue
        if basis != "R":
            errs.append(f"BASIS_INVALID:{cid}:{basis}")
            continue
        if c.get("source") or c.get("historical") or c.get("rerun"):
            errs.append(f"U_TYPE_MIXED:{cid}:R_basis_with_local_control_fields")

        # 3) run 绑定
        run = by_run_id.get(c.get("run_id"))
        if run is None:
            errs.append(f"WRONG_BINDING:{cid}:unknown_run_id")
            continue
        for key in ("plan_sha256", "config_hash", "pipeline_version"):
            if c.get(key) != run.get(key):
                errs.append(f"WRONG_BINDING:{cid}:{key}")
        if c.get("index_revision_binding") != run.get("index_revision_binding"):
            errs.append(f"WRONG_BINDING:{cid}:index_revision_binding")
        q = c.get("question_sha256")
        if not isinstance(q, str) or len(q) != 64 or any(ch not in "0123456789abcdef" for ch in q):
            errs.append(f"WRONG_BINDING:{cid}:question_sha256")

        # 4) 冻结题集：sha256(question) 必须等于 question_sha256
        frozen_path = paths.get("frozen_cases")
        if frozen_path and resolve(str(frozen_path)).exists():
            key = str(resolve(str(frozen_path)))
            if key not in frozen_cache:
                frozen_cache[key] = {row["case_id"]: row for row in load_jsonl(Path(key))}
            spec = frozen_cache[key].get(cid)
            if spec is None:
                errs.append(f"QUESTION_HASH_MISMATCH:{cid}:not_in_frozen_cases")
            else:
                expect = hashlib.sha256(str(spec.get("question", "")).encode("utf-8")).hexdigest()
                if expect != q:
                    errs.append(f"QUESTION_HASH_MISMATCH:{cid}:frozen")

        # 5) run cases.jsonl：同题哈希必须一致
        cases_path = paths.get("run_cases")
        if cases_path and resolve(str(cases_path)).exists():
            key = str(resolve(str(cases_path)))
            if key not in run_cases_cache:
                run_cases_cache[key] = {row["case_id"]: row for row in load_jsonl(Path(key))}
            row = run_cases_cache[key].get(cid)
            if row is None:
                errs.append(f"QUESTION_HASH_MISMATCH:{cid}:not_in_run_cases")
            else:
                product = (row.get("turns") or [{}])[0].get("product") or {}
                if product.get("question_sha256") != q:
                    errs.append(f"QUESTION_HASH_MISMATCH:{cid}:run_cases")
                if row.get("run_id") != c.get("run_id"):
                    errs.append(f"WRONG_BINDING:{cid}:run_cases_run_id")

        # 6) trace 回源
        trace_id = c.get("trace_id")
        if not trace_id:
            errs.append(f"MISSING_TRACE:{cid}")
            continue
        trace_path = paths.get("trace_db")
        if not trace_path or not resolve(str(trace_path)).exists():
            continue  # 已由 EVIDENCE_PATH_MISSING 报出
        key = str(resolve(str(trace_path)))
        if key not in trace_cache:
            con = sqlite3.connect(f"file:{Path(key)}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            trace_cache[key] = {r["trace_id"]: dict(r) for r in con.execute("select * from traces")}
            con.close()
        trace = trace_cache[key].get(str(trace_id))
        if trace is None:
            errs.append(f"TRACE_NOT_IN_RUN:{cid}:{trace_id}")
            continue
        if str(trace.get("question_hash")) != q:
            errs.append(f"TRACE_CASE_MISMATCH:{cid}:question_hash")
        if str(trace.get("run_id")) != str(c.get("run_id")):
            errs.append(f"TRACE_CASE_MISMATCH:{cid}:run_id")
        for trace_field, case_field in (
            ("config_hash", "config_hash"),
            ("pipeline_version", "pipeline_version"),
            ("dataset_version", None),
            ("index_revision", "index_revision_trace"),
            ("path", "trace_path"),
            ("outcome_kind", "trace_outcome"),
        ):
            declared = c.get(case_field) if case_field else run.get("dataset_version")
            actual = trace.get(trace_field)
            if case_field == "index_revision_trace":
                if declared is None or int(actual) != int(declared):
                    errs.append(f"WRONG_BINDING:{cid}:trace.index_revision")
                continue
            if str(actual) != str(declared):
                errs.append(f"WRONG_BINDING:{cid}:trace.{trace_field}")
        if str(trace.get("manifest_sha256")) != str(run.get("corpus_manifest_sha256")):
            errs.append(f"WRONG_BINDING:{cid}:trace.manifest_sha256")

        # 7) 答案类引用证据
        gates = c.get("gates") or {}
        if c.get("expected_kind") == "answer" and not c.get("should_refuse"):
            if "citation_required" not in gates:
                errs.append(f"MISSING_CITATION_EVIDENCE:{cid}")
            if not (c.get("check_evidence") or {}).get("source_hit"):
                errs.append(f"MISSING_CITATION_EVIDENCE:{cid}:source_hit")

        # 8) 采纳一致性（四档）
        adopt = c.get("adopt")
        failing = [g for g, v in gates.items() if isinstance(v, dict) and v.get("status") == "fail"]
        if adopt == "ADOPTED" and failing:
            errs.append(f"ADOPT_INCONSISTENT:{cid}:adopted_with_gate_fail={failing}")
        if adopt == "ADOPTED_WITH_BINDING_PROOF":
            fail_pairs = {
                (g, (v.get("failure") or {}).get("check_id") or "version_binding")
                for g, v in gates.items()
                if isinstance(v, dict) and v.get("status") == "fail"
            }
            mech = c.get("mechanical_gate_failures") or []
            if not fail_pairs:
                errs.append(f"BINDING_PROOF_WITHOUT_MECHANICAL_FAIL:{cid}:no_gate_fail")
            elif not mech:
                errs.append(f"BINDING_PROOF_WITHOUT_MECHANICAL_FAIL:{cid}:no_mechanical_record")
            else:
                mech_pairs = {
                    (m.get("gate"), m.get("check")) for m in mech if isinstance(m, dict)
                }
                if not fail_pairs <= mech_pairs:
                    errs.append(f"BINDING_PROOF_MECHANICAL_RECORD_INCONSISTENT:{cid}")
            proof = c.get("binding_proof")
            required = {
                "decision", "identity", "per_stage_index_versions",
                "same_round_authoritative_evidence", "old_version_applicability",
            }
            if not isinstance(proof, dict) or not required <= set(proof):
                errs.append(f"BINDING_PROOF_MISSING:{cid}")
            else:
                if proof.get("decision") != "D-005":
                    errs.append(f"BINDING_PROOF_MISSING:{cid}:decision")
                ident = proof.get("identity") or {}
                need = ("run_id", "plan_sha256", "config_hash", "pipeline_version",
                        "index_revision_binding", "question_sha256", "trace_id")
                if any(not ident.get(k) for k in need):
                    errs.append(f"BINDING_PROOF_IDENTITY_INCOMPLETE:{cid}")
                ps = proof.get("per_stage_index_versions") or {}
                if any(k not in ps for k in ("ingest_published_max_revision", "product_response_revision",
                                             "rag_index_revision", "trace_index_revision")):
                    errs.append(f"BINDING_PROOF_MISSING:{cid}:per_stage")
                if not proof.get("same_round_authoritative_evidence"):
                    errs.append(f"BINDING_PROOF_MISSING:{cid}:evidence_refs")
                if not (proof.get("old_version_applicability") or {}):
                    errs.append(f"BINDING_PROOF_MISSING:{cid}:old_version")
        if adopt in ("ADOPTED_WITH_BINDING_PROOF", "FAIL", "UNKNOWN") and not c.get("adopt_reason"):
            errs.append(f"ADOPT_INCONSISTENT:{cid}:missing_reason")
        if adopt not in ("ADOPTED", "ADOPTED_WITH_BINDING_PROOF", "FAIL", "UNKNOWN"):
            errs.append(f"ADOPT_INVALID:{cid}:{adopt}")
    return errs


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(json.dumps({"ok": False, "errors": ["USAGE:verify_manifest.py <manifest.json>"]}, ensure_ascii=False))
        return 2
    path = Path(argv[1])
    m = json.loads(path.read_text(encoding="utf-8"))
    errs = validate(m)
    if errs:
        print(json.dumps({"ok": False, "errors": errs}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "cases": len(m["cases"]), "tallies": m["tallies"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
