# T112 证据 01：b0 全量 40 题 live（retrieval_only）真实运行

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 授权与预算闸门（运行前）

- GO/账本：`P1-RETRIEVAL` / `rag` / 3.0 元 / max_requests=1000 / max_request_cny=0.05；
  `resolve_live_gate` 收敛 total_limit=20.0；账本历史前缀 `f4710b18…`（不写整本 sha）。
- 运行环境：`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`（与 `budget.json.limit_cny` 相等）。
- 凭据：既有 `.env` 的 `DASHSCOPE_API_KEY`，未打印、未入证据/仓库。

预检（零 HTTP、零预留）：

```text
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.live --suite b0 ^
  --dataset fixtures\evaluation\b0.jsonl --allow-full-live --dry-run
mode=live scope=retrieval_only suite=b0 cases=40 full_live=true dry_run=true
stage=P1-RETRIEVAL stage_limit_cny=3.0 stage_accounted_cny=0.005269 stage_remaining_cny=2.994731 reservations=435
precheck accepted=true estimated_cny=0.77117400 embedding_index_cny=0.00261150 query_embedding_cny=0.00056250 rerank_cny=0.76800000
precheck requests total=71 embedding_batches=7 query_embeddings=32 rerank=32 max_single_reserve_cny=0.04096000 reasons=none
```

判定：71 请求 ≤ 本包 300 上限；单笔最大预留 0.04096 ≤ 0.05；估算 0.771174 元
（+单笔预留）≤ 阶段剩余 2.994731 元 → 放行。实际计费口径见 D。

## B. 真实运行（一次，跑完即停）

```text
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.live --suite b0 ^
  --dataset fixtures\evaluation\b0.jsonl --allow-full-live
run_id=b0-live-20261109T111828086143Z-0efd058b suite=b0 mode=live scope=retrieval_only cases=40
precheck_estimated_cny=0.771174 precheck_requests=71 pilot=False
ledger_stage=P1-RETRIEVAL stage_accounted_before=0.005269 stage_accounted_after=0.0143149
  stage_remaining_after=2.9856851 reservations_before=435 reservations_after=505
provider_requests embedding=39 rerank=31 chat=0
metrics Recall@10=0.96875 MRR@10=0.96875 nDCG@10=0.96875
  hard_filter_violation_rate=0.0 empty_recall_rate=0.03125
aborted=false
```

产物：`var/eval/runs/b0-live-20261109T111828086143Z-0efd058b/`（gitignored，不入库）。

## C. manifest 六要素 + 语料/索引绑定

```text
run_id=b0-live-20261109T111828086143Z-0efd058b
mode=live  scope=retrieval_only  suite=b0  case_count=40
dataset_version=b0:b0-2026-11-04:bd4f0f7ccc6e
dataset_sha256=bd4f0f7ccc6e9f50ba630598c01b3519804447d4e0f3bfbc2facd54a5a521e4f（=冻结 b0.jsonl）
corpus_manifest_sha256=6889915267c5127312f1ee9308362ce0198277b1a916a2e6413dd48b5d2755b6
index_revision=6  pipeline_version=08166b113481  gate_version=mktkb.gate.v0.2
label_version=b0-2026-11-04  business_date=2026-10-28  config_hash=86132c83798f
index: documents=6 units=42 chunks=27 revision=6
```

每行 `cases.jsonl` 带 `versions` 十项（dataset/corpus/index/pipeline/gate/mode/scope/
label/business_date/config_hash），与 manifest 一致（`tests/evaluation/test_t112_gate_baseline.py` 覆盖）。

## D. 请求/成本/零 chat（保守口径）

| 项 | 观测 |
| --- | --- |
| 真实请求 | 70 = embedding 39（索引 7 批 + query 32）+ rerank 31；≤300 |
| chat | **0**（`provider_requests` 无 chat；`chat_calls=0`；账本按 run_id 过滤 chat reserved/results=0） |
| 重试 | 0（`max_retries=0` / `require_zero_retries=True`；`retries=0`） |
| 失败语义 | `aborted=false`；8 题 OCR 显式 `skipped_requires_ocr`，32 题计分 |
| 账本 | `P1-RETRIEVAL` 预留/结果各 70 笔；stage 0.005269 → **0.0143149** 元（+0.0090459） |
| 预检 vs 账本 | 预检上限 0.771174；账本保守记录 0.0090459；`provider_billed_cny=null`（不是供应商账单） |
| 单笔预留 | 0.04096 ≤ 0.05 |

rerank 比 query 少 1 次：1 个 query 检索无候选，未触发 rerank（不伪造请求）。
