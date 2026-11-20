# p2 纯文档正文兼容契约 v0.6（REFUSAL-COMPAT v0_6）

状态：**已获主人 2026-11-17 批准并实施**（派单与边界：`.claude/handoffs/T-R1-108-compat-v06/handoff.md`；
上一版契约：`docs/evaluation/p2-refusal-compat-v0_5.md`）。
实现：`backend/src/mktkb/evaluation/p2_hard_evidence.py`。
本契约**不改** `p2-refusal-compat-v0_3.md` / `v0_4.md` / `v0_5.md` 的任何登记内容、`MATCHER_VERSION`、
阈值、题集、标签、旧分、旧证据、case-plan、评分 harness 与产品代码。

## 0. 一句话

R1 run2 的 C13 第 2 回合是政策题：使用层 8 个单元**全是无实体身份的文档正文**（投影行
`entity_type`/`entity_key` 都为空）。旧实现在 `_check_cross_entity` 末段兜底
（`matched == 0 and not violations and not unknowns`）只能记
`free_text_attribution_unverifiable` → 整题 cross_entity **unknown**。
v0.6 **只**把这一形状记 `not_applicable`；它**沿链继承 v0.5**（v0.6 ⊃ v0.5 ⊃ v0.4 ⊃ v0.3），
v0.5 的空集证明/投影镜像放行在 v0.6 下逐条生效。默认 `p2-refusal-compat/v0.1` 与
v0.1–v0.5 的行为**逐字不变**。

## 1. 版本开关与继承关系

```python
REFUSAL_COMPAT_V0_1 = "p2-refusal-compat/v0.1"   # 现行行为，默认（全部入口）
REFUSAL_COMPAT_V0_3 = "p2-refusal-compat/v0.3"   # 拒答跨层映射 + 安全模板键
REFUSAL_COMPAT_V0_4 = "p2-refusal-compat/v0.4"   # v0.3 + 检索观察到未使用
REFUSAL_COMPAT_V0_5 = "p2-refusal-compat/v0.5"   # v0.4 + 投影 units 镜像检索层
REFUSAL_COMPAT_V0_6 = "p2-refusal-compat/v0.6"   # 本契约：v0.5 + 纯文档正文回合 cross_entity 记 N/A

REFUSAL_COMPAT_INHERITS = {
    "p2-refusal-compat/v0.4": "p2-refusal-compat/v0.3",
    "p2-refusal-compat/v0.5": "p2-refusal-compat/v0.4",
    "p2-refusal-compat/v0.6": "p2-refusal-compat/v0.5",   # 本契约新增（唯一一条）
}
```

| 入口 | 参数 | 默认 |
|---|---|---|
| `classify_case_evidence(..., *, scope_contract=None, compat=REFUSAL_COMPAT_V0_1)` | keyword-only | v0.1 |
| `_classify_turn` / `_check_cross_entity` / `_check_cross_entity_v02` | keyword-only | v0.1 |
| `_document_only_na_enabled(compat)` | 版本门（沿继承链判定） | — |
| `_compat_lineage` / `_compat_table_version` / `_relax_retrieval_enabled` / `_projection_mirror_relaxable` | 继承解析（本次只改后者版本条件） | — |

1. 省略 `compat` == 显式传 `REFUSAL_COMPAT_V0_1`（默认参数值一字未改）。
2. 只有调用方**显式**传 `REFUSAL_COMPAT_V0_6` 才启用本契约的新增项；`recompute_hard_evidence` /
   `run_recompute_cli` 本模块内不接收 `compat`，CLI/外部链默认路径不受影响。
3. 未登记的任意 `compat` 字符串仍等价于 v0.1（`_compat_lineage` 只返回自身，版本门恒 False）。
4. **继承语义（本契约核心）**：`_compat_lineage(v0.6) == (v0.6, v0.5, v0.4, v0.3)`、
   `_compat_table_version(v0.6) == v0.3`（跨层 kind 映射 + 模板额外键逐条等同 v0.3）、
   `_relax_retrieval_enabled(v0.6) is True`（v0.4 检索放行生效）、
   `_projection_mirror_relaxable(..., compat=v0.6)` 与 v0.5 同值（v0.5 投影镜像放行生效）。
   因此 **v0.6 = v0.5 的全部判据 + 纯文档正文回合的 cross_entity N/A**，不存在任何“v0.5 能过、
   v0.6 过不了”的形状。
5. 为了让第 4 条成立，`_projection_mirror_relaxable` 的版本条件由“**精确等于** v0.5”改为
   “v0.5 在 `_compat_lineage(compat)` 上”。该改动对 v0.1/v0.3/v0.4（链上无 v0.5）与 v0.5
   （链上有 v0.5）**逐值等价**，只有 v0.6 因此获得 v0.5 的放行。

## 2. 唯一新增放行：纯文档正文回合的 cross_entity N/A

`_check_cross_entity`（投影/使用层路径，即 `contract_case is None`）末段兜底在以下**全部**成立时
（`_document_only_use_scope`）改记 N/A，缺一维持原判 `free_text_attribution_unverifiable`：

- **a. 版本门**：`_document_only_na_enabled(compat)` 为真（当前 = 显式传 v0.6）；
- **b. 使用层非空**：`_used_unit_layers(events)`（model 证据 / 直接 RAG 事实 / 直接 RAG 引用 /
  最终引用）至少 1 个 unit_id；
- **c. 无 facts**：没有 `direct_rag_answer.facts` 行（有事实就有可核的归属要求）；
- **d. 全部单元无实体身份**：每个用到的 unit_id 都能在 `db_projection.units` 解析，
  且每个解析到的行的 `entity_type` 与 `entity_key` **都**为空。

命中后果：`acc.ref("document_only_use_scope")` + `acc.na(NA_REASONS["cross_entity"])`
（原因沿用既有的 `no_entity_scope_verified`；不新增 NA 原因码）。折叠到题级时
`not_applicable` 表示“该回合没有可核的实体范围”，既不算 passed 也不算证据缺口，
`missing` 为空；`evidence_complete` 不变（这是分析口径，不是采集缺项）。

**除此之外 v0.6 不改任何判据**：空集证明、检索层放行、投影镜像放行、跨层 kind 映射、模板额外键
与四轴其余行为逐值等于 v0.5（§1 第 4–5 条；实证见 §5 的差分断言）。

## 3. 必须保持的反例

| 输入/条件 | 必须保持 |
|---|---|
| 未显式启用 v0.6（默认 / v0.1 / v0.3 / v0.4 / v0.5） | 旧结果**逐值不变**，仍 `unknown/free_text_attribution_unverifiable` |
| 使用层里有一个**有实体身份但不匹配目标**的单元 | 仍 `violation/other_entity_used`（model/RAG 事实层）或 `violation/citation_entity_mismatch`（纯引用层） |
| 只有一个单元匹配目标，其余全为文档正文 | 仍 `passed/frozen_targets_match_ok` |
| 有一个单元只有 `entity_type` 或只有 `entity_key`（半结构化） | 仍 `unknown/entity_identity_unresolved` |
| 用到的 unit_id 在投影里解析不到（`unresolved_unit_ids` / 缺行） | 仍 `unknown/entity_identity_unresolved` |
| 存在 facts（含 `entity_key` 为空的直接 RAG 事实） | 仍 `unknown`（`entity_identity_unresolved` / `free_text_attribution_unverifiable`），不得升 N/A |
| 冻结 targets 缺失或 `entity_key` 为空 | 仍 `unknown/targets_unresolved`（本契约不改变前置顺序） |
| `request_scoped_collection_no_runtime_record_identity` disclosure | 仍 `unknown/request_scope_identity_unverifiable` |
| 用集为空（没有任何使用来源） | 仍走空集证明（`empty_set_not_proven` / `empty_use_scope_ok`），与 v0.6 无关 |

以上每条在 `backend/tests/evaluation/test_r1_108_compat_v06.py` 都有对应断言。

## 4. v0.2 scope 合同路径的边界（本契约不改）

`_check_cross_entity_v02`（`scope_contract` 存在时走这条）**不**享受本放行，原因与证据：

- 该路径**逐单元先出结论**：有身份 → 命中或 `other_entity_used`/`citation_entity_mismatch` 违规；
  无身份 → `shared_background` 覆盖判定（True 记命中，`None`/`False` 记
  `free_text_attribution_unverifiable`）。
- 因此非空使用层**不可能**走到它的末段兜底（那里只可能是防御性代码）；把 v0.6 分支加进去是死代码，
  也会让合同档与无合同档出现两套“纯文档正文”语义。
- 结论：R1 run2 C13 命中的是**无合同**路径（`p2_hard_evidence.py` 末段兜底）；
  若将来用 scope 合同档重算同类回合，它仍会记 unknown——那是合同语义（要求显式登记
  `shared_background` 覆盖）的既有选择，需要另立契约才能改。
  该处的注释已写明“v0.6 规则不在本路径生效”。

## 5. 旧版（v0.1 / v0.3 / v0.4 / v0.5）逐字不变 + v0.6 ≥ v0.5

- 新增内容是**追加**：1 个常量、1 条继承表项（v0.6 → v0.5）、1 个版本门
  `_document_only_na_enabled`、1 个判据 `_document_only_use_scope`、`_check_cross_entity`
  末段兜底内部的一个版本分支 + 1 个审计 ref，v02 路径上一句注释，以及
  `_projection_mirror_relaxable` 的版本条件由精确匹配改为链上判定（对旧版本逐值等价）。
  没有改任何既有常量取值、登记表键集、判据字面量、阈值或原因码。
- v0.1/v0.3/v0.4/v0.5 下版本门恒 False，末段兜底仍走原语句
  `acc.unknown("free_text_attribution_unverifiable", "use_scope")`，逐字等价。
- **v0.6 不回退 v0.5**：
  - C16/C17 形状（投影 `units` 逐值镜像检索层）：`_empty_use_scope_proof(v0.6)` ==
    `_empty_use_scope_proof(v0.5)` == `(True, "empty_use_scope_ok")`；
    `cross_entity` 与 `stale_source` 在 v0.6 与 v0.5 下同为 `passed`（题级 `as_dict()` 全等）。
  - v0.5 的全部空集反例（多/少/重复单位、`message_sources`、`unresolved_unit_ids`、
    查询态候选、各层 `source_ids` 非空、rag 分支、模板不恒等等）在 v0.6 下逐条仍被拒，
    且 reason 与 v0.5 相同（参数化断言 `test_v06_matches_v05_on_all_v05_counterexamples`）。
  - 纯文档回合上 v0.6 与 v0.5 的其余三轴逐值相同，唯一差异是 cross_entity
    `unknown → not_applicable`（`test_v06_na_is_scoped_to_cross_entity_only`）。
- 内容 pin：`backend/tests/evaluation/test_p2_empty_scope_proof.py::FROZEN_SHA` 按该文件既有
  授权更新流程随本次批准字节更新（v0.6 前 `7956b2b7…` → 本次 `9861c44e…`；同日中间的
  “独立档”字节 `82919196…` 未交付、已被取代，注释留档）；其差分测试
  （live `_empty_use_scope_proof` vs 冻结原语）仍全绿，证明空集证明行为未变。
- 实测（2026-11-17，`..\.venv\Scripts\python.exe -m pytest`，工作目录 `backend/`）：

  | 命令目标 | 结果 |
  |---|---|
  | `tests/evaluation/test_p2_hard_evidence.py` | 289 passed、27 errors（**pre-existing 夹具 setup 失败**：`scenario_ingest_invalid`，改动前/后同值，见报告） |
  | 上述 + `test_r1_108_compat_v06.py`（26 条） | 315 passed、27 errors（同上） |
  | `test_r0_repair_refusal_compat.py` `test_r0_repair_c16_empty_scope.py` `test_r0_repair_v05_projection_mirror.py` `test_r0_9_plan_observed_roles.py` `test_p2_empty_scope_proof.py` `test_p2_cross_entity_scope_v02.py` `test_p2_evidence_rescore.py` `test_p2_evidence_rescore_axes.py` `test_r1_108_compat_v06.py` | 340 passed |
  | `test_p2_evidence_axes_adapter_v2.py` `test_p2_capture_entity_readiness_e2e.py` `test_p2_eval_tool_repair.py` | 75 passed |

## 6. 可回退

删除常量 `REFUSAL_COMPAT_V0_6`、继承表项 `REFUSAL_COMPAT_V0_6: REFUSAL_COMPAT_V0_5`、版本门
`_document_only_na_enabled`、判据 `_document_only_use_scope` 与 `_check_cross_entity` 末段那条
`if` 分支（含审计 ref），并把 `_projection_mirror_relaxable` 的版本条件还原为
`compat != REFUSAL_COMPAT_V0_5`，即回到 v0.5 字节；默认参数与所有旧版本路径从未引用 v0.6，
无需回迁。删除 `test_r1_108_compat_v06.py`、本契约文档，并把 `FROZEN_SHA` 的 pin 回退到
`7956b2b7…`（v0.5 批准字节），即完全还原。

## 7. 明确不做 / 未覆盖

- 不把 unknown 一般性升 pass/N/A：只针对“使用层非空、无 facts、全部单元无实体身份”这一形状；
- 不覆盖 facts 回合、半结构化身份、`shared_background` 合同路径（§4）；
- 不引入“文档正文共享背景”白名单、不读 `document_id`/`version_id` 作归属证据；
- 不改 `scorers.py` / `p2_scoring.py` / 评分 harness / 阈值 / 题集 / 标签 / 旧分 / 证据 / case-plan；
- 不在默认路径启用本契约；不给外部重算链新增 `--compat` 取值（链侧若要用 v0.6，需自行增档并自证
  注入次数）；
- 空用集路径本身一字未改：v0.6 只是通过继承让 v0.5 的既有放行继续生效，没有新增可放行形状。
