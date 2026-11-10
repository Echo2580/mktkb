# T112 独立验收证据 02：baseline 审批、b0 live run 与全量守卫

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. baseline approve 产物（只读核对）

```text
baseline_id=bc6f6f906db1  run_id=b0-live-20261109T111828086143Z-0efd058b
approver=主人  gate_exit_code=0  quality_status=pass
reason=P1 首次 release baseline（b0 live 40 题）；绝对阈值按 T112 校准提案批准；首次建立不做回退检测
gate_result_sha256=c9fcbbb67aa896f1024199fc4c61e931ae36b2df3038fe095897e37d4721742b
mode=live scope=retrieval_only gate_version=mktkb.gate.v0.2
sha256(approval.json)=80113647D0B640D37B3F6C86C6B67758DE7E907F51E3A6FF47DC42B1AF9AAD43
sha256(baseline.json)=1924FAF86FAD52D4495F07C64E2DB1A9262A1299A2B0817FE9D604DE3AD6B07A
baseline list -> baseline_id=bc6f6f906db1 ... approved=yes (exit 0)
```

- 六要素 identity 与 manifest 逐项相等：`b0:b0-2026-11-04:bd4f0f7ccc6e` /
  `08166b113481` / `live` / `retrieval_only` / `mktkb.gate.v0.2` /
  `6889915267c5127312f1ee9308362ce0198277b1a916a2e6413dd48b5d2755b6`；
  重算 `sha256(concat)[:12]=bc6f6f906db1`。
- `artifact_sha256` 与 run 的 manifest/cases/summary 当前摘要逐一相等。
- 在 scratch root 重跑 `baseline approve`（同一 run 副本）得到同一 baseline_id；
  与交付 approval.json 仅 `approved_at` 不同，`gate_result_sha256`/exit/quality/approver/reason 全同。
- 负例：`--config` 用未审批 R0 配置 → 现场重算 exit 3，`baseline approve 拒绝`，未写 approval；
  CLI 空 `--approver` → argparse exit 2；库层 `approve_baseline` 空 approver/reason 拒绝（R0 测试覆盖）。
- `var/eval/baselines/` 仅 `bc6f6f906db1` 一条；审批前该目录无 P0 baseline，
  未创建/未 copy P0 baseline。`diff --baseline 000000000000` → exit 3
  （`baseline 未建立 ... fail closed`）。
- 跨版本抽查：将 manifest pipeline_version 改为 `deadbeef0000` 后，
  `load_baseline(expected=...)` 无 `compare_with` → `CrossVersionBaselineError`；
  显式 `compare_with=bc6f6f906db1` → `comparison=explicit_cross_version`、
  `release_allowed=False`、`require_release_baseline` 拒绝；同版本 → `release_baseline`/allowed。

## B. b0 live run（只读核对，未重跑 live）

```text
run_id=b0-live-20261109T111828086143Z-0efd058b
case_count=40 suite=b0 mode=live scope=retrieval_only
dataset_sha256=bd4f0f7ccc6e…（= fixtures/evaluation/b0.jsonl 当前字节）
corpus_manifest_sha256=68899152… pipeline_version=08166b113481 gate_version=mktkb.gate.v0.2
index: documents=6 units=42 chunks=27 revision=6
status_counts={pass:32, skipped_requires_ocr:8} error_count=0 aborted=false
metrics: Recall/MRR/nDCG all=0.96875 exact=1.0 text=0.875;
         hard_filter all/exact/text=0; empty_recall all=0.03125 / exact=0 / text=0.125
每行 versions 11 字段（dataset_version/sha、corpus sha、index/pipeline/gate/mode/scope/label/business_date/config_hash），40 行唯一版本字典=1
```

账本按 `run_id` 独立复核（`docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl`）：

```text
rows=140：reserved 70（embedding 39 / rerank 31 / chat 0）+ result 70（39/31）
reservation_id 70 个、每 id 恰好 1 result；http_status 全 200；boundary_anomaly 全 false
reserve 合计 2.34144 元；result conservative_charge_cny 合计 0.0090459 元
provider_billed_cny 全 null；summary.provider_requests.attempts={embedding:39, rerank:31}
summary.retries=0；config.max_retries=0；require_zero_retries=true
budget_before reservation_count=435 → after=505 / GO max_requests=1000
P1-RETRIEVAL stage 0.005269 → 0.0143149 元（+0.0090459）；precheck estimated_cny=0.771174
provider_billed_cny=null（summary + 每笔 result）
```

## C. `--allow-full-live` 守卫负例（零 HTTP；均在凭据/GO 读取前拒绝）

```text
默认关闭 + 40 题 b0 -> exit 3（必须显式放行）
--allow-full-live + suite=badcase -> exit 3（只允许 b0）
--allow-full-live + 39 题 -> exit 3（必须恰好 40）
--allow-full-live + 40 题但首行多一空格（sha 变） -> exit 3（字节级 sha 不符）
--allow-full-live + --pilot 10 -> exit 3（互斥）
```

- 正例不重跑（避免读 `.env`/账本与真实调用）；R0 证据 01 的预检/运行结果已核对。
- `live.py:677` 守卫、`live.py:744` 预检分支、`runner.py:1052` 运行分支一致。

## D. 范围

- P1 release baseline 仅来自 b0 live；badcase/regression/holdout live 与 P0 跨版本比较
  仍 NOT-RUN（主人方案 A 请求上限；report §5/§R1、证据 04 §D 已登记）。
