"""v3 Mock 端到端干跑（新增文件；**零真实调用**，只证明链路可跑，不代表质量）。

职责
----
1. 用 ``MockChatBackend``（产品侧同一 ``httpx.MockTransport`` 后端，不出网）把 v3 的 4 个 run
   各跑一遍：v3 数据集加载 → 逐 run ``business_date`` 注入 → 30 题/36 回合 → 出卡。
2. 每 run 产出：驱动层聚合卡（``/v0.1`` 形状，仓库内）、四轴硬证据卡（``v0.2``，仓库内）、
   运行回执（计数/码/摘要，仓库内）。逐题 case-plan 与逐回合密文证据含题号，**只落仓外**。
3. C20/C22 的索引层冒烟：文档标题与门店过滤在**产品自己的解析器**上是否可解析（不调 embedding）。
4. 计分侧 source-map 走 ``p2_holdout_v3_scoring.dispatched_scoring_map``（版本分发）；
   作用域外 ``p2_score_run`` 行为不变。

边界
----
- 不读题面/答案到产物：所有仓内产物只有计数/固定码/64 位摘要；逐题/逐回合材料留在仓外目录。
- 不改任何既有模块；不改 v2/v3 密文与语料；不 stage/commit。
- 网络：进程内删除代理环境变量 + socket/httpx 双守卫（只放行回环），并做**不经本机代理**的
  正对照；本轮结束时 ``external`` 尝试必须为 0。

用法::

    python tools/p2_v3_mock_dryrun.py --out docs/reports/OBS-EVAL/P2/H2V3/dryrun \
        --evidence-root D:\\mktkb-p2-dryrun --root D:\\mktkb-p2-holdout\\v3 \
        --key-file D:\\mktkb-p2-holdout\\keys\\v3.key
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import socket
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = PROJECT_ROOT / 'backend' / 'src'
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from cryptography.fernet import Fernet  # noqa: E402

from mktkb.evaluation import p2_holdout_run_date as run_date  # noqa: E402
from mktkb.evaluation import p2_holdout_scenarios_v3 as contract_v3  # noqa: E402
from mktkb.evaluation import p2_holdout_v3_scoring as wiring  # noqa: E402
from mktkb.evaluation.p2_authorization import preflight_p2  # noqa: E402
from mktkb.evaluation.p2_contracts import (  # noqa: E402
    P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
    P2LedgerSnapshot,
)
from mktkb.evaluation.p2_dataset import (  # noqa: E402
    HOLDOUT_KEY_FILE_ENV,
    HOLDOUT_ROOT_ENV,
    load_p2_dataset,
)
from mktkb.evaluation.p2_diagnostics import validate_scorecard  # noqa: E402
from mktkb.evaluation.p2_evidence_capture import (  # noqa: E402
    BINDING_KEYS,
    EVIDENCE_SCHEMA_VERSION_V03,
    EvidenceCaptureConfig,
)
from mktkb.evaluation.p2_evidence_io import EvidenceWriter, read_encrypted_evidence  # noqa: E402
from mktkb.evaluation.p2_hard_evidence import (  # noqa: E402
    CASEPLAN_SCHEMA_VERSION,
    prepare_annotation,
    recompute_hard_evidence,
    validate_case_plan,
    validate_hard_evidence_scorecard,
)
from mktkb.evaluation.p2_holdout_plan import summarize as summarize_plan  # noqa: E402
from mktkb.evaluation.p2_runner import build_dry_run_authorization, run_p2  # noqa: E402
from mktkb.evaluation.p2_scoring import load_p2_gate_config  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    MockChatBackend,
    ProductEvalAdapter,
    case_questions,
)

DRYRUN_SCHEMA_VERSION = 'p2-h2v3-mock-dryrun/v0.1'
RUN_RECEIPT_SCHEMA_VERSION = 'p2-h2v3-mock-dryrun-run-receipt/v0.1'
INDEX_SMOKE_SCHEMA_VERSION = 'p2-h2v3-index-smoke/v0.1'
NOW = datetime(2026, 11, 15, 4, 0, tzinfo=timezone.utc)
CREATED_UTC = '2026-11-15T04:00:00+00:00'
NONCE = 'dryrun-v3-' + '5a' * 8
PROXY_ENV_KEYS = ('HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy',
                  'NODE_USE_ENV_PROXY', 'node_use_env_proxy')
DRYRUN_CONFIG_DIGEST = hashlib.sha256(b'p2-h2v3-mock-dryrun:local_mock:no-provider').hexdigest()
PREREG_PATH = (PROJECT_ROOT / 'docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-author/pre-registration.json')
PREREG_SHA256 = '23cb3c08a8098557f27e8ad3bf433ce8a69111afcfca4aa587073ed9d60d4bce'
CASE_LABEL_RE = __import__('re').compile(r'(C\d{2})')
"""题号（公开：预登记表本身只含题号/run/分层/轴/原因，不含题面）。"""
C20_C22_RUNS = (1, 3)
"""C22 在 run 1（``base_b0_plus_v01``），C20 在 run 3（``post_v05_without_v01``）。"""


# --------------------------------------------------------------------------- #
# 网络守卫（零真实调用是硬门）
# --------------------------------------------------------------------------- #


class NetworkAttempts:
    def __init__(self) -> None:
        self.external: list[str] = []
        self.local: list[str] = []

    def add(self, label: str, host: Any) -> None:
        (self.local if _is_loopback(host) else self.external).append(label)

    def snapshot(self) -> dict[str, Any]:
        return {'external': list(self.external), 'local': list(self.local)}


def _is_loopback(host: Any) -> bool:
    if isinstance(host, (tuple, list)) and host:
        host = host[0]
    text = str(host or '').strip().lower()
    if text in ('localhost', '::1', '0.0.0.0'):
        return True
    if text.startswith('127.'):
        return True
    return False


def install_guard() -> NetworkAttempts:
    """拦掉一切外部出站（回环放行并记录）；与仓库 netguard 同口径的 primitives。"""
    from mktkb.evaluation.product_adapter import MockChatBackend as _Mock

    del _Mock  # 只用于确认产品侧 Mock 后端已导入（同进程）
    import httpx

    attempts = NetworkAttempts()
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address, *args, **kwargs):  # noqa: ANN001
        attempts.add(f'socket.connect {address!r}', address)
        if _is_loopback(address):
            return real_connect(self, address, *args, **kwargs)
        raise RuntimeError(f'blocked connect {address!r}')

    def guarded_connect_ex(self, address, *args, **kwargs):  # noqa: ANN001
        attempts.add(f'socket.connect_ex {address!r}', address)
        if _is_loopback(address):
            return real_connect_ex(self, address, *args, **kwargs)
        raise RuntimeError(f'blocked connect_ex {address!r}')

    def guarded_create(address, *args, **kwargs):  # noqa: ANN001
        attempts.add(f'socket.create_connection {address!r}', address)
        if _is_loopback(address):
            return real_create(address, *args, **kwargs)
        raise RuntimeError(f'blocked create_connection {address!r}')

    def guarded_getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
        attempts.add(f'socket.getaddrinfo {host!r}', (host if isinstance(host, str) else ''))
        if _is_loopback(host):
            return real_getaddrinfo(host, *args, **kwargs)
        raise RuntimeError(f'blocked getaddrinfo {host!r}')

    def guarded_handle_request(self, request):  # noqa: ANN001
        attempts.add(f'httpx {request.url}', (str(request.url.host),))
        raise RuntimeError(f'blocked http {request.url}')

    async def guarded_handle_async_request(self, request):  # noqa: ANN001
        attempts.add(f'httpx-async {request.url}', (str(request.url.host),))
        raise RuntimeError(f'blocked http {request.url}')

    socket.socket.connect = guarded_connect  # type: ignore[assignment]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[assignment]
    socket.create_connection = guarded_create  # type: ignore[assignment]
    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
    httpx.HTTPTransport.handle_request = guarded_handle_request  # type: ignore[assignment]
    httpx.AsyncHTTPTransport.handle_async_request = guarded_handle_async_request  # type: ignore[assignment]
    return attempts


def positive_control() -> dict[str, Any]:
    """正对照：DNS/直连/urllib/httpx 四类探针必须被拦，且**不得借道本机代理**。"""
    import httpx

    attempts = NetworkAttempts()
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address, *args, **kwargs):  # noqa: ANN001
        attempts.add(f'socket.connect {address!r}', address)
        if _is_loopback(address):
            return real_connect(self, address, *args, **kwargs)
        raise RuntimeError('blocked connect')

    def guarded_connect_ex(self, address, *args, **kwargs):  # noqa: ANN001
        attempts.add(f'socket.connect_ex {address!r}', address)
        raise RuntimeError('blocked connect_ex')

    def guarded_create(address, *args, **kwargs):  # noqa: ANN001
        attempts.add(f'socket.create_connection {address!r}', address)
        if _is_loopback(address):
            return real_create(address, *args, **kwargs)
        raise RuntimeError('blocked create_connection')

    def guarded_getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
        attempts.add(f'socket.getaddrinfo {host!r}', (host if isinstance(host, str) else ''))
        if _is_loopback(host):
            return real_getaddrinfo(host, *args, **kwargs)
        raise RuntimeError('blocked getaddrinfo')

    def guarded_handle(self, request):  # noqa: ANN001
        attempts.add(f'httpx {request.url}', (str(request.url.host),))
        raise RuntimeError('blocked http')

    probes: list[str] = []
    saved = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection,
             socket.getaddrinfo, httpx.HTTPTransport.handle_request)
    try:
        socket.socket.connect = guarded_connect  # type: ignore[assignment]
        socket.socket.connect_ex = guarded_connect_ex  # type: ignore[assignment]
        socket.create_connection = guarded_create  # type: ignore[assignment]
        socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
        httpx.HTTPTransport.handle_request = guarded_handle  # type: ignore[assignment]
        for name, probe in (
            ('dns', lambda: socket.getaddrinfo('example.invalid', 80)),
            ('direct', lambda: socket.socket().connect(('192.0.2.1', 80))),
            ('urllib', lambda: urllib.request.build_opener(urllib.request.ProxyHandler({}))
                .open('http://example.invalid/', timeout=2)),
            ('httpx', lambda: httpx.get('http://example.invalid/', timeout=2)),
        ):
            try:
                probe()
            except Exception:  # noqa: BLE001 - 被拦即达标
                probes.append(name + ':blocked')
            else:  # pragma: no cover - 守卫失效才会到这里
                probes.append(name + ':escaped')
    finally:
        (socket.socket.connect, socket.socket.connect_ex, socket.create_connection,
         socket.getaddrinfo, httpx.HTTPTransport.handle_request) = saved
    snapshot = attempts.snapshot()
    return {
        'probes': probes,
        'blocked': all(item.endswith(':blocked') for item in probes),
        'external_attempts': len(snapshot['external']),
        'local_attempts': len(snapshot['local']),
        'proxy_env_removed': not any(os.environ.get(key) for key in PROXY_ENV_KEYS),
        'ambient_registry_proxy_present': bool(urllib.request.getproxies()),
        'external': snapshot['external'],
    }


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    path.write_text(text, encoding='utf-8')
    raw = text.encode('utf-8')
    return {'path': str(path), 'sha256': sha256_bytes(raw), 'bytes': len(raw)}


def synthetic_snapshot(plan: Any) -> P2LedgerSnapshot:
    """空账快照：只用于构造 dry-run 授权，不参与任何金额判定。"""
    return P2LedgerSnapshot(
        schema_version=P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
        ledger_path='in-memory:dry-run',
        ledger_sha256='0' * 64,
        historical_prefix_sha256='1' * 64,
        budget_sha256='2' * 64,
        total_limit_cny=float(plan.project_total_limit_cny),
        historical_accounted_cny=0.0,
        accounted_cny=0.0,
        reservation_count=0,
        result_count=0,
        stage_allocations_cny={'S2-DEV': 0.0, 'P1-RETRIEVAL': 0.0, 'P2-LIVE': plan.stage_limit_cny},
        p2_stage_accounted_cny=0.0,
        p2_center_accounted_cny={center: 0.0 for center in plan.cost_centers_cny},
        source='in-memory',
    )


def dry_run_authorization(plan: Any) -> Any:
    preflight = preflight_p2(plan, synthetic_snapshot(plan))
    if not preflight.ok:  # pragma: no cover - 计划合法性由 contract 保证
        raise RuntimeError(f'preflight 未通过: {sorted(preflight.reasons)}')
    return build_dry_run_authorization(plan, preflight, now=NOW, nonce=NONCE)


def annotation_payload(path: Path, key_file: Path) -> tuple[dict[str, Any], str]:
    """解封 v0.2 标注（与 loader 同一份密文/key；只在内存使用）。"""
    raw = path.read_bytes()
    key = key_file.read_bytes().strip()
    return json.loads(Fernet(key).decrypt(raw)), sha256_bytes(raw)


def turn_counter_map(dataset: Any) -> dict[int, tuple[str, int]]:
    """全局回合序号（0 基，适配器按执行顺序分配）-> (case_id, 轮次)。"""
    rows: dict[int, tuple[str, int]] = {}
    cursor = 0
    for case in dataset.cases:
        for turn in range(1, len(case_questions(case)) + 1):
            rows[cursor] = (case.case_id, turn)
            cursor += 1
    return rows


def build_chat(mode: str) -> tuple[Any, str]:
    """离线 chat 替身。

    - ``stock``：产品自带 ``MockChatBackend``（回显首条证据的前 3 个字段）；
    - ``echo-all``：同一后端、只把"回显范围"扩到**全部证据行的全部字段**并引用全部来源 id，
      让产品的事实准入有足够原文可用。两种模式都**不生成任何新内容**（只是把检索到的原文
      机械拼接），也都不出网。
    """
    chat = MockChatBackend()
    if mode == 'stock':
        return chat, mode

    def echo_all(body: Mapping[str, Any], behavior: Any) -> str:  # noqa: ANN001
        evidence = [item for item in body.get('evidence') or () if isinstance(item, Mapping)]
        parts: list[str] = []
        ids: list[str] = []
        for item in evidence:
            fields = item.get('fields')
            if isinstance(fields, Mapping) and fields:
                parts.extend(f'{key}：{value}' for key, value in fields.items())
            elif item.get('text'):
                parts.append(str(item['text']))
            sid = str(item.get('source_id') or '').strip()
            if sid and sid not in ids:
                ids.append(sid)
        text = '；'.join(part for part in parts if part).strip()
        return json.dumps({'answer': text[:4000] or '资料中未记录相关信息。',
                           'source_ids': ids}, ensure_ascii=False)

    chat._answer_json = echo_all  # type: ignore[method-assign]
    return chat, mode


# --------------------------------------------------------------------------- #
# 单 run
# --------------------------------------------------------------------------- #


async def run_one(
    *,
    contract: Any,
    run_index: int,
    annotation: Any,
    dataset_anchor: str,
    out_root: Path,
    evidence_root: Path,
    nonce_tag: str,
    chat_mode: str = 'stock',
) -> dict[str, Any]:
    binding = run_date.bind_run(run_index, dataset_anchor=dataset_anchor)
    name = binding.scenario_id
    if name != contract.scenario_ids[run_index]:  # pragma: no cover - 表与合同不一致才会到这
        raise RuntimeError(f'run{run_index} 的 scenario 与 contract 不一致')
    subset = contract.subset(name)
    plan = contract.build_plan(name, plan_id=f'P2-H2V3-DRYRUN-R{run_index}',
                               created_utc=CREATED_UTC, max_requests=1100)
    ingest = contract.ingest_plan(name)
    run_id = f'p2run-h2v3-dryrun-r{run_index}-{nonce_tag}'
    authorization = dry_run_authorization(plan)
    gate_config = load_p2_gate_config()

    run_dir = out_root / 'runtime' / f'r{run_index}'
    ev_dir = evidence_root / f'r{run_index}'
    for path in (run_dir, ev_dir):
        if path.exists():
            shutil.rmtree(path)
    ev_dir.mkdir(parents=True, exist_ok=True)
    evidence_key = Fernet.generate_key()
    bindings = {key: f'dryrun-{key}' for key in BINDING_KEYS}
    bindings.update(fixture_kind='local_mock', run_id=run_id, plan_id=plan.plan_id,
                    plan_sha256=plan.plan_sha256, scenario_id=name,
                    config_sha256=DRYRUN_CONFIG_DIGEST,
                    pipeline_version='p2-h2v3-mock-dryrun',
                    code_version=DRYRUN_SCHEMA_VERSION,
                    index_revision='0')
    contract_binding = contract.binding(name)
    bindings.update(scenario_contract_sha256=contract_binding['scenario_contract_sha256'],
                    assignment_sha256=contract_binding['assignment_sha256'],
                    custody_sha256=contract_binding['custody_sha256'])
    writer = EvidenceWriter(root_dir=ev_dir, key=evidence_key, bindings=bindings,
                            fixture_kind='local_mock', run_name=run_id)
    capture = EvidenceCaptureConfig(root_dir=ev_dir, bindings=bindings, fixture_kind='local_mock',
                                    strict=True, writer=writer,
                                    capture_schema_version=EVIDENCE_SCHEMA_VERSION_V03)
    chat, chat_mode_used = build_chat(chat_mode)
    adapter = ProductEvalAdapter(
        run_dir,
        ingest_plan=ingest,
        dataset=subset,
        chat=chat,
        scenario_contract=contract,
        evidence_capture=capture,
        purge_traces_on_close=True,
        label=f'v3-dryrun-r{run_index}',
        rag_business_date=binding.rag_business_date,
        manifest_business_date=binding.manifest_business_date,
    )
    marks: list[Any] = []
    result: Any = None
    error: str | None = None
    dispatch: wiring.ScoringMapDispatch | None = None
    try:
        with wiring.dispatched_scoring_map(contract_v3.V3_SOURCE_MAP) as dispatch:
            result = await run_p2(
                plan,
                adapter=adapter,
                authorization=authorization,
                dataset=subset,
                gate=None,
                now=NOW,
                run_id=run_id,
                gate_config=gate_config,
                private_case_marks_sink=lambda rows: marks.extend(rows),
            )
    except Exception as exc:  # noqa: BLE001 - 干跑要留下失败码，不吞
        error = f'{type(exc).__name__}:{getattr(exc, "code", "")}'
    summary = adapter.evidence_capture_summary() or {}
    session_bindings = dict(summary.get('bindings') or {})
    receipts = list(writer.written)
    real_calls = int(getattr(result, 'requests_sent', 0) or 0)
    try:
        await adapter.close()
    except Exception as exc:  # noqa: BLE001
        error = error or f'close:{type(exc).__name__}'
    if result is None:
        return {'run_index': run_index, 'scenario_id': name, 'status': 'error',
                'error': error, 'business_date': binding.business_date}

    card_path = run_dir / 'p2-run' / 'holdout_scorecard.json'
    card = json.loads(card_path.read_text(encoding='utf-8')) if card_path.is_file() else None
    validated = None
    if card is not None:
        try:
            validate_scorecard(card, total=len(subset.cases), run_id=card.get('run_id'),
                               config_hash=card.get('config_hash'))
            validated = 'ok'
        except (ValueError, TypeError, KeyError) as exc:
            validated = f'invalid:{type(exc).__name__}'

    case_plan = build_case_plan(dataset=subset, run_id=run_id, bindings=session_bindings or bindings,
                                config_hash=card.get('config_hash') if card else None,
                                receipts=receipts, marks=marks)
    plan_path = ev_dir / 'case-plan.json'
    plan_receipt = write_json(plan_path, case_plan)
    audits = build_audits(case_plan, receipts, evidence_key=evidence_key,
                          expected_bindings=session_bindings or bindings, evidence_dir=ev_dir,
                          dataset=subset)
    hard_card, hard_error = build_hard_evidence(
        cases=subset.cases, annotation=annotation, audits=audits,
        plan_meta={
            'thresholds_approved': bool(card.get('thresholds_approved')) if card else False,
            'execution_mode': 'local_mock',
            'real_calls': 0,
            'run_id': run_id,
            'config_hash': card.get('config_hash') if card else None,
            'expected_strata': dict(subset.identity.get('strata') or {}),
        },
    )

    payload = {
        'run_index': run_index,
        'scenario_id': name,
        'business_date': binding.business_date,
        'status': str(getattr(result, 'status', '')),
        'error': error,
        'run_id': run_id,
        'turns': {k: v for k, v in (summary.get('status_counts') or {}).items()},
        'turn_count': int(summary.get('turn_count') or 0),
        'evidence_blocked': bool(summary.get('blocked')),
        'marks': {str(getattr(mark, 'status', '')): sum(1 for row in marks
                                                        if str(getattr(row, 'status', '')) == str(getattr(mark, 'status', '')))
                  for mark in marks},
        'case_plan': {'counts': {'cases': len(case_plan['cases']),
                                 'turns': sum(len(row['turns']) for row in case_plan['cases'])},
                      'sha256': plan_receipt['sha256']},
        'scorecard': card,
        'scorecard_validation': validated,
        'hard_evidence': hard_card,
        'hard_evidence_error': hard_error,
        'scoring_map': wiring.dispatch_summary(dispatch) if dispatch is not None else None,
        'plan_summary': summarize_plan(plan),
        'chat_mode': chat_mode_used,
        'requested_sends': real_calls,
        'observed_status_by_case': {
            (CASE_LABEL_RE.search(str(getattr(mark, 'case_id', ''))) or [None, None])[1]:
                str(getattr(mark, 'status', ''))
            for mark in marks
            if CASE_LABEL_RE.search(str(getattr(mark, 'case_id', '')))
        },
        'run_dir': str(run_dir),
        'evidence_dir': str(ev_dir),
    }
    return payload


def build_case_plan(*, dataset: Any, run_id: str, bindings: Mapping[str, str],
                    config_hash: str | None, receipts: Sequence[Mapping[str, Any]],
                    marks: Sequence[Any]) -> dict[str, Any]:
    """mock case-plan（``p2-hard-evidence-caseplan/v0.1`` 形状；含题号，只落仓外）。"""
    by_index = {int(row.get('turn_index', -1)): row for row in receipts
                if str(row.get('kind', 'turn')) == 'turn'}
    quality = {str(getattr(mark, 'case_id', '')): str(getattr(mark, 'status', 'error')) for mark in marks}
    rows: list[dict[str, Any]] = []
    cursor = 0
    for case in dataset.cases:
        turns: list[dict[str, Any]] = []
        for _ in range(len(case_questions(case))):
            receipt = by_index.get(cursor)
            turns.append({
                'turn_index': cursor,
                'status': 'executed' if receipt is not None else 'not_started',
                'evidence_file': None if receipt is None else Path(str(receipt['path'])).name,
                'error': None,
            })
            cursor += 1
        status = quality.get(str(case.case_id), 'error')
        if any(row['status'] != 'executed' for row in turns) and status not in ('error', 'not_executed'):
            status = 'error'
        rows.append({'case_id': str(case.case_id), 'quality_status': status, 'turns': turns})
    document = {
        'schema_version': CASEPLAN_SCHEMA_VERSION,
        'bindings': {key: str(bindings.get(key, '')) for key in BINDING_KEYS},
        'run_id': run_id,
        'config_hash': config_hash,
        'execution_mode': 'local_mock',
        'real_calls': 0,
        'thresholds_approved': False,
        'expected_strata': {str(k): int(v) for k, v in dict(dataset.identity.get('strata') or {}).items()},
        'cases': rows,
    }
    validate_case_plan(document, dataset.cases)
    return document


def build_audits(case_plan: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]], *,
                 evidence_key: bytes, expected_bindings: Mapping[str, str], evidence_dir: Path,
                 dataset: Any) -> list[dict[str, Any]]:
    """逐 case 的 audit：executed 回合必须读回并逐值验绑定/完整性。"""
    by_name = {Path(str(row.get('path'))).name: row for row in receipts}
    audits: list[dict[str, Any]] = []
    for row in case_plan['cases']:
        entries: list[dict[str, Any]] = []
        for turn in row['turns']:
            if turn['status'] != 'executed':
                entries.append({'turn_index': int(turn['turn_index']), 'status': turn['status'],
                                'error': turn['error'], 'evidence': None})
                continue
            name = str(turn['evidence_file'])
            path = by_name.get(name, {}).get('path') or str(evidence_dir / name)
            envelope = read_encrypted_evidence(Path(path), key=evidence_key,
                                               expected_bindings=dict(expected_bindings))
            entries.append({'turn_index': int(turn['turn_index']), 'status': 'executed',
                            'error': None, 'evidence': envelope})
        audits.append({'quality_status': row['quality_status'], 'turns': entries})
    if len(audits) != len(dataset.cases):  # pragma: no cover
        raise RuntimeError('audit 覆盖与题数不一致')
    return audits


def build_hard_evidence(*, cases: Sequence[Any], annotation: Any, audits: Sequence[Mapping[str, Any]],
                        plan_meta: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        card, _results = recompute_hard_evidence(cases, annotation, audits, plan_meta=plan_meta)
        validate_hard_evidence_scorecard(card, total=len(cases), run_id=plan_meta.get('run_id'),
                                         config_hash=plan_meta.get('config_hash'),
                                         expected_strata=plan_meta.get('expected_strata'))
        return card, None
    except Exception as exc:  # noqa: BLE001 - 四轴算不出来要留固定码，不伪装成 0
        return None, f'{type(exc).__name__}:{getattr(exc, "code", "")}'


def load_preregistration() -> dict[str, Any]:
    """读**已冻结**的预登记（只取题号/run/预期方向；不含题面/答案）。"""
    raw = PREREG_PATH.read_bytes()
    digest = sha256_bytes(raw)
    if digest != PREREG_SHA256:
        raise RuntimeError('预登记摘要与冻结值不一致')
    payload = json.loads(raw.decode('utf-8'))
    entries = payload['entries']
    runs: dict[str, set[int]] = {}
    directions: dict[str, set[str]] = {}
    for entry in entries:
        case = str(entry['case_id'])
        runs.setdefault(case, set()).add(int(entry['run']))
        directions.setdefault(case, set()).add(str(entry['expected_direction']))
    fail = sorted(case for case, dirs in directions.items() if 'fail' in dirs)
    not_affected = sorted(case for case, dirs in directions.items()
                          if dirs == {'not_affected'})
    return {'sha256': digest, 'fail': fail, 'not_affected': not_affected,
            'runs': {case: sorted(value) for case, value in runs.items()},
            'counts': dict(entries=len(entries), distinct_cases=len(directions),
                           fail_cases=len(fail), not_affected_only=len(not_affected))}


def prereg_comparison(prereg: Mapping[str, Any], results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    observed: dict[str, dict[str, Any]] = {}
    for row in results:
        for case, status in (row.get('observed_status_by_case') or {}).items():
            observed[str(case)] = {'run_index': row.get('run_index'), 'status': status}
    rows: list[dict[str, Any]] = []
    for case in sorted(set(prereg['fail']) | set(prereg['not_affected'])):
        registered = 'fail' if case in prereg['fail'] else 'not_affected'
        seen = observed.get(case, {})
        rows.append({
            'case': case,
            'registered_direction': registered,
            'registered_runs': list(prereg['runs'].get(case, [])),
            'observed_run_index': seen.get('run_index'),
            'observed_status': seen.get('status'),
            'channel_reached': bool(seen),
        })
    return {
        'schema_version': 'p2-h2v3-dryrun-prereg/v0.1',
        'preregistration_sha256': prereg['sha256'],
        'preregistration_counts': prereg['counts'],
        'note': 'Mock 下的 pass/fail 只用于核对"码位与链路是否走通"，不代表题目语义结论，不得据此宣称通过或失败。',
        'cases': rows,
        'fail_cases_with_status': sum(1 for row in rows
                                      if row['registered_direction'] == 'fail' and row['observed_status']),
        'fail_cases_observed_fail': sum(1 for row in rows
                                        if row['registered_direction'] == 'fail'
                                        and row['observed_status'] == 'fail'),
        'not_affected_observed_pass': sum(1 for row in rows
                                          if row['registered_direction'] == 'not_affected'
                                          and row['observed_status'] == 'pass'),
        'missing_status_cases': [row['case'] for row in rows if not row['observed_status']],
    }


# --------------------------------------------------------------------------- #
# C20/C22 索引层冒烟（纯离线；不调 embedding/模型）
# --------------------------------------------------------------------------- #


def _xlsx_rows(path: Path) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows: list[dict[str, Any]] = []
        for sheet in workbook.worksheets:
            values = list(sheet.iter_rows(values_only=True))
            header_index = next((i for i, row in enumerate(values)
                                 if row and all(isinstance(cell, str) and cell.strip()
                                                for cell in row[:3])), None)
            if header_index is None:
                continue
            header = [str(cell).strip() if cell is not None else '' for cell in values[header_index]]
            for row in values[header_index + 1:]:
                if not row or not any(cell not in (None, '') for cell in row):
                    continue
                rows.append({
                    'sheet': sheet.title,
                    'fields': {header[i]: ('' if cell is None else str(cell).strip())
                               for i, cell in enumerate(row) if i < len(header) and header[i]},
                })
        return rows
    finally:
        workbook.close()


def index_smoke(corpus_root: Path, ingest_names: Sequence[str]) -> dict[str, Any]:
    """文档标题 + 门店过滤在**产品自己的解析器**上是否可解析。

    用真实 v3 语料内容做 lexicon（门店/物品取自语料单元格），标题取自 ingest plan 的上传名。
    不调 embedding、不查库、不发请求；判据是 ``rag.query`` 的纯函数。
    """
    from mktkb.rag.query import DocumentRef, Lexicon, _document_core, parse_query

    position_rows = _xlsx_rows(corpus_root / 'normal' / 'D01_物品位置表.xlsx')
    store_rows = _xlsx_rows(corpus_root / 'normal' / 'D02_合作店家信息.xlsx')
    stores = sorted({row['fields'].get('门店', '') for row in position_rows + store_rows} - {''})
    items = sorted({row['fields'].get('物品', '') for row in position_rows} - {''})
    position_stores = {row['fields'].get('门店', '') for row in position_rows
                       if row['sheet'].startswith('物品位置') or row['fields'].get('物品')}
    title = 'D01_物品位置表.xlsx'
    core = _document_core(title)
    documents = (DocumentRef(doc_id='doc-d01', title=title),)
    lexicon = Lexicon(stores=tuple(stores), items=tuple(items), documents=documents)
    clean = DocumentRef(doc_id='doc-d01', title='物品位置表')
    clean_lexicon = Lexicon(stores=tuple(stores), items=tuple(items), documents=(clean,))
    probes: dict[str, Any] = {}

    def probe(name: str, question: str, used: Lexicon) -> dict[str, Any]:
        plan = parse_query(question, previous=None, lexicon=used, business_date='2026-07-15')
        filters = dict(plan.filters)
        return {
            'name': name,
            'stores_recognized': list(plan.state.stores),
            'store_filter': filters.get('store'),
            'doc_id_filter': filters.get('doc_id'),
            'doc_title_in_state': getattr(plan.state, 'doc_title', None),
            'mode': str(plan.mode),
            'clarification': plan.clarification,
            'reason': plan.reason,
            'missing_store': bool(plan.missing_stores),
        }

    def resolved(row: Mapping[str, Any]) -> bool:
        return bool(row['doc_id_filter'] or row['doc_title_in_state'])

    if len(stores) < 2:  # pragma: no cover - v3 语料固定有两家门店
        raise RuntimeError('语料门店不足两个，冒烟无法成立')
    item = items[0]
    # 同一句自然提问（只写中文标题、不写 Dxx 代号）；唯一变量是索引里的文档标题形态。
    title_question = f'物品位置表里{item}在哪'
    probes['two_stores'] = probe('two_stores', f'{stores[0]}和{stores[1]}的{item}分别放在哪', lexicon)
    probes['one_store_control'] = probe('one_store_control', f'{stores[0]}的{item}放在哪', lexicon)
    probes['doc_title_prefixed'] = probe('doc_title_prefixed', title_question, lexicon)
    probes['doc_title_clean'] = probe('doc_title_clean', title_question, clean_lexicon)
    probes['doc_title_prefixed']['resolved'] = resolved(probes['doc_title_prefixed'])
    probes['doc_title_clean']['resolved'] = resolved(probes['doc_title_clean'])
    return {
        'schema_version': INDEX_SMOKE_SCHEMA_VERSION,
        'corpus_root': str(corpus_root),
        'ingest_names': list(ingest_names),
        'stores': stores,
        'items': items,
        'document_core_of_ingested_title': core,
        'document_title_in_index': title,
        'position_sheets': sorted({row['sheet'] for row in position_rows}),
        'position_rows_with_store': len([row for row in position_rows if row['fields'].get('门店')]),
        'store_present_in_position_rows': {name: name in position_stores for name in stores},
        'probes': probes,
        'two_stores_recognized': len(probes['two_stores']['stores_recognized']) == 2,
        'two_stores_filter_dropped': probes['two_stores']['store_filter'] is None,
        'one_store_filter_kept': probes['one_store_control']['store_filter'] is not None,
        'title_resolvable_with_prefix': probes['doc_title_prefixed']['resolved'],
        'title_resolvable_without_prefix': probes['doc_title_clean']['resolved'],
    }


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='v3 Mock 端到端干跑（零真实调用）')
    parser.add_argument('--root', default=os.environ.get(HOLDOUT_ROOT_ENV) or '')
    parser.add_argument('--key-file', default=os.environ.get(HOLDOUT_KEY_FILE_ENV) or '')
    parser.add_argument('--out', default=str(PROJECT_ROOT / 'docs/reports/OBS-EVAL/P2/H2V3/dryrun'))
    parser.add_argument('--evidence-root', default=r'D:\mktkb-p2-dryrun')
    parser.add_argument('--only-runs', default='')
    parser.add_argument('--skip-index-smoke', action='store_true')
    parser.add_argument('--chat-mode', choices=('stock', 'echo-all'), default='stock')
    args = parser.parse_args(argv)

    if not args.root or not args.key_file:
        print(json.dumps({'error': 'need --root/--key-file or env'}, ensure_ascii=False))
        return 3
    root, key_file = Path(args.root).resolve(), Path(args.key_file).resolve()
    out_root, evidence_root = Path(args.out).resolve(), Path(args.evidence_root).resolve()
    if out_root.is_relative_to(PROJECT_ROOT) is False:
        print(json.dumps({'error': 'out 必须是仓库内路径'}, ensure_ascii=False))
        return 3
    if evidence_root.is_relative_to(PROJECT_ROOT):
        print(json.dumps({'error': 'evidence-root 必须在仓库外'}, ensure_ascii=False))
        return 3
    for key in PROXY_ENV_KEYS:
        os.environ.pop(key, None)
    os.environ[HOLDOUT_ROOT_ENV] = str(root)
    os.environ[HOLDOUT_KEY_FILE_ENV] = str(key_file)
    guard = install_guard()
    control = positive_control()
    if not control['blocked']:
        print(json.dumps({'error': 'netguard 正对照未全拦', 'control': control}, ensure_ascii=False))
        return 4

    dataset = load_p2_dataset(root / 'manifest.json', visibility='holdout')
    contract = contract_v3.load_v3_scenario_contract(
        dataset,
        annotation_path=root / 'annotations-v0_2.fernet',
        key_file=key_file,
        review_path=root / 'review-v0_2.fernet',
    )
    payload, annotation_sha = annotation_payload(root / 'annotations-v0_2.fernet', key_file)
    annotation = prepare_annotation(payload, dataset.cases,
                                   schema_path=contract_v3.V3_SCHEMA,
                                   scenario_path=contract_v3.V3_SCENARIO_CONTRACT)
    wiring.assert_v01_identity()
    closure = wiring.assert_remap_closure(dataset.cases, wiring.source_map_for_scoring(contract_v3.V3_SOURCE_MAP).mapping)

    runs_root = out_root / 'runs'
    only = {int(x) for x in args.only_runs.split(',') if x.strip()} if args.only_runs else None
    results: list[dict[str, Any]] = []
    for run_index in range(4):
        if only is not None and run_index not in only:
            continue
        result = asyncio.run(run_one(
            contract=contract, run_index=run_index, annotation=annotation,
            dataset_anchor=dataset.manifest.business_date, out_root=evidence_root,
            evidence_root=evidence_root / 'evidence', chat_mode=args.chat_mode,
            nonce_tag=uuid.uuid5(
                uuid.NAMESPACE_URL, f'p2-h2v3-dryrun-r{run_index}').hex[:8],
        ))
        run_out = runs_root / f'r{run_index}'
        if result.get('scorecard') is not None:
            write_json(run_out / 'holdout_scorecard.json', result['scorecard'])
        if result.get('hard_evidence') is not None:
            write_json(run_out / 'holdout_scorecard_v0_2.json', result['hard_evidence'])
        if not args.skip_index_smoke and run_index in C20_C22_RUNS:
            names = [str(source.name or source.path.name)
                     for source in contract.ingest_plan(contract.scenario_ids[run_index]).sources]
            smoke = index_smoke(PROJECT_ROOT / 'fixtures/acceptance-h2v3', names)
            smoke['run_index'] = run_index
            smoke['scenario_id'] = contract.scenario_ids[run_index]
            result['index_smoke'] = smoke
            write_json(run_out / 'index_smoke.json', smoke)
        receipt = {k: v for k, v in result.items()
                   if k not in ('scorecard', 'hard_evidence', 'index_smoke', 'run_dir', 'evidence_dir',
                                'observed_status_by_case')}
        receipt['schema_version'] = RUN_RECEIPT_SCHEMA_VERSION
        receipt['scorecard_sha256'] = None if result.get('scorecard') is None else hashlib.sha256(
            json.dumps(result['scorecard'], ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        receipt['hard_evidence_sha256'] = None if result.get('hard_evidence') is None else hashlib.sha256(
            json.dumps(result['hard_evidence'], ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        result['receipt'] = write_json(run_out / 'run_receipt.json', receipt)
        results.append(result)

    summary = {
        'schema_version': DRYRUN_SCHEMA_VERSION,
        'mode': 'local_mock',
        'business_dates': [{'run_index': row.run_index, 'scenario_id': row.scenario_id,
                            'business_date': row.business_date}
                           for row in run_date.bind_all_runs(dataset_anchor=dataset.manifest.business_date)],
        'contract': contract.safe_summary(),
        'dataset': {'dataset_version': dataset.manifest.dataset_version,
                    'label_version': dataset.manifest.label_version,
                    'manifest_sha256': dataset.manifest.manifest_sha256,
                    'cases': len(dataset.cases),
                    'turns': sum(len(case_questions(c)) for c in dataset.cases)},
        'annotation_ciphertext_sha256': annotation_sha,
        'scoring_map_wiring': {
            'v01_identity': True,
            'remap_closure_cases': closure,
            'declared': wiring.dispatch_summary(wiring.ScoringMapDispatch(
                path=str(contract_v3.V3_SOURCE_MAP),
                version=wiring.source_map_for_scoring(contract_v3.V3_SOURCE_MAP).schema_version,
                code_count=wiring.source_map_for_scoring(contract_v3.V3_SOURCE_MAP).code_count)),
            'per_run_resolutions': {str(row.get('run_index')): (row.get('scoring_map') or {}).get('resolutions')
                                    for row in results},
            'total_resolutions_served_by_dispatch': sum(
                int((row.get('scoring_map') or {}).get('served_by_dispatch') or 0) for row in results),
        },
        'runs': [{
            'run_index': row.get('run_index'),
            'scenario_id': row.get('scenario_id'),
            'business_date': row.get('business_date'),
            'status': row.get('status'),
            'error': row.get('error'),
            'turn_count': row.get('turn_count'),
            'turns': row.get('turns'),
            'scorecard': None if row.get('scorecard') is None else {
                'total': row['scorecard']['total'], 'executed': row['scorecard']['executed'],
                'errors': row['scorecard']['errors'], 'passed': row['scorecard']['passed'],
                'failed': row['scorecard']['failed'],
                'by_stratum': row['scorecard']['by_stratum'],
                'hard_failures': row['scorecard']['hard_failures'],
                'blocks': [block['code'] for block in row['scorecard']['blocks']],
                'thresholds_approved': row['scorecard']['thresholds_approved'],
                'release_ready': row['scorecard']['release_ready'],
                'validation': row.get('scorecard_validation'),
            },
            'hard_evidence': None if row.get('hard_evidence') is None else {
                'total': row['hard_evidence']['total'],
                'executed': row['hard_evidence']['executed'],
                'errors': row['hard_evidence']['errors'],
                'passed': row['hard_evidence']['passed'],
                'failed': row['hard_evidence']['failed'],
                'axes': row['hard_evidence']['hard_evidence']['axes'],
                'hard_failures_by_kind': row['hard_evidence']['hard_evidence']['hard_failures_by_kind'],
                'missing_evidence_cases': row['hard_evidence']['hard_evidence']['missing_evidence_cases'],
                'evidence_complete_cases': row['hard_evidence']['hard_evidence']['evidence_complete_cases'],
                'verified': row['hard_evidence']['hard_evidence']['verified'],
                'blocks': [block['code'] for block in row['hard_evidence']['blocks']],
            },
            'hard_evidence_error': row.get('hard_evidence_error'),
            'case_plan': row.get('case_plan'),
            'scoring_map': row.get('scoring_map'),
            'index_smoke': None if row.get('index_smoke') is None else {
                key: row['index_smoke'][key] for key in
                ('two_stores_recognized', 'two_stores_filter_dropped', 'one_store_filter_kept',
                 'title_resolvable_with_prefix', 'title_resolvable_without_prefix',
                 'document_core_of_ingested_title', 'stores', 'items', 'probes')
            },
        } for row in results],
        'zero_call': {
            'positive_control': control,
            'external_attempts': len(guard.snapshot()['external']),
            'local_attempts': len(guard.snapshot()['local']),
            'external': guard.snapshot()['external'],
        },
    }
    summary['prereg_comparison'] = prereg_comparison(load_preregistration(), results)
    write_json(out_root / 'prereg_comparison.json', summary['prereg_comparison'])
    summary['totals'] = {
        'cases': sum((row.get('scorecard') or {}).get('total', 0) for row in results),
        'turns': sum(int(row.get('turn_count') or 0) for row in results),
        'executed': sum((row.get('scorecard') or {}).get('executed', 0) for row in results),
        'errors': sum((row.get('scorecard') or {}).get('errors', 0) for row in results),
        'passed': sum((row.get('scorecard') or {}).get('passed', 0) for row in results),
        'failed': sum((row.get('scorecard') or {}).get('failed', 0) for row in results),
    }
    write_json(out_root / 'summary.json', summary)
    print(json.dumps({'totals': summary['totals'], 'runs': [
        {'run_index': row.get('run_index'), 'status': row.get('status'), 'turns': row.get('turn_count'),
         'card': None if row.get('scorecard') is None else
         [row['scorecard']['total'], row['scorecard']['executed'], row['scorecard']['passed'],
          row['scorecard']['failed'], row['scorecard']['errors']],
         'hard': None if row.get('hard_evidence') is None else 'axes-ok',
         'hard_error': row.get('hard_evidence_error'),
         'error': row.get('error')}
        for row in results], 'zero_call': summary['zero_call']['external_attempts']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
