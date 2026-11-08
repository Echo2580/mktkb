# T111 证据 01：范围、改动与命令

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 起点与口径

- 分支 `p1/fix-retrieval`，父提交 `1552a9e`（T110 G6 后）；开工前 `git status --short` 为空。
- 范围：`mode=live + scope=retrieval_only`；只做真实 embedding `text-embedding-v4`(1024)
  + rerank `gte-rerank-v2`，**不生成答案、不调用 chat**；零重试、串行、首个失败即停。
- GO：`load_live_authorization(stage="P1-RETRIEVAL", service="rag")` →
  stage_limit 3.0 元 / max_requests 1000 / max_request_cny 0.05 / expires 2026-11-30；
  `resolve_live_gate` 收敛 total_limit=20.0。GO 绑定的历史前缀哈希 `f4710b18…`
  （不写整本账本 sha）。
- 环境：`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；凭据由既有 `.env` 体系读取
  （`DASHSCOPE_API_KEY`），不打印、不写证据、不入库。

## B. 改动（只动 handoff 允许路径）

| 文件 | 性质 | 要点 |
| --- | --- | --- |
| `backend/src/mktkb/evaluation/live.py` | 新增 | live 配置接线：GO/账本/预算闸门、凭据读取、provider binding 核对、成本预检、pilot 校验、`python -m mktkb.evaluation.live` CLI；临时清理环境 `NO_PROXY` 中 httpx 0.28.1 无法解析的 `[::1]` 条目（仅包装索引装配期，结束恢复） |
| `backend/src/mktkb/evaluation/runner.py` | 扩展 | `MODES` 增加 `live`；`run_suite` 增加 live 分支（pilot ≤10、隔离索引、逐 case 版本字段、fail-stop、零 chat 校验、冻结的 liveness/预算摘要）；`_build_summary` 增加 retrieval-only 口径；local/replay 默认行为不变 |
| `backend/src/mktkb/evaluation/corpus.py` | 扩展 | `build_suite_index` 增加 live 分支（真实 embedding/rerank + 共享账本）；offline 分支行为不变 |
| `backend/tests/evaluation/test_live_runner.py` | 新增 | 10 条 fake/负例：预检、阶段/单请求/请求数拒绝、GO 绑定不符、零 chat spy、fail closed/零重试、pilot 停点、manifest/逐行版本字段、OCR 显式跳过、proxy env 恢复 |

## C. 运行命令（cwd=仓库根）

准备 pilot 子集（`var/` 已 gitignore，不入库）：

```text
python -B -c "import pathlib; s=pathlib.Path('fixtures/evaluation/b0.jsonl').read_text(encoding='utf-8').splitlines(keepends=True); p=pathlib.Path('var/eval/pilot/b0-pilot10.jsonl'); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(''.join(s[:10]), encoding='utf-8')"
```

预检（零预留、零 HTTP）：

```text
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
python -B -m mktkb.evaluation.live --suite b0 --dataset var\eval\pilot\b0-pilot10.jsonl --pilot 10 --dry-run
```

真实 pilot（10 题，跑完即停）：

```text
python -B -m mktkb.evaluation.live --suite b0 --dataset var\eval\pilot\b0-pilot10.jsonl --pilot 10
```

预检输出（本次 pilot 前；pilot 摘要中的 precheck 与之同值）：

```text
mode=live scope=retrieval_only suite=b0 cases=10 dry_run=true
stage=P1-RETRIEVAL stage_limit_cny=3.0 stage_accounted_cny=0.0 stage_remaining_cny=3.0 reservations=381
precheck accepted=true estimated_cny=0.24277650 embedding_index_cny=0.00261150 query_embedding_cny=0.00016500 rerank_cny=0.24000000
precheck requests total=27 embedding_batches=7 query_embeddings=10 rerank=10 max_single_reserve_cny=0.04096000 reasons=none
```

真实 pilot 输出：

```text
run_id=b0-live-20261108T194053896474Z-b224f9fb suite=b0 mode=live scope=retrieval_only cases=10 out=D:\GPT项目\市场部AI知识库\var\eval\runs\b0-live-20261108T194053896474Z-b224f9fb
precheck_estimated_cny=0.2427765 precheck_requests=27 pilot=True
ledger_stage=P1-RETRIEVAL stage_accounted_before=0.0 stage_accounted_after=0.0026345 stage_remaining_after=2.9973655 reservations_before=381 reservations_after=408
provider_requests embedding=17 rerank=10 chat=0
metrics Recall@10=1.0 MRR@10=1.0 nDCG@10=1.0 hard_filter_violation_rate=0.0 empty_recall_rate=0.0
aborted=false
```

## D. 环境问题与处置（如实记录）

首次尝试在 **索引装配构造 `httpx.Client`** 时失败：本机 `NO_PROXY` 含 `::1,[::1]`，
httpx 0.28.1 的 `URLPattern` 把 `[::1]` 当 URL 解析并抛 `InvalidURL: Invalid port`。
该失败发生在任何 provider 预留/HTTP 之前（账本仍为 381 次预留、P1-RETRIEVAL 占用 0.0）。
处置：`evaluation/live.py` 增加 `httpx_compatible_proxy_env()`，仅在 live 索引装配期
临时移除括号 IPv6/`::1` 条目（保留 localhost/127.0.0.1），结束逐值恢复；未改业务
provider、未改代理/系统设置。随后 pilot 成功（27 次真实请求，0 chat）。
