# Evaluation Data Protocol v0.1（T001）

> 状态：P0 契约冻结稿（Task 1）。
> 来源：`docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md` §7（含 §7.3 / §7.4）。
> 实现：Case 加载/校验/`dataset_version` 在 Task 4 落地；本文件先冻结数据结构与口径。
> 版本常量：`CASE_SCHEMA_VERSION = "mktkb.eval.case.v0.1"`（`mktkb.observability.contracts`）。

## 1. 文件与编码

- 一行一个 case 的 JSONL，UTF-8；`fixtures/evaluation/b0.jsonl`、`badcase.jsonl`（P0），
  `holdout.jsonl`（P1）。
- 每个 case 必须带 `case_id`，在同一 `suite` 内唯一；`split` 区分 `dev` / `holdout`。
- 运行清单（`run_manifest.json`）与每个 `CaseResult` 都携带 §6 的版本字段。

## 2. Case 结构

```json
{
  "case_id": "H01",
  "suite": "holdout",
  "split": "holdout",
  "stratum": "paraphrase",
  "business_date": "2026-10-28",
  "question": "海报搁哪儿了？",
  "turns": [],
  "expected_kind": "answer",
  "expected_values": ["B区1号货架第二层"],
  "expected_sources": [
    {"doc_code": "D01", "record_code": "P01", "unit_key": "sheet:物品位置:row:8"}
  ],
  "relevant_units": [
    {"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}
  ],
  "reference_answer": "城东店的宣传海报在B区1号货架第二层。",
  "should_refuse": false,
  "refusal_reason": null,
  "forbidden_values": [],
  "forbidden_sources": [],
  "expected_pagination": null,
  "requires_ocr": false,
  "labeler": "lead",
  "label_version": "holdout-2026-11-04",
  "notes": ""
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `case_id` | case 唯一 ID（B0 用 `B001`…，Bad Case 用原编号，Holdout 用 `H01`…） |
| `suite` / `split` / `stratum` | 数据集、划分与分层标签；聚合按 `stratum` 与总体分别报告 |
| `business_date` | 该 case 的业务日期（用于 `effective_from/to` 与 `include_future` 判定） |
| `question` / `turns` | 单轮问题；`turns` 非空表示多轮，runner 顺序执行并逐轮记录 Trace，全部轮次通过才算 case 通过 |
| `expected_kind` | 期望结局：`answer` / `clarification` / `no_answer` / `conflict` / `refusal` 等 |
| `expected_values` | 归一化后必须命中的值（exact 契约） |
| `expected_sources` | 允许引用的稳定业务单元（见 §3） |
| `relevant_units` | 检索指标用的相关单元；缺省时由 `expected_sources` 派生 |
| `reference_answer` | 人工参考答案（Ragas Context Recall / Answer Correctness 用）；P0 可为空，P1 Holdout 必须有 |
| `should_refuse` / `refusal_reason` | 拒答样本；`should_refuse=true` 必须有 `refusal_reason` |
| `forbidden_values` / `forbidden_sources` | 泄漏检测：回答不得含这些值 / 不得引用这些来源 |
| `expected_pagination` | 分页契约期望（`total/returned/has_more/next_page`）；无分页为 `null` |
| `requires_ocr` | `true` 时 Replay/Local 明确 `skipped_requires_ocr`，不算通过；只在 P2 live 执行 |
| `labeler` / `label_version` | 标注人与标注版本；`dataset_version` 依赖 `label_version` |
| `notes` | 标注备注（不进入评分） |

字段规则：

- `expected_sources` 只允许 `doc_code` + `unit_key` 或 `locator`；**禁止写 `chunk_id` /
  `unit_id` UUID**。
- `relevant_units` 用于检索指标；缺省时由 `expected_sources` 派生。
- `should_refuse=true` 的 case 可带 `forbidden_values` / `forbidden_sources` 检测泄漏。
- `requires_ocr=true` 在 Replay/Local 不得计为通过，且不得触发真实 OCR。

## 3. 稳定引用解析

```text
doc_code + unit_key  -> 当前索引 RagUnit.unit_id -> 相关 chunk
doc_code + locator   -> 按 kind/sheet/row/heading/page/paragraph 匹配
```

- 解析到 0 个或多个 unit：`GoldUnresolved`，case 状态 `error`，门禁退出码 3；不能随意挑一个 chunk。
- 多个 chunk 命中同一 unit：按 unit 去重后再算 Recall@k / MRR。
- 跨版本比较：优先 `unit_key`；不存在时回退 `locator`。

## 4. 数据集版本

```text
dataset_version = suite:label_version:sha256(canonical JSONL)[:12]
```

- 摘要口径与 Trace 摘要一致：`sha256` 前 12 位十六进制（见 `trace_schema_v0_1.md` §7.2）。
- `label_version` 在数据内容/标注变化时递增；`suite` 区分 `b0` / `badcase` / `holdout`。

## 5. 运行清单绑定

运行清单与每个 `CaseResult` 至少绑定以下版本字段，报告可按任意维度分组：

```text
dataset_version, dataset_sha256, corpus_manifest_sha256, business_date,
index_revision, pipeline_version, gate_version, mode, scope
```

- `pipeline_version` 由 `mktkb.observability.versioning.pipeline_version()` 生成；
- `mode` ∈ `replay` / `local` / `live`（P0 禁止 live）；
- `scope` ∈ `retrieval_only` / `end_to_end`。

## 6. P0 数据集

| 数据集 | 规模 | 来源 | 说明 |
| --- | --- | --- | --- |
| `b0` | 40 题：exact 24 / text 8 / ocr 8 | `fixtures/acceptance/questions.json` | 主回归集 |
| `badcase` | 13 题 | `docs/evidence/LOCAL-R1-20261101/S1-DEV/questions.json` | 单独统计，不进入 Holdout |

P1 数据集：`holdout` 30 题，分层 10 改写/模糊、5 多轮、5 负样本、5 过期/冲突、5 跨文档/安全。

## 7. Holdout 防污染

- Holdout 与 B0 / Bad Case 分文件、分 `split`。
- CLI 默认只输出分层聚合；查看具体 case 需 `--allow-holdout-details`，并写入 `holdout_audit.json`。
- CI / 门禁禁止 `--allow-holdout-details`。
- 失败样本正式转入 Bad Case 后，用新的未见样本补足 Holdout；记录 `retired_from_holdout` /
  `replaced_by`，递增 `label_version`。
- 开发期间不对开发者展示 Holdout 的逐题答案与 Trace。

## 8. 校验要求（Task 4 落地）

- JSONL 每行必须是对象；缺必填字段、字段类型错误 → 加载失败（退出码 3），不静默跳过。
- 同一 `suite` 内 `case_id` 重复 → 加载失败。
- `expected_sources` 出现 UUID 形态的 `chunk_id` / `unit_id` → 加载失败（违反稳定引用契约）。
- `should_refuse=true` 但 `refusal_reason` 为空 → 加载失败。
- `turns` 与 `question` 同时为空 → 加载失败。
