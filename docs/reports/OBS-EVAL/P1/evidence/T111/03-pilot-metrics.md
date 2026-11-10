# T111 证据 03：pilot 指标、manifest 与零 chat

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

运行：`b0-live-20261108T194053896474Z-b224f9fb`
产物：`var/eval/runs/b0-live-20261108T194053896474Z-b224f9fb/`（gitignored，不入库）。

## A. manifest 版本绑定（六要素 + corpus sha + index_revision）

```text
mode=live  scope=retrieval_only  suite=b0  case_count=10
dataset_version=b0:b0-2026-11-04:d958336c01fe
dataset_sha256=aa2acdcaeb3a8b0f3cca5079d0817dd133702c16edce2b46faf4800c0385e95d
corpus_manifest_sha256=6889915267c5127312f1ee9308362ce0198277b1a916a2e6413dd48b5d2755b6
index_revision=6
pipeline_version=08166b113481（真实 embedding/rerank 配置参与；与 local 明确区分）
gate_version=mktkb.gate.v0.1
label_version=b0-2026-11-04  business_date=2026-10-28
config_hash=86132c83798f
```

隔离索引：`<run>/index/rag.sqlite3`；6 文件 / 42 unit / **27 chunk** / revision 6。
实时配置：`text-embedding-v4`(1024)、`gte-rerank-v2`、`top_k=8`、检索输出深度 10
（`index.search(plan, limit=10)`，不改变产品 top_k），embedding batch=5，
`max_retries=0`，`chat_model=None`。

## B. 逐 case 版本字段

`cases.jsonl` 10 行的 `versions` 完全一致，且与 manifest 同值：

```json
{"dataset_version":"b0:b0-2026-11-04:d958336c01fe",
 "dataset_sha256":"aa2acdcaeb3a8b0f3cca5079d0817dd133702c16edce2b46faf4800c0385e95d",
 "corpus_manifest_sha256":"6889915267c5127312f1ee9308362ce0198277b1a916a2e6413dd48b5d2755b6",
 "index_revision":6,"pipeline_version":"08166b113481","gate_version":"mktkb.gate.v0.1",
 "label_version":"b0-2026-11-04","business_date":"2026-10-28",
 "config_hash":"86132c83798f","mode":"live","scope":"retrieval_only"}
```

## C. 指标（retrieval_only；10 题全部执行成功）

| 指标 | 值 |
| --- | ---: |
| case_count / scored_count | 10 / 10 |
| status_counts | `{"pass": 10}` |
| Recall@10 | 1.0 |
| MRR@10 | 1.0 |
| nDCG@10 | 1.0 |
| hard_filter_violation_rate | 0.0 |
| empty_recall_rate | 0.0 |

逐 case 均有 1 个 gold unit / 1 个 retrieved unit；无 error、无 OCR 跳过。
本 pilot 只覆盖 b0 前 10 题（exact 类），**不代表全量 b0/badcase/regression/holdout**；
全量留 T112 放行后执行。

## D. 零 chat 证明（真实运行）

1. 配置层：`RagConfig.chat_model=""`、`chat_api_key=""`、`chat_base_url=""`；
   live 分支只调用 `index.search(plan, limit)`，从不调用 `RagIndex.ask`。
2. provider 计数：`post_counters()` attempts = `{"embedding":17,"rerank":10}`，chat 缺失（0）。
3. 账本归属：按 `run_id` 过滤后 `reserved` = embedding 17 / rerank 10 / chat 0；
   `result` 同；`chat_reserved=0`、`chat_results=0`。
4. 离线 spy 测试（`test_live_runner.py`）证明 `DeepSeekChatProvider.__init__`/
   `complete` 与 `RagIndex.ask` 均未被调用。

## E. 摘要字段位置

`summary.json.live`：`precheck` / `budget_before` / `budget_after` / `budget_delta` /
`ledger_events` / `provider_requests` / `chat_calls=0` / `go`（授权摘要，无 GO 原文）/
`config`（`safe_config_summary`，无凭据）。`summary.json.retrieval_only=true`；
`summary.json.declarations.retrieval_only.answers_generated=false`。
