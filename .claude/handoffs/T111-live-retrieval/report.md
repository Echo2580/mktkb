模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# T111 live 检索运行器与真实索引（pilot）

## 1. 起点与范围

- 分支 `p1/fix-retrieval`，父提交 `1552a9e`；开工前 `git status --short` 为空。
- 只做 `mode=live + scope=retrieval_only`：真实 `text-embedding-v4`(1024) +
  `gte-rerank-v2`；不生成答案、不调用 chat；零重试、串行、首个失败即停。
- GO：`P1-RETRIEVAL` / `rag` / 3.0 元 / max_requests=1000 / max_request_cny=0.05；
  `resolve_live_gate` 收敛 total_limit=20.0；账本历史前缀绑定 `f4710b18…`。
- 凭据由既有 `.env` 体系读取（`DASHSCOPE_API_KEY`），未打印、未入证据/仓库。

## 2. 改动（handoff 允许路径）

| 文件 | 要点 |
| --- | --- |
| `evaluation/live.py`（新增） | GO/账本/预算闸门、凭据读取、provider binding 核对、成本预检、pilot 校验、`python -m mktkb.evaluation.live` CLI；索引装配期临时清理本机 `NO_PROXY` 的 `[::1]`（httpx 0.28.1 不兼容，结束恢复） |
| `evaluation/runner.py` | `MODES` 加 `live`；`run_suite` live 分支：pilot ≤10、隔离索引 `<run>/index/`、逐 case 版本字段、fail-stop、零 chat 校验、预算/liveness 摘要；`_build_summary` retrieval-only 口径；local/replay 默认不变 |
| `evaluation/corpus.py` | `build_suite_index` live 分支（真实 embedding/rerank + 共享账本）；offline 分支不变 |
| `tests/evaluation/test_live_runner.py`（新增） | 11 条 fake/负例：预检、预算拒绝、GO 绑定不符、零 chat spy、fail closed/零重试、pilot 停点、manifest/版本字段、OCR 跳过、多轮状态、proxy env 恢复 |

## 3. 命令与产物

```text
# 准备 pilot 子集（var/ 已 gitignore）
python -B -c "...read fixtures/evaluation/b0.jsonl; write first 10 lines -> var/eval/pilot/b0-pilot10.jsonl"
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
python -B -m mktkb.evaluation.live --suite b0 --dataset var\eval\pilot\b0-pilot10.jsonl --pilot 10 --dry-run
python -B -m mktkb.evaluation.live --suite b0 --dataset var\eval\pilot\b0-pilot10.jsonl --pilot 10
```

- 真实 pilot：`b0-live-20261108T194053896474Z-b224f9fb`，10 题，`aborted=false`。
- 产物：`var/eval/runs/<run_id>/`（manifest/cases/summary/traces/index），不入库。
- 索引：6 文件 / 42 unit / 27 chunk / revision 6；`pipeline_version=08166b113481`，
  `config_hash=86132c83798f`；`index.search(plan, limit=10)`（不改产品 top_k）。

## 4. 结果（保守口径）

- **成本预检**：0.2427765 元（index 0.0026115 + query embed 0.000165 + rerank 0.24），
  27 次请求，单笔最大预留 0.04096 ≤ 0.05，阶段剩余 3.0 → 接受。
- **账本**：stage `P1-RETRIEVAL` 0.0 → **0.0026345 元**；预留 381 → 408（+27），
  27 笔全部 `succeeded`；`provider_billed_cny=null`（不是供应商账单）。
- **请求量**：embedding 17（索引 7 + query 10）、rerank 10、chat 0；零重试。
- **指标（10 题）**：`Recall@10=1.0`、`MRR@10=1.0`、`nDCG@10=1.0`、
  `hard_filter_violation_rate=0.0`、`empty_recall_rate=0.0`；status `{"pass":10}`。
- **零 chat**：配置无 chat 字段；`post_counters` 无 chat；账本按 run_id 过滤
  `reserved={embedding:17,rerank:10}`、`result` 同、chat 0；spy 测试 0 次。
- **版本绑定**：manifest 六要素 + corpus sha + `index_revision=6`；10 行 `versions`
  与 manifest 一致（dataset/corpus/index/pipeline/gate/mode/scope/label/business_date/
  config_hash）。

## 5. 验证、合规与下一步

- 测试：本包 11 passed；`backend/tests/evaluation` 420 passed；全量 **1823 passed**
  （0 failed/0 error，500.60s，峰值 RSS 约 412MB）。
- 本地 P0 对照：b0 40/40、badcase 13/13、regression 7/7 `signature diffs=0`；
  gate 均 exit 3、hard `[]`（既有 min_sample/thresholds），regression 与 T109-R2 一致。
- 合规：未改业务代码/API/检索算法/conversations；未读 Holdout；未 commit var/账本/GO；
  未 push/amend；无 skip/xfail/删断言；证据无凭据/答案原文。
- **pilot 后已停止，不自动全量。** T112 风险：账本已 408/1000 次预留，regression live
  索引（5066 chunk、batch=5）约需 1033 次 embedding 请求，全量前必须缩小索引语料/
  调整 batch 或重签请求上限；阶段金额剩余 2.9973655 元不是唯一约束。
