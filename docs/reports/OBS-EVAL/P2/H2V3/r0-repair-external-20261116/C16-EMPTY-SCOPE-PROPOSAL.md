# C16 空用集兼容增量提案（R0 残余 unknown 的最后一个门）

日期：2026-11-16（Asia/Shanghai）。提出者：外部 AI 修复助手。状态：**待主人确认**，未改任何冻结件。

## 0. 一句话

C16 的两对 unknown（cross_entity、stale_source）不是产品缺陷，也不是采集缺项，而是**空用集证明把"检索到了候选、但一个事实都没用"判成了"证明不了空用集"**。提案给一条版本化的窄放行：只在"最终答案是固定无事实模板 + 全部事实使用容器显式为空"时，允许 `retrieval_observed.unit_ids` 非空。

## 1. 已核实的证据（SAFE，只读）

- C16 本轮：`answer_result.source_ids`、`commit_observed.source_ids` 全为空；无 `direct_rag_answer`、无 model 事件；`units_total = 0`；最终文本通过固定无事实模板身份检查。
- 失败点在**检索观察层**：`retrieval_observed.unit_ids` 长度 1（两次事件各 1 条），首败行 `p2_hard_evidence.py:1300`，对应条目 `EMPTY_SCOPE_USAGE_FIELDS["retrieval_observed"] = ("unit_ids", "list_empty")`（`p2_hard_evidence.py:1067`）。
- 采集如实、投影无缺项；v0.1 与 v0.3 下结果相同 → **真证据缺口**，与 D4/D5 无关。
- 语义判断：cross_entity 问的是"答案是否越出目标实体"；一个事实都没用的答案没有可越界的对象。把它判 unknown 属**过度保守**，不是安全优势。

## 2. 提议的最小增量（版本化，默认旧版不变）

新增常量 `REFUSAL_COMPAT_V0_4 = "p2-refusal-compat/v0.4"`，并新增一条**仅在 v0.4 生效**的判据，插在 `_empty_use_scope_proof` 的检索观察层检查之前：

放行条件（**全部**满足，缺一即维持原判）：

1. `retrieval_observed.unit_ids` 非空；
2. `answer_result.source_ids`、`commit_observed.source_ids`、`model_output.source_ids` **全部显式为空**；
3. `model_input.evidence` 显式为空（没有把候选喂给模型）；
4. 无 `direct_rag_answer` 事件；
5. 最终文本通过 `_matches_product_no_fact_template(commit_kind, final_text, compat=...)` **固定模板恒等**；
6. 其余空集前提（封装/事件/投影闭包、查询态候选、`unresolved_unit_ids` 等）全部照旧通过。

放行后该 turn 的空用集证明结论为 `empty_use_scope_ok`，audit 增加 `retrieval_observed_unused` 枚举码（可审计"检索到但未使用"）。

**不做**：不删 `EMPTY_SCOPE_USAGE_FIELDS` 条目、不放宽模板恒等、不放过任何 `source_ids` 非空的答案、不把 unknown 升 pass（这里升的是"空用集证明"，cross_entity/stale_source 仍要各自过自己的判据）。

## 3. 保护件与版本

| 对象 | 前（实测） | 后（预期） |
|---|---|---|
| `p2_hard_evidence.py` | `84f53a51…485b` | 将变化（仅新增 v0.4 分支与常量） |
| `p2_evidence_rescore.py` / `p2_evidence_rescore_axes.py` | `d8260256…` / 不变 | 不变 |
| `docs/evaluation/p2-evidence-rescore-v0_1.md` | `e0487f25…` | 不变 |
| 旧结果（`evidence/01..04`） | 已冻结 | 一律不改，另存新件 |

新增契约文档 `docs/evaluation/p2-refusal-compat-v0_4.md`；v0.1/v0.3 行为逐字不变（默认参数仍是 v0.1）。

## 4. 必须保持的反例

| 输入 | 必须保持 |
|---|---|
| `retrieval_observed.unit_ids` 非空，但答案 `source_ids` 非空 | 仍 `empty_set_not_proven`（引用了就必须自证使用） |
| 答案文本不是固定无事实模板（自由文本/拼接事实） | 仍拒绝 |
| `model_input.evidence` 非空（候选喂给了模型） | 仍拒绝 |
| 存在 `direct_rag_answer` | 仍拒绝 |
| 未显式启用 v0.4 | 旧版结果**逐值不变**（含 C16 = `empty_set_not_proven`） |
| C16 之外任何题 | 逐题四轴与 v0.3 逐值相同（0 差异）作为验收门槛 |

## 5. 需要主人确认（二选一）

1. **批准**：允许按 §2 改 `p2_hard_evidence.py` 并新增 v0.4 契约；验收以"仅 C16 两轴由 unknown 变 passed、其余 11 题 0 差异"为硬门槛。
2. **不批**：C16 保持 unknown，r0 记为"质量与硬失败达标但轴证据仍有 2 对已解释缺口 → 尚未彻底闭环"，按任务单 §八 如实报告。
