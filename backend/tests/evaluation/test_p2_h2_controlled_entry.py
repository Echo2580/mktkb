"""T207 05：受控 live 入口（plan-private/preflight/run/recompute）定向测试。

边界（与派单一致）：
- 全部离线合成：合成 30 题/36 回合 dataset、合成 v0.2 annotation + v0.3 addendum、
  合成 .env（哨兵假值）、合成 transport（httpx.MockTransport）、tmp 固定路径 GO/预算/账本；
- 零真实模型/产品/付费/预留；不读真实 .env/真实 H2 题面/标签/私有密文/真实 key；
- 断言覆盖：绑定/ GO/账本/首错停/账本配对/封存/安全聚合/秘密哨兵/反例拒绝。
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import importlib.util
import json
import os
import re
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_EVALUATION_TESTS = Path(__file__).resolve().parent
if str(_EVALUATION_TESTS) not in sys.path:
    sys.path.insert(0, str(_EVALUATION_TESTS))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb import live_authorization  # noqa: E402
from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation import p2_contracts as c  # noqa: E402
from mktkb.evaluation import p2_evidence_capture as capture  # noqa: E402
from mktkb.evaluation import p2_evidence_io as evidence_io  # noqa: E402
from mktkb.evaluation import p2_live  # noqa: E402
from mktkb.evaluation import p2_scoring  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, cases_to_jsonl  # noqa: E402
from mktkb.evaluation.p2_dataset import P2Dataset, P2Manifest  # noqa: E402
from mktkb.evaluation.p2_holdout_plan import build_holdout_plan  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    product_pipeline_version,
)
from evaluation.test_p2_hard_evidence import (  # noqa: E402
    CONTRACT as H2_CONTRACT,
    SCHEMA as H2_SCHEMA,
    make_addendum,
    make_annotation,
)
from evaluation.test_p2_runner import LEGACY_QUESTION  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "tools" / "p2_h2_controlled_execute.py"
D01 = ROOT / "fixtures" / "acceptance" / "normal" / "D01_物品位置表.xlsx"
D04 = ROOT / "fixtures" / "acceptance" / "normal" / "D04_活动策划流程.docx"

NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
TOTAL_LIMIT_CNY = 40.0
STAGE_LIMIT_CNY = 20.0
CENTERS = {"answer_retrieval": 8.5, "ocr": 6.5, "judge": 3.0, "independent": 2.0}
BUSINESS_DATE = "2026-10-28"
CHAT_SECRET = "P2H2ENTRY_CHAT_SECRET_SENTINEL_DO_NOT_EXPORT_aaa111"
DASHSCOPE_SECRET = "P2H2ENTRY_DASHSCOPE_SECRET_SENTINEL_DO_NOT_EXPORT_bbb222"
OCR_SECRET = "P2H2ENTRY_OCR_SECRET_SENTINEL_DO_NOT_EXPORT_ccc333"
SECRETS = (CHAT_SECRET, DASHSCOPE_SECRET, OCR_SECRET)

STRATA = (("paraphrase", 10), ("multi_turn", 5), ("negative", 5), ("stale_conflict", 5), ("cross_doc_security", 5))


@pytest.fixture(scope="module")
def entry() -> Any:
    spec = importlib.util.spec_from_file_location("p2_h2_controlled_entry_under_test", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def asyncio_test(func):
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


# --------------------------------------------------------------------------- #
# 合成 30 题 / 36 回合 + manifest / dataset / annotation / addendum
# --------------------------------------------------------------------------- #


def synthetic_cases() -> tuple[CaseSpec, ...]:
    cases: list[CaseSpec] = []
    index = 0
    for stratum, count in STRATA:
        for _ in range(count):
            if index < 4:
                turns = (
                    {"question": "合成第二回合问题" + str(index) + "A"},
                    {"question": "合成第二回合问题" + str(index) + "B"},
                )
            elif index == 4:
                turns = (
                    {"question": "合成第二回合问题" + str(index) + "A"},
                    {"question": "合成第三回合问题" + str(index) + "B"},
                    {"question": "合成第四回合问题" + str(index) + "C"},
                )
            else:
                turns = ()
            cases.append(
                CaseSpec(
                    case_id="SYN-" + f"{index:02d}",
                    suite="p2-holdout",
                    split="holdout",
                    stratum=stratum,
                    business_date=BUSINESS_DATE,
                    question=(
                        ""
                        if turns
                        else (LEGACY_QUESTION if index in (5, 6) else ("合成问题" + str(index)))
                    ),
                    turns=turns,
                    expected_values=(),
                    expected_sources=(),
                    relevant_units=(),
                    should_refuse=False,
                    labeler="synthetic-fixture",
                    label_version="synthetic-v1",
                )
            )
            index += 1
    return tuple(cases)


def synthetic_manifest() -> P2Manifest:
    payload = {
        "schema_version": "p2-holdout-manifest/v0.1",
        "dataset_version": "P2-HOLDOUT-v2",
        "suite": "p2-holdout",
        "label_version": "synthetic-v1",
        "case_count": 30,
        "strata": {name: count for name, count in STRATA},
        "business_date": BUSINESS_DATE,
        "created_utc": "2026-11-10T11:08:00Z",
        "author": "synthetic-fixture",
        "encryption": {"kind": "fernet", "key_id": "synthetic-key"},
        "questions_plaintext_sha256": "1" * 64,
        "labels_plaintext_sha256": "2" * 64,
        "questions_ciphertext_sha256": "3" * 64,
        "labels_ciphertext_sha256": "4" * 64,
        "turn_stats": {
            "total_turns": 36,
            "max_turns_per_case": 3,
            "turn_histogram": {"1": 25, "2": 4, "3": 1},
        },
    }
    return P2Manifest.from_dict(payload, manifest_sha256="a" * 64)


def synthetic_dataset(cases: tuple[CaseSpec, ...] | None = None) -> P2Dataset:
    chosen = tuple(cases if cases is not None else synthetic_cases())
    labels = {case.case_id: {"reference_answer": "合成参考答案"} for case in chosen}
    return P2Dataset(visibility="holdout", manifest=synthetic_manifest(), cases=chosen, labels=labels)


def _sha_json(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


ASSIGNMENTS = {
    "base_b0": 26,
    "base_b0_plus_v01": 1,
    "pre_v05_without_v07": 2,
    "post_v05_without_v01": 1,
}
BATCHES = {"base_b0": 8, "base_b0_plus_v01": 9, "pre_v05_without_v07": 11, "post_v05_without_v01": 13}


def _owners(cases: tuple[CaseSpec, ...]) -> list[str]:
    owners: list[str] = []
    for scenario, count in ASSIGNMENTS.items():
        owners.extend([scenario] * count)
    assert len(owners) == len(cases)
    return owners


class FakeContract:
    """只实现 plan-private/recompute 实际调用的公开方法（不伪造 ValidatedScenarioContract）。"""

    def __init__(self, cases: tuple[CaseSpec, ...], annotation: dict[str, Any], *, batches: dict[str, int] | None = None) -> None:
        self.cases = tuple(cases)
        self.owners = _owners(self.cases)
        self.batches = dict(batches or BATCHES)
        bindings = annotation["bindings"]
        self.bindings = {
            "assignment_sha256": "5" * 64,
            "custody_sha256": "6" * 64,
            "review_sha256": "7" * 64,
            "scenario_contract_sha256": bindings["scenario_contract_sha256"],
            "ingest_plan_sha256": bindings["ingest_plan_sha256"],
            "full_cases_sha256": bindings["cases_sha256"],
            "manifest_sha256": bindings["manifest_sha256"],
            "schema_sha256": bindings["schema_sha256"],
            "source_map_sha256": bindings["source_map_sha256"],
        }

    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(ASSIGNMENTS)

    def _cases(self, name: str) -> tuple[CaseSpec, ...]:
        return tuple(case for case, owner in zip(self.cases, self.owners) if owner == name)

    def binding(self, name: str) -> dict[str, str]:
        cases = self._cases(name)
        return dict(
            scenario_id=name,
            **self.bindings,
            subset_sha256=_sha_json([case.case_id for case in cases]),
            scenario_ingest_sha256=_sha_json({"scenario": name, "batches": self.batches[name]}),
        )

    def subset(self, name: str) -> P2RunDataset:
        cases = self._cases(name)
        strata: dict[str, int] = {}
        for case in cases:
            strata[str(case.stratum)] = strata.get(str(case.stratum), 0) + 1
        return P2RunDataset(
            visibility="holdout",
            cases=cases,
            identity={
                "dataset_version": "P2-HOLDOUT-v2",
                "label_version": "synthetic-v1",
                "suite": "p2-holdout",
                "manifest_sha256": "a" * 64,
                "case_count": len(cases),
                "strata": strata,
                "turn_stats": {
                    "total_turns": sum(len(case_questions_safe(case)) for case in cases),
                    "max_turns_per_case": max(
                        (len(case_questions_safe(case)) for case in cases), default=1
                    ),
                },
                "scenario_binding": self.binding(name),
            },
        )

    def ingest_plan(self, name: str) -> P2IngestPlan:
        sources = tuple(IngestSource(path=D01) for _ in range(self.batches[name]))
        return P2IngestPlan(sources=sources, label="synthetic-" + name)

    def build_plan(self, name: str, *, plan_id: str, created_utc: str, plan_version: str = "v0.1", max_requests: int = 1100) -> Any:
        cases = tuple(
            (case.case_id, len(case_questions_safe(case))) for case in self._cases(name)
        )
        return build_holdout_plan(
            cases=cases,
            ingest_batches=self.batches[name],
            plan_id=plan_id,
            plan_version=plan_version,
            created_utc=created_utc,
            max_requests=max_requests,
            scenario_binding=self.binding(name),
        )

    def safe_summary(self) -> dict[str, Any]:
        counts = {name: 0 for name in ASSIGNMENTS}
        for owner in self.owners:
            counts[owner] = counts.get(owner, 0) + 1
        return {
            "case_count": 30,
            "total_turns": 36,
            "scenario_counts": counts,
            "axis_counts": {},
            "fixed_gap_counts": {},
            "quality_readiness": "BLOCKED",
            "runtime_axis_evidence_produced": False,
            "release_ready": False,
        }


def case_questions_safe(case: CaseSpec) -> tuple[str, ...]:
    from mktkb.evaluation.product_adapter import case_questions

    return case_questions(case)


def make_bundle(entry: Any, tmp_path: Path, cases: tuple[CaseSpec, ...] | None = None) -> SimpleNamespace:
    chosen = tuple(cases if cases is not None else synthetic_cases())
    dataset = synthetic_dataset(chosen)
    annotation = make_annotation(chosen)
    contract = FakeContract(chosen, annotation)
    inputs = {}
    real_bytes = {
        # 合成 v0.2 标注“密文文件”：真 Fernet 字节，记录 sha 只可能是密文文件摘要。
        "annotation_ciphertext": Fernet(Fernet.generate_key()).encrypt(
            json.dumps(
                annotation, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ),
        "annotation_schema": H2_SCHEMA.read_bytes(),
        "scenario_contract": H2_CONTRACT.read_bytes(),
    }
    for index, name in enumerate(entry.INPUT_NAMES):
        target = tmp_path / "inputs" / (name + ".bin")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(real_bytes.get(name, b"synthetic-" + name.encode()))
        inputs[name] = {
            "path": str(target.resolve()),
            "sha256": entry.sha256_file(target),
            "bytes": target.stat().st_size,
        }
    # 真实 v0.3 语义：addendum 绑定 v0.2 标注“密文文件”SHA256（不是明文 canonical sha）。
    annotation_cipher_sha256 = inputs["annotation_ciphertext"]["sha256"]
    addendum = make_addendum(
        chosen, annotation, annotation_cipher_sha256=annotation_cipher_sha256
    )
    bundle = SimpleNamespace(
        dataset=dataset,
        contract=contract,
        annotation=annotation,
        addendum=addendum,
        addendum_acceptance={
            "schema_version": "p2-h2-custody-gapaddendum-manager-acceptance/v0.3",
            "merged_axis_counts": None,
            "gap_total": 4,
            "gap_resolved": 4,
            "gap_kept_unknown": 0,
        },
        inputs=inputs,
        business_date=BUSINESS_DATE,
    )
    merged = entry._prepare_annotation(
        bundle, H2_SCHEMA, H2_CONTRACT
    )
    bundle.addendum_acceptance["merged_axis_counts"] = merged.public_summary()["axis_counts"]
    return bundle


def _write_ledger(path: Path, *, amount: float = 2.0) -> None:
    path.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": amount, "source": "unit-test"})
        + "\n",
        encoding="utf-8",
    )


def _write_budget(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "limit_cny": TOTAL_LIMIT_CNY,
                "historical_conservative_accounted_cny": 2.0,
                "stages": {"S2-DEV": 18.0, "P2-LIVE": STAGE_LIMIT_CNY},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_go(path: Path, *, ledger: Path, plan: Any, now: datetime = NOW, plan_sha: str | None = None, ledger_sha: str | None = None) -> None:
    issued = now.replace(minute=0, second=0, microsecond=0)
    expires = issued + timedelta(days=1)
    path.write_text(
        json.dumps(
            {
                "document": "P2-LIVE-GO",
                "schema_version": "p2-live-go/v0.1",
                "stage": "P2-LIVE",
                "authorization": "SYNTHETIC-UNIT-TEST-GO（零真实调用）",
                "issued_by": "pytest-synthetic",
                "nonce": "synthetic-nonce-0123456789abcdef",
                "issued_utc": issued.isoformat(),
                "expires_utc": expires.isoformat(),
                "budget_ledger_path": str(ledger),
                "budget_ledger_sha256": ledger_sha or live_authorization.historical_prefix_sha256(ledger),
                "budget_total_limit_cny": TOTAL_LIMIT_CNY,
                "scope": {
                    "plan_id": plan.plan_id,
                    "plan_sha256": plan_sha or plan.plan_sha256,
                    "operations": list(plan.operations),
                    "cost_centers_cny": dict(CENTERS),
                    "stage_limits_cny": {"P2-LIVE": STAGE_LIMIT_CNY},
                    "max_requests": 1100,
                    "max_request_cny": 0.5,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def fixed_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    ledger = tmp_path / "fixed" / "live-ledger.jsonl"
    budget = tmp_path / "fixed" / "budget.json"
    go = tmp_path / "fixed" / "P2-LIVE-GO.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    _write_ledger(ledger)
    _write_budget(budget)
    monkeypatch.setattr(p2a, "P2_LEDGER_PATH", ledger)
    monkeypatch.setattr(p2a, "P2_BUDGET_PATH", budget)
    monkeypatch.setattr(p2a, "P2_GO_PATH", go)
    monkeypatch.setenv(live_authorization.TOTAL_LIMIT_ENV, str(TOTAL_LIMIT_CNY))
    return SimpleNamespace(ledger=ledger, budget=budget, go=go)


def _env_values() -> dict[str, str]:
    return {
        "MKTKB_MODEL_API_KEY": CHAT_SECRET,
        "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com",
        "MKTKB_MODEL_NAME": "deepseek-flash",
        "DASHSCOPE_API_KEY": DASHSCOPE_SECRET,
        "DASHSCOPE_BASE_URL": "https://dashscope.aliyuncs.com",
        "MKTKB_OCR_SECRET_ID": OCR_SECRET,
        "MKTKB_OCR_SECRET_KEY": OCR_SECRET,
        "MKTKB_OCR_REGION": "ap-guangzhou",
        "MKTKB_OCR_DISABLED": "0",
        "MKTKB_PROJECT_TOTAL_LIMIT_CNY": str(TOTAL_LIMIT_CNY),
        "MKTKB_P2_HOLDOUT_ROOT": "D:/synthetic-holdout-root",
        "MKTKB_P2_HOLDOUT_KEY_FILE": "D:/synthetic-holdout-root/key",
    }


def runtime_options(entry: Any, tmp_path: Path) -> Any:
    """A：显式运行参数（holdout 根/钥/总上限）；全部在仓外临时目录。"""
    root = tmp_path / "holdout-root"
    root.mkdir(parents=True, exist_ok=True)
    key = tmp_path / "holdout.key"
    key.write_bytes(Fernet.generate_key())
    return entry.RuntimeOptions(
        holdout_root=root,
        holdout_key_file=key,
        project_total_limit_cny=TOTAL_LIMIT_CNY,
    )


#: 真实授权 .env 的**键名形状**（值全部合成；不含 holdout/总上限/凭据以外的运行键）。
REAL_ENV_SHAPE: dict[str, str] = {
    "MKTKB_CSRF_SECRET": "synthetic-csrf-sentinel-not-a-real-secret",
    "MKTKB_ADMIN_PASSWORD": "synthetic-admin-sentinel",
    "MKTKB_EMPLOYEE_PASSWORD": "synthetic-employee-sentinel",
    "MKTKB_TRUSTED_ORIGINS": "http://127.0.0.1:59885",
    "MKTKB_COOKIE_SECURE": "false",
    "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com",
    "MKTKB_MODEL_NAME": "deepseek-chat",
    "MKTKB_MODEL_API_KEY": CHAT_SECRET,
    "MKTKB_OCR_SECRET_ID": OCR_SECRET,
    "MKTKB_OCR_SECRET_KEY": OCR_SECRET,
    "DASHSCOPE_API_KEY": DASHSCOPE_SECRET,
}


# --------------------------------------------------------------------------- #
# 合成 run 装配（真实 run_live_p2/gate/账本 + 合成 transport）
# --------------------------------------------------------------------------- #


class UsageChatBackend(MockChatBackend):
    def _completion(self, request: httpx.Request, content: str, *, call: int) -> httpx.Response:
        response = super()._completion(request, content, call=call)
        payload = json.loads(response.content.decode("utf-8"))
        payload["usage"] = {
            "prompt_tokens": 64,
            "completion_tokens": 32,
            "total_tokens": 96,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 64,
        }
        return httpx.Response(200, json=payload, request=request)


def embedding_transport(calls: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        texts = list(body.get("input") or ())
        dims = int(body.get("dimensions") or 1024)
        calls.append({"texts": len(texts), "dimensions": dims})
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": index, "embedding": [0.01] * dims}
                    for index in range(len(texts))
                ],
                "usage": {"total_tokens": 40},
                "id": "emb-" + str(len(calls)),
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def rerank_transport(calls: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        docs = list((body.get("input") or {}).get("documents") or ())
        calls.append({"documents": len(docs)})
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": index, "relevance_score": 0.9 - index * 0.01}
                        for index in range(len(docs))
                    ]
                },
                "usage": {"total_tokens": 80},
                "request_id": "rerank-" + str(len(calls)),
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def _transports(chat: MockChatBackend) -> dict[str, Any]:
    return {
        "chat": chat.transport,
        "embedding": embedding_transport([]),
        "rerank": rerank_transport([]),
    }


def _subset_dataset(entry: Any, cases: tuple[CaseSpec, ...]) -> P2RunDataset:
    strata: dict[str, int] = {}
    for case in cases:
        strata[str(case.stratum)] = strata.get(str(case.stratum), 0) + 1
    return P2RunDataset(
        visibility="holdout",
        cases=cases,
        identity={
            "dataset_version": "P2-HOLDOUT-v2",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "a" * 64,
            "case_count": len(cases),
            "strata": strata,
            "turn_stats": {
                "total_turns": sum(len(case_questions_safe(case)) for case in cases),
                "max_turns_per_case": max(
                    (len(case_questions_safe(case)) for case in cases), default=1
                ),
            },
        },
    )


def chain_setup(entry: Any, tmp_path: Path, fixed_paths: SimpleNamespace, *, chat: MockChatBackend | None = None) -> SimpleNamespace:
    # 两个 legacy 问题强制走模型措辞面：合成 transport 才能覆盖 chat 发送/usage/首错停。
    cases = tuple(case for case in synthetic_cases() if case.case_id in {"SYN-05", "SYN-06"})
    dataset = _subset_dataset(entry, cases)
    plan = build_holdout_plan(
        cases=[(case.case_id, 1) for case in cases],
        # 与 live wiring 回归同口径：内容入库的 embedding 批数按 8 预留（未用的不花）。
        ingest_batches=8,
        plan_id="P2-H2-SYNTHETIC-UNIT-1",
        plan_version="v0.1",
        created_utc="2026-11-19T00:00:00+00:00",
        max_requests=1100,
    )
    code_version = entry.code_digest()
    config = entry._build_config(
        business_date=BUSINESS_DATE,
        inputs={},
        code_version=code_version,
        thresholds_approved=False,
    )
    config_sha = entry.canonical_sha256(config)
    run_id = "p2-h2-synth-r1"
    bindings = {
        "run_id": run_id,
        "plan_id": str(plan.plan_id),
        "plan_sha256": str(plan.plan_sha256),
        "dataset_version": "P2-HOLDOUT-v2",
        "manifest_sha256": "a" * 64,
        "label_version": "synthetic-v1",
        "suite": "p2-holdout",
        "scenario_id": "synthetic",
        "scenario_contract_sha256": "b" * 64,
        "assignment_sha256": "c" * 64,
        "custody_sha256": "d" * 64,
        "config_sha256": config_sha,
        "pipeline_version": str(product_pipeline_version()),
        "index_revision": capture.LIVE_PENDING_INDEX_REVISION,
        "code_version": code_version,
        "fixture_kind": capture.LIVE_FIXTURE_KIND,
    }
    run_entry = {
        "run_index": 0,
        "scenario_id": "synthetic",
        "run_id": run_id,
        "plan_id": str(plan.plan_id),
        "plan_sha256": str(plan.plan_sha256),
        "evidence_bindings": bindings,
    }
    document = {
        "business_date": BUSINESS_DATE,
        "code_version": code_version,
        "config_sha256": config_sha,
        "config": config,
        "binding_sha256": "9" * 64,
    }
    go_path = fixed_paths.go
    _write_go(go_path, ledger=fixed_paths.ledger, plan=plan)
    key_path = tmp_path / "evidence.key"
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    out_dir = tmp_path / "product"
    evidence_root = tmp_path / "evidence"
    seal_root = tmp_path / "seal"
    chat_backend = chat if chat is not None else UsageChatBackend()
    options = entry.RunOptions(
        out_dir=out_dir,
        evidence_root=evidence_root,
        seal_root=seal_root,
        evidence_key_file=key_path,
        process_env=_env_values(),
        transports=_transports(chat_backend),
        now=NOW,
    )
    ingest_plan = P2IngestPlan(sources=(IngestSource(D04),), label="synthetic-ingest")
    return SimpleNamespace(
        cases=cases,
        dataset=dataset,
        plan=plan,
        run_entry=run_entry,
        document=document,
        options=options,
        key=key,
        chat=chat_backend,
        ingest_plan=ingest_plan,
        out_dir=out_dir,
        evidence_root=evidence_root,
        seal_root=seal_root,
    )


async def _run_chain(setup: SimpleNamespace, entry: Any) -> dict[str, Any]:
    return await entry._execute_loaded(
        binding_doc=setup.document,
        run_entry=setup.run_entry,
        plan=setup.plan,
        dataset=setup.dataset,
        ingest_plan=setup.ingest_plan,
        contract=None,
        options=setup.options,
    )


def ledger_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# plan-private
# --------------------------------------------------------------------------- #


def test_plan_private_synthetic_matrix_and_privacy(entry: Any, tmp_path: Path) -> None:
    bundle = make_bundle(entry, tmp_path)
    payload = entry.plan_private(
        bundle,
        entry.PlanOptions(
            out_dir=tmp_path / "private",
            created_utc="2026-11-13T00:00:00+00:00",
        ),
    )
    assert payload["cases"] == 30 and payload["turns"] == 36
    assert payload["scenario_counts"] == ASSIGNMENTS
    assert payload["business_date"] == BUSINESS_DATE
    assert [run["scenario_id"] for run in payload["runs"]] == list(ASSIGNMENTS)
    assert [run["ingest_batches"] for run in payload["runs"]] == list(BATCHES.values())
    assert [run["case_count"] for run in payload["runs"]] == list(ASSIGNMENTS.values())
    assert sum(run["turn_count"] for run in payload["runs"]) == 36
    assert len({run["plan_sha256"] for run in payload["runs"]}) == 4
    assert payload["chat_model"] == "deepseek-flash"
    assert payload["model_pinned"] is True
    assert payload["ingest_batches_source"] == "frozen_scenario_contract"
    assert payload["synthetic_corpus_inference"] is False
    for run in payload["runs"]:
        allocation = run["index_embedding_allocation"]
        assert allocation["source"] == "frozen_scenario_contract"
        assert allocation["item_id"] == "ingest-index-embedding"
        assert allocation["batches"] == BATCHES[run["scenario_id"]]
        assert allocation["requests"] == BATCHES[run["scenario_id"]]
    serialized = json.dumps(payload, ensure_ascii=False)
    for case in bundle.dataset.cases:
        assert case.case_id not in serialized
        assert "合成" not in serialized
    binding_path = Path(payload["binding_file"])
    assert binding_path.is_file()
    document = entry.load_run_binding(binding_path)
    assert document["binding_sha256"] == payload["binding_sha256"]
    for run in document["runs"]:
        plan_file = Path(run["plan_file"])
        assert plan_file.is_file()
        assert entry.sha256_file(plan_file) == run["plan_file_sha256"]
        plan = c.P2RunPlan.from_dict(entry._read_json_mapping(plan_file, "plan"))
        assert plan.plan_sha256 == run["plan_sha256"]
        assert dict(plan.scenario_binding) == run["scenario_binding"]
        assert [item for item in plan.items if item.operation == "index_embedding"][0].requests == run["ingest_batches"]


def test_plan_private_plan_sha_stable_for_same_inputs(entry: Any, tmp_path: Path) -> None:
    bundle = make_bundle(entry, tmp_path)
    first = entry.plan_private(
        bundle,
        entry.PlanOptions(out_dir=tmp_path / "a", created_utc="2026-11-13T00:00:00+00:00"),
    )
    second = entry.plan_private(
        bundle,
        entry.PlanOptions(out_dir=tmp_path / "b", created_utc="2026-11-13T00:00:00+00:00"),
    )
    assert [run["plan_sha256"] for run in first["runs"]] == [
        run["plan_sha256"] for run in second["runs"]
    ]
    assert first["code_version"] == second["code_version"]
    assert first["config_sha256"] == second["config_sha256"]
    third = entry.plan_private(
        bundle,
        entry.PlanOptions(out_dir=tmp_path / "c", created_utc="2026-11-14T00:00:00+00:00"),
    )
    assert third["runs"][0]["plan_sha256"] != first["runs"][0]["plan_sha256"]


def test_plan_private_refuses_business_date_mismatch(entry: Any, tmp_path: Path) -> None:
    cases = synthetic_cases()
    bad = list(cases)
    bad[3] = replace(bad[3], business_date="2026-10-29")
    bundle = make_bundle(entry, tmp_path, cases=tuple(bad))
    with pytest.raises(entry.EntryError) as excinfo:
        entry.plan_private(
            bundle,
            entry.PlanOptions(out_dir=tmp_path / "private-bad", created_utc="2026-11-13T00:00:00+00:00"),
        )
    assert excinfo.value.code == "business_date_case_mismatch"
    bundle_ok = make_bundle(entry, tmp_path)
    with pytest.raises(entry.EntryError) as excinfo:
        entry.plan_private(
            bundle_ok,
            entry.PlanOptions(
                out_dir=tmp_path / "private-bad2",
                created_utc="2026-11-13T00:00:00+00:00",
                business_date="2026-10-29",
            ),
        )
    assert excinfo.value.code == "business_date_binding_mismatch"


def test_plan_private_refuses_scenario_counts_and_batches(entry: Any, tmp_path: Path) -> None:
    bundle = make_bundle(entry, tmp_path)
    original = dict(bundle.contract.batches)
    bundle.contract.batches = {name: 8 for name in original}
    with pytest.raises(entry.EntryError) as excinfo:
        entry.plan_private(
            bundle,
            entry.PlanOptions(out_dir=tmp_path / "bad-batches", created_utc="2026-11-13T00:00:00+00:00"),
        )
    assert excinfo.value.code == "plan_ingest_batches_mismatch"

    bundle2 = make_bundle(entry, tmp_path / "second")
    bundle2.contract.owners = ["base_b0"] * 30
    with pytest.raises(entry.EntryError) as excinfo:
        entry.plan_private(
            bundle2,
            entry.PlanOptions(out_dir=tmp_path / "bad-counts", created_utc="2026-11-13T00:00:00+00:00"),
        )
    assert excinfo.value.code == "scenario_counts_mismatch"


def test_plan_private_refuses_axis_counts_and_binding_tamper(entry: Any, tmp_path: Path) -> None:
    bundle = make_bundle(entry, tmp_path)
    bundle.addendum_acceptance["merged_axis_counts"] = {
        "safety": {"required": 1, "not_applicable": 29, "unknown": 0}
    }
    with pytest.raises(entry.EntryError) as excinfo:
        entry.plan_private(
            bundle,
            entry.PlanOptions(out_dir=tmp_path / "bad-axes", created_utc="2026-11-13T00:00:00+00:00"),
        )
    assert excinfo.value.code == "axis_counts_mismatch"

    bundle2 = make_bundle(entry, tmp_path / "tamper")
    payload = entry.plan_private(
        bundle2,
        entry.PlanOptions(out_dir=tmp_path / "ok", created_utc="2026-11-13T00:00:00+00:00"),
    )
    document = entry.load_run_binding(Path(payload["binding_file"]))
    tampered = json.loads(json.dumps(document))
    tampered["runs"][0]["plan_sha256"] = "e" * 64
    with pytest.raises(entry.EntryError) as excinfo:
        entry._validate_binding_document(tampered)
    assert excinfo.value.code == "run_binding_invalid"

    changed = json.loads(json.dumps(document))
    first_input = changed["inputs"]["holdout_manifest"]
    Path(first_input["path"]).write_bytes(b"changed-after-plan")
    with pytest.raises(entry.EntryError) as excinfo:
        entry._verify_input_digests(changed)
    assert excinfo.value.code == "input_changed_since_plan"


# --------------------------------------------------------------------------- #
# R2：v0.2 标注密文 SHA256 绑定（真实 v0.3 addendum 语义）
# --------------------------------------------------------------------------- #


def test_prepare_annotation_uses_v02_ciphertext_record_sha(
    entry: Any, tmp_path: Path
) -> None:
    bundle = make_bundle(entry, tmp_path / "ok")
    cipher_sha = bundle.inputs["annotation_ciphertext"]["sha256"]
    cipher_path = Path(bundle.inputs["annotation_ciphertext"]["path"])
    assert re.fullmatch(r"[0-9a-f]{64}", cipher_sha)
    # 记录值来自 .fernet 文件字节（不是明文 canonical sha）。
    assert entry.sha256_file(cipher_path) == cipher_sha
    # addendum 绑定的是记录里的 v0.2 标注密文文件摘要，而不是明文 canonical sha。
    assert bundle.addendum["bindings"]["annotations_v0_2_sha256"] == cipher_sha
    assert cipher_sha != entry.canonical_sha256(bundle.annotation)
    merged = entry._prepare_annotation(bundle, H2_SCHEMA, H2_CONTRACT)
    assert (
        merged.axis(bundle.dataset.cases[3].case_id, "cross_entity")
        == bundle.addendum["gaps"][0]["axis_value"]
    )
    # plan-private 不因该参数回归：同一 bundle 仍产出 30 题/36 回合计划。
    payload = entry.plan_private(
        bundle,
        entry.PlanOptions(
            out_dir=tmp_path / "r2-plan",
            created_utc="2026-11-13T00:00:00+00:00",
        ),
    )
    assert payload["cases"] == 30 and payload["turns"] == 36
    assert [run["scenario_id"] for run in payload["runs"]] == list(ASSIGNMENTS)


def test_prepare_annotation_refuses_non_ciphertext_sha(
    entry: Any, tmp_path: Path
) -> None:
    def assert_refused(bundle: SimpleNamespace, detail: str) -> None:
        with pytest.raises(entry.EntryError) as excinfo:
            entry._prepare_annotation(bundle, H2_SCHEMA, H2_CONTRACT)
        assert excinfo.value.code == "annotation_invalid"
        assert detail in excinfo.value.detail
        out_dir = tmp_path / ("out-" + detail)
        with pytest.raises(entry.EntryError) as excinfo:
            entry.plan_private(
                bundle,
                entry.PlanOptions(
                    out_dir=out_dir,
                    created_utc="2026-11-13T00:00:00+00:00",
                ),
            )
        assert excinfo.value.code == "annotation_invalid"
        assert detail in excinfo.value.detail
        assert not out_dir.exists()

    # 1) 记录值与 addendum 绑定的密文 sha 不等 → 固定拒绝。
    mismatch = make_bundle(entry, tmp_path / "mismatch")
    mismatch.inputs["annotation_ciphertext"]["sha256"] = "a" * 64
    assert_refused(mismatch, "addendum_annotation_binding_mismatch")

    # 2) 用明文 canonical sha 冒充密文文件 sha → 固定拒绝。
    plaintext = make_bundle(entry, tmp_path / "plaintext")
    plaintext.inputs["annotation_ciphertext"]["sha256"] = entry.canonical_sha256(
        plaintext.annotation
    )
    assert_refused(plaintext, "addendum_annotation_binding_mismatch")

    # 3) 缺 annotation_ciphertext 记录（缺参）→ 固定拒绝。
    missing = make_bundle(entry, tmp_path / "missing")
    missing.inputs.pop("annotation_ciphertext")
    assert_refused(missing, "addendum_annotation_cipher_sha_required")

    # 4) 非 64-hex 的“密文 sha” → 固定拒绝。
    invalid = make_bundle(entry, tmp_path / "invalid")
    invalid.inputs["annotation_ciphertext"]["sha256"] = "not-a-sha"
    assert_refused(invalid, "addendum_annotation_cipher_sha_invalid")


# --------------------------------------------------------------------------- #
# run 全链 + 独立重算
# --------------------------------------------------------------------------- #


def test_run_chain_evidence_seal_recompute_and_masquerade(
    entry: Any, tmp_path: Path, fixed_paths: SimpleNamespace
) -> None:
    setup = chain_setup(entry, tmp_path, fixed_paths)
    receipt = asyncio.run(_run_chain(setup, entry))
    assert receipt["ok"] is True, receipt
    assert receipt["status"] == "succeeded"
    assert receipt["stop_code"] is None
    assert receipt["requests"]["sent"] == 2
    assert receipt["requests"]["planned"] == 16
    assert receipt["requests"]["attempts_reserved"] >= 3
    assert receipt["requests"]["attempts_scope"] == "all_attempts"
    assert receipt["real_sends"] == 0
    assert receipt["evidence"]["turn_files"] == 2
    assert receipt["evidence"]["manifest_present"] is True
    assert receipt["evidence"]["manifest_turn_count"] == 2
    assert receipt["evidence"]["readback_ok"] is True
    assert receipt["cleanup"]["business_db_removed"] is True
    assert receipt["cleanup"]["trace_db_removed"] is True
    assert receipt["cleanup"]["data_dir_removed"] is True
    assert receipt["cleanup"]["run_dir_removed"] is True
    assert receipt["cleanup"]["plaintext_clean"] is True
    assert receipt["cleanup"]["removed_count"] >= 1
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        for item in receipt["cleanup"]["removed_paths"]
    )
    assert receipt["seal"]["sealed"] is True
    assert receipt["case_plan"] is not None
    assert receipt["chat_model"] == "deepseek-flash"
    assert receipt["model_pinned"] is True
    assert receipt["plan_ingest"]["source"] == "frozen_scenario_contract"
    assert receipt["case_plan_failed_turn_code"] is None
    assert not (setup.out_dir / "data").exists()
    assert not (setup.out_dir / "p2-run").exists()
    assert [path.relative_to(setup.out_dir).as_posix() for path in setup.out_dir.rglob("*") if path.is_file()] == [
        "controlled/case-plan.json"
    ]
    leaked = [
        path.name
        for path in setup.out_dir.rglob("*")
        if path.is_file()
        and any(
            needle.encode() in path.read_bytes()
            for needle in ("合成问题", "活动策划需要哪些步骤", "合成参考答案")
        )
    ]
    assert leaked == []
    receipt_path = Path(receipt["receipt_path"])
    assert receipt_path.is_file()
    on_disk = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert on_disk["run_binding"] == receipt["run_binding"]
    for secret in SECRETS:
        assert secret not in json.dumps(receipt, ensure_ascii=False)

    rows = ledger_rows(fixed_paths.ledger)
    mine = [row for row in rows if row.get("run_id") == receipt["run_id"]]
    reservations = [row for row in mine if row.get("event") == "reserved"]
    results = [row for row in mine if row.get("event") == "result"]
    assert len(reservations) == len(results) == receipt["requests"]["attempts_reserved"]
    assert {row["reservation_id"] for row in reservations} == {
        row["reservation_id"] for row in results
    }

    case_plan_path = Path(receipt["case_plan"]["path"])
    case_plan = json.loads(case_plan_path.read_text(encoding="utf-8"))
    assert len(case_plan["cases"]) == 2
    assert sum(len(row["turns"]) for row in case_plan["cases"]) == 2
    assert all(row["turns"][0]["status"] == "executed" for row in case_plan["cases"])
    assert case_plan["run_binding"] == receipt["run_binding"]
    assert case_plan["bindings"]["fixture_kind"] == capture.LIVE_FIXTURE_KIND
    assert re.fullmatch(r"[0-9]+", case_plan["bindings"]["index_revision"])

    sealed_files = [path for path in setup.out_dir.rglob("*") if path.is_file()]
    assert sealed_files and all(not (path.stat().st_mode & 0o200) for path in sealed_files)

    bundle = make_bundle(entry, tmp_path / "recompute")
    merged = entry._prepare_annotation(bundle, H2_SCHEMA, H2_CONTRACT)
    result = entry._recompute_loaded(
        document=setup.document,
        run_entry=setup.run_entry,
        plan=setup.plan,
        cases=setup.dataset.cases,
        annotation=merged,
        case_plan_payload=case_plan,
        evidence_dir=receipt["paths"]["evidence_dir"],
        key=setup.key,
        ledger_path=fixed_paths.ledger,
        receipt=receipt,
        out_card=tmp_path / "recomputed-card.json",
    )
    assert result["card"]["total"] == 2
    assert result["card"]["executed"] + result["card"]["errors"] == 2
    assert result["card"]["hard_failures_by_kind"].keys() == {
        "safety",
        "cross_user",
        "cross_entity",
        "stale_source",
    }
    assert result["card"]["release_ready"] is False
    for table in result["card"]["axes"].values():
        assert table["planned"] == 2
        assert table["checked"] + table["unknown"] == 2
    assert result["coverage"]["executed_turns"] == 2
    assert result["coverage"]["manifest_turn_count"] == 2
    assert result["funding"]["reservations"] == receipt["requests"]["attempts_reserved"]
    assert result["funding"]["results"] == receipt["requests"]["attempts_reserved"]
    assert result["funding"]["paired_one_to_one"] is True
    assert result["funding"]["prefix_binding_ok"] is True
    assert result["funding"]["receipt_attempts_match"] is True
    assert Path(result["card_file"]["path"]).is_file()

    # 证据 schema 强区分：live 缺 run_binding / run binding 被篡改 / local_mock 带 run_binding 都拒绝。
    envelope_path = sorted(Path(receipt["paths"]["evidence_dir"]).glob("turn-*.fernet"))[0]
    envelope = evidence_io.read_encrypted_evidence(envelope_path, key=setup.key)
    missing = {key: value for key, value in envelope.items() if key != "run_binding"}
    with pytest.raises(evidence_io.EvidenceIntegrityError):
        evidence_io.validate_turn_evidence(missing, phase="pre_write")
    tampered = json.loads(json.dumps(envelope))
    tampered["run_binding"]["attempt_scope_sha256"] = "0" * 64
    with pytest.raises(evidence_io.EvidenceIntegrityError):
        evidence_io.validate_turn_evidence(tampered, phase="pre_write")
    masquerade = json.loads(json.dumps(envelope))
    masquerade["fixture_kind"] = "local_mock"
    masquerade["schema_version"] = capture.EVIDENCE_SCHEMA_VERSION
    masquerade["bindings"]["fixture_kind"] = "local_mock"
    with pytest.raises(evidence_io.EvidenceIntegrityError):
        evidence_io.validate_turn_evidence(masquerade, phase="pre_write")

    bad_plan = json.loads(json.dumps(case_plan))
    bad_plan["bindings"]["plan_sha256"] = "e" * 64
    with pytest.raises(entry.EntryError) as excinfo:
        entry._recompute_loaded(
            document=setup.document,
            run_entry=setup.run_entry,
            plan=setup.plan,
            cases=setup.dataset.cases,
            annotation=merged,
            case_plan_payload=bad_plan,
            evidence_dir=receipt["paths"]["evidence_dir"],
            key=setup.key,
            ledger_path=fixed_paths.ledger,
        )
    assert excinfo.value.code == "case_plan_invalid"
    bad_control = json.loads(json.dumps(case_plan))
    bad_control["run_binding"]["go_sha256"] = "e" * 64
    with pytest.raises(entry.EntryError) as excinfo:
        entry._recompute_loaded(
            document=setup.document,
            run_entry=setup.run_entry,
            plan=setup.plan,
            cases=setup.dataset.cases,
            annotation=merged,
            case_plan_payload=bad_control,
            evidence_dir=receipt["paths"]["evidence_dir"],
            key=setup.key,
            ledger_path=fixed_paths.ledger,
        )
    assert excinfo.value.code == "case_plan_invalid"


def test_run_first_error_stops_without_retry(
    entry: Any, tmp_path: Path, fixed_paths: SimpleNamespace
) -> None:
    chat = UsageChatBackend(behaviors=(ChatBehavior(kind="invalid_json"),))
    setup = chain_setup(entry, tmp_path, fixed_paths, chat=chat)
    receipt = asyncio.run(_run_chain(setup, entry))
    assert receipt["ok"] is False
    assert receipt["status"] in {"aborted", "blocked"}
    assert receipt["stop_code"]
    assert chat.call_count == 1, "首错停：不得自动重试或继续后续回合"
    assert receipt["requests"]["sent"] <= 1
    assert receipt["cleanup"]["business_db_removed"] is True
    rows = ledger_rows(fixed_paths.ledger)
    mine = [row for row in rows if row.get("run_id") == receipt["run_id"]]
    reservations = [row for row in mine if row.get("event") == "reserved"]
    results = [row for row in mine if row.get("event") == "result"]
    assert len(reservations) == len(results)
    assert {row["reservation_id"] for row in reservations} == {
        row["reservation_id"] for row in results
    }
    assert receipt["case_plan"] is not None
    case_plan = json.loads(Path(receipt["case_plan"]["path"]).read_text(encoding="utf-8"))
    assert case_plan["cases"][1]["turns"][0]["status"] == "not_started"
    assert case_plan["cases"][1]["quality_status"] in {"error", "not_executed"}


def test_capture_failure_attributes_started_turn_as_error(
    entry: Any,
    tmp_path: Path,
    fixed_paths: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D：capture writer 失败时，已发送回合必须是 error，未开始才是 not_started。"""

    class FailingWriter(entry.EvidenceWriter):
        def write_turn(self, evidence: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("synthetic-writer-failure")

    monkeypatch.setattr(entry, "EvidenceWriter", FailingWriter)
    setup = chain_setup(entry, tmp_path, fixed_paths)
    receipt = asyncio.run(_run_chain(setup, entry))
    assert receipt["ok"] is False
    assert receipt["status"] in {"aborted", "blocked"}
    assert receipt["requests"]["sent"] >= 1
    assert receipt["evidence"]["turn_files"] == 0
    assert receipt["case_plan"] is not None, receipt
    assert receipt["case_plan_started_turns"] == 1
    assert receipt["case_plan_failed_turn_code"]
    case_plan = json.loads(Path(receipt["case_plan"]["path"]).read_text(encoding="utf-8"))
    first = case_plan["cases"][0]["turns"][0]
    assert first["status"] == "error"
    assert first["error"]
    assert case_plan["cases"][1]["turns"][0]["status"] == "not_started"
    assert receipt["cleanup"]["plaintext_clean"] is True
    rows = ledger_rows(fixed_paths.ledger)
    mine = [row for row in rows if row.get("run_id") == receipt["run_id"]]
    reservations = [row for row in mine if row.get("event") == "reserved"]
    results = [row for row in mine if row.get("event") == "result"]
    assert len(reservations) == len(results)
    assert {row["reservation_id"] for row in reservations} == {
        row["reservation_id"] for row in results
    }


# --------------------------------------------------------------------------- #
# 发送前拒绝（零发送）
# --------------------------------------------------------------------------- #


def _updated_env(**overrides: str) -> dict[str, str]:
    values = _env_values()
    values.update({key: str(value) for key, value in overrides.items()})
    return values


def test_run_chain_pins_chat_model_when_env_differs(
    entry: Any, tmp_path: Path, fixed_paths: SimpleNamespace
) -> None:
    """B：真实 .env 的旧模型不生效；全链仍以计划/契约的 deepseek-flash 结算。"""
    setup = chain_setup(entry, tmp_path, fixed_paths)
    setup.options = replace(
        setup.options, process_env=_updated_env(MKTKB_MODEL_NAME="deepseek-chat")
    )
    receipt = asyncio.run(_run_chain(setup, entry))
    assert receipt["ok"] is True, receipt
    assert receipt["chat_model"] == "deepseek-flash"
    assert receipt["model_pinned"] is True
    assert receipt["runtime"]["model_pinned"] is True


def test_run_refusals_are_zero_send(
    entry: Any, tmp_path: Path, fixed_paths: SimpleNamespace
) -> None:
    cases: list[tuple[str, dict[str, Any], str]] = [
        ("host", {"env": {"MKTKB_MODEL_BASE_URL": "https://evil.example.com"}}, "env_chat_host_mismatch"),
        ("limit", {"env": {"MKTKB_PROJECT_TOTAL_LIMIT_CNY": "50"}}, "env_total_limit_mismatch"),
        ("go-missing", {"go": "missing"}, "path_missing"),
        ("go-plan", {"go": "plan"}, "go_plan_sha256_mismatch"),
        ("go-expired", {"go": "expired"}, "go_expired"),
        ("go-ledger", {"go": "ledger"}, "go_ledger_binding_mismatch"),
    ]
    for index, (name, mutation, expected) in enumerate(cases):
        root = tmp_path / name
        root.mkdir()
        fixed = SimpleNamespace(
            ledger=fixed_paths.ledger,
            budget=fixed_paths.budget,
            go=root / "P2-LIVE-GO.json",
        )
        # 每个用例重新绑定固定路径：GO 文件放在独立目录，内容可独立改写。
        p2a.P2_GO_PATH = fixed.go
        setup = chain_setup(entry, root, fixed)
        if "env" in mutation:
            setup.options = replace(setup.options, process_env=_updated_env(**mutation["env"]))
        mode = mutation.get("go")
        if mode == "missing":
            fixed.go.unlink()
        elif mode == "plan":
            _write_go(fixed.go, ledger=fixed.ledger, plan=setup.plan, plan_sha="e" * 64)
        elif mode == "expired":
            _write_go(fixed.go, ledger=fixed.ledger, plan=setup.plan, now=NOW - timedelta(days=10))
        elif mode == "ledger":
            _write_go(fixed.go, ledger=fixed.ledger, plan=setup.plan, ledger_sha="f" * 64)
        receipt = asyncio.run(_run_chain(setup, entry))
        assert receipt["status"] == "refused", (name, receipt)
        assert receipt["error_code"] == expected, (name, receipt)
        assert receipt["ok"] is False
        assert setup.chat.call_count == 0, name
        assert not setup.out_dir.exists(), name
        assert receipt["seal"]["sealed"] is False


def test_purge_plaintext_derivatives_removes_business_derivatives(
    entry: Any, tmp_path: Path
) -> None:
    """C：封存前删除 index DB/storage/p2-run/残留明文文件，并记录 sha256 与扫描结果。"""
    sentinel = "P2H2_CLEANUP_PLAINTEXT_SENTINEL_9f2c4e"
    case = synthetic_cases()[0]
    dataset = SimpleNamespace(cases=(case,), labels={})
    out_dir = tmp_path / "product"
    (out_dir / "data" / "storage").mkdir(parents=True)
    (out_dir / "data" / "rag-index.sqlite3").write_bytes(("db " + sentinel).encode())
    (out_dir / "data" / "rag-index.sqlite3-wal").write_bytes(("wal " + sentinel).encode())
    (out_dir / "data" / "storage" / "upload.bin").write_bytes(("upload " + sentinel).encode())
    (out_dir / "p2-run").mkdir()
    (out_dir / "p2-run" / "summary.json").write_text(
        json.dumps({"note": sentinel}), encoding="utf-8"
    )
    (out_dir / "other").mkdir()
    (out_dir / "other" / "notes.txt").write_text(sentinel, encoding="utf-8")
    (out_dir / "controlled").mkdir()
    (out_dir / "controlled" / "case-plan.json").write_text(
        json.dumps({"safe": "aggregate"}), encoding="utf-8"
    )

    cleanup = entry._purge_plaintext_derivatives(
        out_dir, dataset, extra_needles=(sentinel,)
    )
    assert cleanup["plaintext_clean"] is True, cleanup
    assert cleanup["data_dir_removed"] is True
    assert cleanup["run_dir_removed"] is True
    assert cleanup["plaintext_scan"]["clean"] is True
    assert cleanup["plaintext_scan"]["hit_count"] == 0
    assert not (out_dir / "data").exists()
    assert not (out_dir / "p2-run").exists()
    removed = {item["path"] for item in cleanup["removed_paths"]}
    assert "data/rag-index.sqlite3" in removed
    assert "data/storage/upload.bin" in removed
    assert "p2-run/summary.json" in removed
    assert "other/notes.txt" in removed
    assert all(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in cleanup["removed_paths"])
    assert all(
        item["sha256_before_removal"] == item["sha256"]
        for item in cleanup["removed_paths"]
    )
    assert cleanup["removed_count"] == len(cleanup["removed_paths"])
    assert cleanup["retained_paths"] == ["controlled/case-plan.json"]
    assert sentinel.encode() not in (out_dir / "controlled" / "case-plan.json").read_bytes()


def test_purge_refuses_plaintext_in_required_case_plan(entry: Any, tmp_path: Path) -> None:
    """C：必要回执若命中明文，fail closed（不删回执、不声称已清理）。"""
    sentinel = "P2H2_CLEANUP_REQUIRED_SENTINEL_1a2b"
    dataset = SimpleNamespace(cases=(synthetic_cases()[0],), labels={})
    out_dir = tmp_path / "product2"
    (out_dir / "controlled").mkdir(parents=True)
    (out_dir / "controlled" / "case-plan.json").write_text(sentinel, encoding="utf-8")
    cleanup = entry._purge_plaintext_derivatives(
        out_dir, dataset, extra_needles=(sentinel,)
    )
    assert cleanup["plaintext_clean"] is False
    assert "plaintext_residual_required" in cleanup["cleanup_errors"]
    assert (out_dir / "controlled" / "case-plan.json").is_file()


def test_path_and_key_refusals(entry: Any, tmp_path: Path) -> None:
    key = tmp_path / "key"
    key.write_bytes(Fernet.generate_key())
    with pytest.raises(entry.EntryError) as excinfo:
        entry.check_target_paths(
            entry.PathOptions(
                out_dir=ROOT / "backend" / "synthetic-out",
                evidence_root=tmp_path / "ev",
                seal_root=tmp_path / "seal",
                evidence_key_file=key,
            )
        )
    assert excinfo.value.code == "path_inside_forbidden_root"

    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "x").write_text("x", encoding="utf-8")
    with pytest.raises(entry.EntryError) as excinfo:
        entry.check_target_paths(
            entry.PathOptions(
                out_dir=tmp_path / "out-x",
                evidence_root=nonempty,
                seal_root=tmp_path / "seal-x",
                evidence_key_file=key,
            )
        )
    assert excinfo.value.code == "output_not_empty"

    bad_key = tmp_path / "bad-key"
    bad_key.write_bytes(b"short")
    with pytest.raises(entry.EntryError) as excinfo:
        entry.check_target_paths(
            entry.PathOptions(
                out_dir=tmp_path / "out-y",
                evidence_root=tmp_path / "ev-y",
                seal_root=tmp_path / "seal-y",
                evidence_key_file=bad_key,
            )
        )
    assert excinfo.value.code == "evidence_key_invalid"

    with pytest.raises(entry.EntryError) as excinfo:
        entry._validate_fixed_paths(str(tmp_path / "other-go.json"), None, None)
    assert excinfo.value.code == "fixed_path_mismatch"


# --------------------------------------------------------------------------- #
# 授权 .env / 秘密哨兵
# --------------------------------------------------------------------------- #


def _write_env(path: Path, values: dict[str, str]) -> Path:
    path.write_text(
        "\n".join(key + "=" + value for key, value in values.items()) + "\n", encoding="utf-8"
    )
    return path


def test_authorized_env_real_shape_only_reads_whitelisted_credentials(
    entry: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A：真实 .env 形状（产品键 + 旧模型 + 无 holdout/总上限）也能只读凭据。"""
    env_path = tmp_path / ".env"
    monkeypatch.setattr(entry, "AUTHORIZED_ENV_PATH", env_path)
    _write_env(env_path, REAL_ENV_SHAPE)
    values = entry.read_authorized_env(env_path)
    assert "MKTKB_PROJECT_TOTAL_LIMIT_CNY" not in values
    assert "MKTKB_P2_HOLDOUT_ROOT" not in values
    assert "MKTKB_P2_HOLDOUT_KEY_FILE" not in values
    assert "MKTKB_CSRF_SECRET" not in values
    assert "MKTKB_ADMIN_PASSWORD" not in values
    assert values["MKTKB_MODEL_NAME"] == "deepseek-chat"  # .env 旧值仍可读，但注入时被钉住
    assert values["MKTKB_MODEL_API_KEY"] == CHAT_SECRET
    with entry.applied_env(values):
        live_env = entry.p2_live.load_live_env(None)
    assert live_env.chat_model == "deepseek-flash"
    assert live_env.dashscope_base_url == "https://dashscope.aliyuncs.com"
    assert live_env.ocr_region == "ap-guangzhou"
    for secret in SECRETS:
        assert secret not in repr(live_env)

    missing = dict(REAL_ENV_SHAPE)
    missing.pop("MKTKB_OCR_SECRET_KEY")
    _write_env(env_path, missing)
    with pytest.raises(entry.EntryError) as excinfo:
        entry.read_authorized_env(env_path)
    assert excinfo.value.code == "env_required_missing"
    assert "MKTKB_OCR_SECRET_KEY" in excinfo.value.detail
    for secret in SECRETS:
        assert secret not in str(excinfo.value)

    _write_env(env_path, REAL_ENV_SHAPE | {"UNKNOWN_NAME": "x"})
    with pytest.raises(entry.EntryError) as excinfo:
        entry.read_authorized_env(env_path)
    assert excinfo.value.code == "env_name_not_allowed"

    # 运行键即便出现在 .env 也被剥离：来源只能是显式参数。
    _write_env(
        env_path,
        REAL_ENV_SHAPE
        | {
            "MKTKB_PROJECT_TOTAL_LIMIT_CNY": "50",
            "MKTKB_P2_HOLDOUT_ROOT": "D:/wrong",
            "MKTKB_P2_HOLDOUT_KEY_FILE": "D:/wrong/key",
        },
    )
    values = entry.read_authorized_env(env_path)
    assert "MKTKB_PROJECT_TOTAL_LIMIT_CNY" not in values
    assert "MKTKB_P2_HOLDOUT_ROOT" not in values
    assert "MKTKB_P2_HOLDOUT_KEY_FILE" not in values

    other = tmp_path / "not-authorized.env"
    _write_env(other, REAL_ENV_SHAPE)
    with pytest.raises(entry.EntryError) as excinfo:
        entry.read_authorized_env(other)
    assert excinfo.value.code == "env_file_not_authorized"

    opts = runtime_options(entry, tmp_path)
    captured = []
    original = entry._emit
    entry._emit = lambda payload: captured.append(json.dumps(payload, ensure_ascii=False))
    try:
        code = entry.main(["preflight", "--env-file", str(other), "--run-binding", str(tmp_path / "none.json"), "--run-index", "0", "--out-dir", str(tmp_path / "o"), "--evidence-root", str(tmp_path / "e"), "--seal-root", str(tmp_path / "s"), "--evidence-key-file", str(tmp_path / "k"), "--holdout-root", str(opts.holdout_root), "--holdout-key-file", str(opts.holdout_key_file), "--project-total-limit-cny", "40"])
    finally:
        entry._emit = original
    assert code == entry.EXIT_REFUSED
    assert "env_file_not_authorized" in captured[-1]
    for secret in SECRETS:
        assert secret not in captured[-1]


def test_runtime_options_explicit_boundary(entry: Any, tmp_path: Path) -> None:
    """A：holdout 根/钥/总上限只认显式参数；缺失/位置/结构/数值全部固定码拒绝。"""
    opts = runtime_options(entry, tmp_path)
    checked = entry.check_runtime_options(opts)
    values = entry.runtime_env_values(checked)
    assert values["MKTKB_P2_HOLDOUT_ROOT"] == str(checked.holdout_root)
    assert values["MKTKB_P2_HOLDOUT_KEY_FILE"] == str(checked.holdout_key_file)
    assert values["MKTKB_PROJECT_TOTAL_LIMIT_CNY"] == "40.0"

    with pytest.raises(entry.EntryError) as excinfo:
        entry.check_runtime_options(None)
    assert excinfo.value.code == "runtime_options_missing"

    with pytest.raises(entry.EntryError) as excinfo:
        entry.check_runtime_options(
            entry.RuntimeOptions(tmp_path / "missing-root", opts.holdout_key_file, 40.0)
        )
    assert excinfo.value.code == "holdout_root_missing"

    with pytest.raises(entry.EntryError) as excinfo:
        entry.check_runtime_options(
            entry.RuntimeOptions(entry.PROJECT_ROOT, opts.holdout_key_file, 40.0)
        )
    assert excinfo.value.code == "holdout_root_inside_repo"

    bad_key = tmp_path / "bad-holdout.key"
    bad_key.write_bytes(b"short")
    with pytest.raises(entry.EntryError) as excinfo:
        entry.check_runtime_options(entry.RuntimeOptions(opts.holdout_root, bad_key, 40.0))
    assert excinfo.value.code == "holdout_key_invalid"

    with pytest.raises(entry.EntryError) as excinfo:
        entry.check_runtime_options(
            entry.RuntimeOptions(opts.holdout_root, entry.PROJECT_ROOT / "README.md", 40.0)
        )
    assert excinfo.value.code == "holdout_key_inside_repo"

    with pytest.raises(entry.EntryError) as excinfo:
        entry.check_runtime_options(entry.RuntimeOptions(opts.holdout_root, opts.holdout_key_file, None))
    assert excinfo.value.code == "project_total_limit_missing"

    with pytest.raises(entry.EntryError) as excinfo:
        entry.check_runtime_options(entry.RuntimeOptions(opts.holdout_root, opts.holdout_key_file, 50.0))
    assert excinfo.value.code == "project_total_limit_mismatch"

    with pytest.raises(entry.EntryError) as excinfo:
        entry.check_runtime_options(entry.RuntimeOptions(opts.holdout_root, opts.holdout_key_file, float("nan")))
    assert excinfo.value.code == "project_total_limit_mismatch"

    # 显式运行值覆盖 .env 同名键（merge 语义）。
    merged = entry.merge_runtime_env(
        {
            "MKTKB_MODEL_API_KEY": CHAT_SECRET,
            "MKTKB_PROJECT_TOTAL_LIMIT_CNY": "50",
            "MKTKB_P2_HOLDOUT_ROOT": "D:/wrong",
        },
        checked,
    )
    assert merged["MKTKB_PROJECT_TOTAL_LIMIT_CNY"] == "40.0"
    assert merged["MKTKB_P2_HOLDOUT_ROOT"] == str(checked.holdout_root)


def test_cli_plan_private_runtime_args_and_optional_env_file(
    entry: Any, tmp_path: Path
) -> None:
    base = [
        "plan-private",
        "--out-dir",
        str(tmp_path / "plan-out"),
        "--created-utc",
        "2026-11-13T00:00:00+00:00",
        "--annotation",
        str(tmp_path / "annotation.fernet"),
        "--review",
        str(tmp_path / "review.fernet"),
        "--scenario-key-file",
        str(tmp_path / "scenario.key"),
        "--addendum",
        str(tmp_path / "addendum.fernet"),
    ]
    captured = []
    original = entry._emit
    entry._emit = lambda payload: captured.append(json.dumps(payload, ensure_ascii=False))
    try:
        # 缺显式运行参数：CLI usage 拒绝（exit 3）。
        code = entry.main(base)
        assert code == entry.EXIT_USAGE
        assert "usage_invalid" in captured[-1]
        # 总上限错误：在读取任何私有输入之前拒绝（exit 2）。
        opts = runtime_options(entry, tmp_path)
        code = entry.main(
            base
            + [
                "--holdout-root",
                str(opts.holdout_root),
                "--holdout-key-file",
                str(opts.holdout_key_file),
                "--project-total-limit-cny",
                "50",
            ]
        )
        assert code == entry.EXIT_REFUSED
        assert "project_total_limit_mismatch" in captured[-1]
        # env-file 对 plan-private 可选：没有 --env-file 也不会 usage 拒绝，会走到输入校验。
        code = entry.main(
            base
            + [
                "--holdout-root",
                str(opts.holdout_root),
                "--holdout-key-file",
                str(opts.holdout_key_file),
                "--project-total-limit-cny",
                "40",
            ]
        )
        assert code == entry.EXIT_REFUSED
        assert "usage_invalid" not in captured[-1]
        assert any(
            token in captured[-1]
            for token in ("input_file_missing", "input_path_rejected", "input_path_invalid")
        )
    finally:
        entry._emit = original


def test_model_pinned_to_plan_and_explicit_config_conflict_rejected(entry: Any) -> None:
    """B：.env 的旧模型值不生效；计划/配置显式冲突仍固定码拒绝。"""
    values = _updated_env(MKTKB_MODEL_NAME="gpt-4o")
    with entry.applied_env(values):
        live_env = entry.p2_live.load_live_env(None)
        assert live_env.chat_model == "deepseek-flash"
        with pytest.raises(entry.p2_live.P2LiveConfigError) as excinfo:
            entry.p2_live.load_live_env(None, overrides={"chat_model": "gpt-4o"})
        assert excinfo.value.code == "live_chat_model_not_authorized"
    config = {
        "providers": {
            "chat": {"model": "gpt-4o", "host": "api.deepseek.com"},
            "embedding": {"host": "dashscope.aliyuncs.com"},
            "ocr_region": "ap-guangzhou",
        }
    }
    with pytest.raises(entry.EntryError) as excinfo:
        entry._verify_env_against_config(live_env, config)
    assert excinfo.value.code == "env_chat_model_mismatch"


def test_repr_does_not_leak_secrets(entry: Any, tmp_path: Path) -> None:
    key = Fernet.generate_key()
    bindings = {name: "x" for name in capture.BINDING_KEYS}
    bindings["fixture_kind"] = capture.LIVE_FIXTURE_KIND
    config = capture.EvidenceCaptureConfig(
        root_dir=tmp_path / "evidence",
        bindings=bindings,
        fixture_kind=capture.LIVE_FIXTURE_KIND,
        writer=None,
        run_binding=None,
    )
    assert "x" * 3 not in repr(config)
    with pytest.raises(capture.EvidenceCaptureConfigError):
        config.validated_run_binding()
    assert str(key) not in repr(
        evidence_io.EvidenceWriter(
            root_dir=tmp_path / "evidence2",
            key=key,
            bindings={**bindings, "index_revision": "1"},
            fixture_kind=capture.LIVE_FIXTURE_KIND,
        )
    )


# --------------------------------------------------------------------------- #
# preflight（check-only）/ recompute 编排 / 账本审计
# --------------------------------------------------------------------------- #


def _write_env_file(entry: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    env_path = tmp_path / ".env"
    monkeypatch.setattr(entry, "AUTHORIZED_ENV_PATH", env_path)
    _write_env(env_path, _env_values())
    return env_path


def test_preflight_check_only_reads_go_budget_ledger(
    entry: Any, tmp_path: Path, fixed_paths: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = make_bundle(entry, tmp_path / "bundle")
    payload = entry.plan_private(
        bundle,
        entry.PlanOptions(out_dir=tmp_path / "private", created_utc="2026-11-13T00:00:00+00:00"),
    )
    binding_path = Path(payload["binding_file"])
    document = entry.load_run_binding(binding_path)
    run_entry = document["runs"][0]
    plan = c.P2RunPlan.from_dict(entry._read_json_mapping(Path(run_entry["plan_file"]), "plan"))
    _write_go(fixed_paths.go, ledger=fixed_paths.ledger, plan=plan)
    env_path = _write_env_file(entry, tmp_path, monkeypatch)
    key = tmp_path / "evidence.key"
    key.write_bytes(Fernet.generate_key())
    paths = entry.PathOptions(
        out_dir=tmp_path / "out-prep",
        evidence_root=tmp_path / "ev-prep",
        seal_root=tmp_path / "seal-prep",
        evidence_key_file=key,
    )
    result = entry.preflight(
        env_file=env_path,
        binding_path=binding_path,
        run_index=0,
        paths=paths,
        runtime=runtime_options(entry, tmp_path),
        now=NOW,
    )
    assert result["ok"] is True, result
    assert result["zero_paid_probes"] is True
    assert result["go"]["plan_sha_match"] is True
    assert result["authorization"]["production_ready"] is True
    assert result["ledger"]["reservation_count"] == 0
    assert result["ledger"]["historical_prefix_sha256"]
    assert result["env"]["chat_model"] == "deepseek-flash"
    assert result["env"]["model_pinned"] is True
    assert result["env"]["total_limit_source"] == "explicit_cli"
    assert all(check["ok"] for check in result["checks"])
    for secret in SECRETS:
        assert secret not in json.dumps(result, ensure_ascii=False)

    fixed_paths.go.unlink()
    refused = entry.preflight(
        env_file=env_path,
        binding_path=binding_path,
        run_index=0,
        paths=paths,
        runtime=runtime_options(entry, tmp_path),
        now=NOW,
    )
    assert refused["ok"] is False
    assert refused["error_code"] == "preflight_failed"
    assert any(not check["ok"] for check in refused["checks"])


def test_recompute_orchestration_reaches_evidence_boundary(
    entry: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = make_bundle(entry, tmp_path / "bundle")
    payload = entry.plan_private(
        bundle,
        entry.PlanOptions(out_dir=tmp_path / "private", created_utc="2026-11-13T00:00:00+00:00"),
    )
    env_path = _write_env_file(entry, tmp_path, monkeypatch)
    monkeypatch.setattr(
        entry, "load_private_bundle", lambda values, paths, **kwargs: bundle
    )
    key = tmp_path / "evidence.key"
    key.write_bytes(Fernet.generate_key())
    with pytest.raises(entry.EntryError) as excinfo:
        entry.recompute(
            env_file=env_path,
            binding_path=Path(payload["binding_file"]),
            run_index=0,
            evidence_dir=tmp_path / "missing-evidence",
            evidence_key_file=key,
            case_plan_path=tmp_path / "missing-case-plan.json",
            runtime=runtime_options(entry, tmp_path),
        )
    assert excinfo.value.code == "evidence_dir_missing"

    empty = tmp_path / "empty-evidence"
    empty.mkdir()
    with pytest.raises(entry.EntryError) as excinfo:
        entry.recompute(
            env_file=env_path,
            binding_path=Path(payload["binding_file"]),
            run_index=0,
            evidence_dir=empty,
            evidence_key_file=key,
            case_plan_path=tmp_path / "missing-case-plan.json",
            runtime=runtime_options(entry, tmp_path),
        )
    assert excinfo.value.code == "case_plan_unreadable"


def test_ledger_audit_detects_unpaired_and_orphan(entry: Any, fixed_paths: SimpleNamespace) -> None:
    rows = [
        {"event": "historical_import", "accounted_cny": 2.0},
        {"event": "reserved", "run_id": "run-x", "reservation_id": "a", "reserve_cny": 0.1},
        {"event": "reserved", "run_id": "run-x", "reservation_id": "b", "reserve_cny": 0.2},
        {"event": "result", "run_id": "run-x", "reservation_id": "a", "conservative_charge_cny": 0.05, "status": "succeeded"},
        {"event": "result", "run_id": "run-x", "reservation_id": "c", "conservative_charge_cny": 0.03, "status": "failed"},
    ]
    fixed_paths.ledger.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    audit = entry._audit_ledger(fixed_paths.ledger, "run-x", None)
    assert audit["reservations"] == 2
    assert audit["results"] == 2
    assert audit["unpaired_reservations"] == ["b"]
    assert audit["orphan_results"] == ["c"]
    assert audit["paired_one_to_one"] is False
    assert audit["reserved_cny"] == pytest.approx(0.3)
    assert audit["settled_cny"] == pytest.approx(0.08)
