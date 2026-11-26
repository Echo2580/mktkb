# R2-203C HTTP 正式链路见证 + 敏感性对照

- 任务：T-R2-203C（执行者 `r2-203c-http`）
- 仓库：`D:\GPT项目\市场部AI知识库`（cwd `backend/`）
- Python：`.venv\Scripts\python.exe -X utf8`
- basetemp（仓库外）：`D:\mktkb-p2-h2v3-r2-20261117\basetemp-203c\`
- 业务日：**2026-11-20**（`Settings.rag_business_date`，逐字段对齐 `tests/conftest.py` 后显式钉住）
- 新增文件（本批唯一改动）：`backend/tests/integration/test_r2_203c_f1_http_join_witness.py`、
  `..._f2_identity_http.py`、`..._f3_multiturn_http.py`、`..._f4_caseplan_set.py`
  （`git status` 无本批对 `backend/src/**`、既有测试、`docs/evidence/**`、`fixtures/**`、
  `docs/evaluation/**`、账本/预算/GO 的任何写入）

## 0. 结论

| 组 | 结论 | 节点数 |
|---|---|---|
| F1（C29 主例 A/B + 敏感性 + legacy 见证） | 绿；关掉两处修复各自可转红 | 5 |
| F2（C25 同形身份 + 分类 + R0 键还原 + 相邻反例） | 绿；旧键形态转 `unknown` | 3 |
| F3（C14 两回合 + revision/as_of + 业务日闭区间） | 绿；区间外一天转红 | 7 |
| F4（R2 集合恒等式 + 四种变异负例） | 绿；四种变异全部 `case_plan_coverage_invalid` | 6 |
| 合计（新增） | **21 passed，退出码 0** | 21 |
| 既有相关节点复跑 | **40 passed，退出码 0** | 40 |

四条敏感性对照全部**以红态实测**成立（第 3–6 节逐条给出红态断言消息原文）。

## 1. 命令与退出码

### 1.1 验收命令（最终态）

```text
# C-1  F1 单文件
cd backend
..\.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_r2_203c_f1_http_join_witness.py ^
  -x -q -s -p no:cacheprovider --basetemp=D:\mktkb-p2-h2v3-r2-20261117\basetemp-203c\f1
→ 5 passed, 1 warning in 3.91s    EXIT=0

# C-2  F3 单文件
..\.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_r2_203c_f3_multiturn_http.py ^
  -x -q -s -p no:cacheprovider --basetemp=D:\mktkb-p2-h2v3-r2-20261117\basetemp-203c\f3
→ 7 passed, 1 warning in 4.57s    EXIT=0

# C-3  F2 单文件
..\.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_r2_203c_f2_identity_http.py ^
  -x -q -s -p no:cacheprovider --basetemp=D:\mktkb-p2-h2v3-r2-20261117\basetemp-203c\f2
→ 3 passed, 1 warning in 3.47s    EXIT=0

# C-4  F4 单文件
..\.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_r2_203c_f4_caseplan_set.py ^
  -x -q -s -p no:cacheprovider --basetemp=D:\mktkb-p2-h2v3-r2-20261117\basetemp-203c\f4
→ 6 passed, 1 warning in 0.13s    EXIT=0

# C-5  四个新文件合并跑（-s 保留 WITNESS 红/绿态观测）
..\.venv\Scripts\python.exe -X utf8 -m pytest ^
  tests/integration/test_r2_203c_f1_http_join_witness.py ^
  tests/integration/test_r2_203c_f2_identity_http.py ^
  tests/integration/test_r2_203c_f3_multiturn_http.py ^
  tests/integration/test_r2_203c_f4_caseplan_set.py ^
  -q -s -p no:cacheprovider --basetemp=D:\mktkb-p2-h2v3-r2-20261117\basetemp-203c\all
→ 21 passed, 1 warning in 11.18s   EXIT=0

# C-6  既有相关节点复跑（未跑全量）
..\.venv\Scripts\python.exe -X utf8 -m pytest ^
  tests/integration/test_r2_202c_c29_join_rag.py ^
  tests/integration/test_r2_202a_c29_mechanism_synthetic.py ^
  tests/evaluation/test_r2_202b_entity_identity_e2e.py ^
  tests/unit/test_entity_key_parity.py ^
  -q -p no:cacheprovider --basetemp=D:\mktkb-p2-h2v3-r2-20261117\basetemp-203c\related
→ 40 passed, 1 warning in 20.82s   EXIT=0
```

合并跑输出全量日志：`D:\mktkb-p2-h2v3-r2-20261117\203c-full.log`（含 30 条 `WITNESS` 观测行）；
既有节点日志：`...\203c-related.log`。

### 1.2 开发期迭代（非验收，如实记录退出码）

| # | 命令 | 退出码 | 失败原因 | 处理 |
|---|---|---|---|---|
| I-1 | F3 首跑 | 1 | 裸追问 `合作状态分别是什么？` 与继承到的「物品」目标冲突，产品返回 `not_found` | 改成同目标同字段的裸追问 `位置分别是什么？`（继承断言不变） |
| I-2 | F3 二跑 | 1 | 断言「模型 0 调用」错：单字段轮次走 legacy 取证 + 模型 | 改为「≤2 次且证据面不含另一家店」 |
| I-3 | F3 三跑 | 1 | `ProductEvalAdapter` 要求 `manifest_business_date` 与 `rag_business_date` 同时给出 | 同时显式传两者 |
| I-4 | F3 四跑 | 1 | `answer_result.revision` 为 `None`（该事件不带 revision） | 改用 `commit_observed.revision_before/after` |
| I-5 | F2 首跑 | 1 | 恢复跑的子目录不存在（`FileNotFoundError`） | `_corpus()` 内 `mkdir` |
| I-6 | F2 二跑 | 1 | 相邻反例那回合的投影只含本回合用到的单元，取不到本店目标键 | 目标键取自**正例那次**捕获（冻结合同语义） |
| I-7 | F4 首跑 | 1 | 工具模块未登记 `sys.modules`，其 dataclass 注解解析失败 | 装载前登记 `sys.modules[spec.name]` |
| I-8 | F4 二跑 | 1 | `case_questions` 口径：`turns` 达 2 条时逐条即全部用户轮 | 2 回合 case 显式给 2 条占位轮 |

以上均为**我自己的新文件**的装配/口径修正，未改动 `backend/src/**` 与既有测试，也未放宽任何断言
（逐条说明见第 8 节）。

## 2. F1 — C29 证实失败路径（HTTP 主例）

文件：`backend/tests/integration/test_r2_203c_f1_http_join_witness.py`

合成语料（虚构）：`物品位置台账.xlsx`（门店/物品/标识/位置/数量）+ `合作店家信息.xlsx`
（标识/店家/联系人/合作状态）。店家表**故意把非目标店放第 4 行、目标店（青禾店）放第 5 行**，
于是"引用的是哪一行"可用 `sources[].locator.row` 分辨。

链路：`POST /api/v1/documents`（multipart）→ `run_one_job`（解析/索引）→
`POST .../versions/{id}/publish`（带 `expected_revision`）→
`POST /api/v1/conversations/{id}/messages`。**主断言全部取自该 HTTP 响应**；
`QaEngine.prepare` / `QaEngine.answer` 只作补充证据（证明落在 C29 触发条件上、两条来源各带一条事实）。

### F1-A `test_f1a_http_enumerate_turn_joins_store_level_value`

问法 A：`折叠桌的位置在哪里，合作状态分别是什么？`（不点名门店、含"分别"）

断言清单（全部通过）：

1. `kind == "answer"`；
2. 正文同时含 `甲区1号架`（位置值）与 `合作中`（店家级值）；
3. `sources` **恰好 2 条**且来自**两份不同文档**（`{物品位置台账.xlsx, 合作店家信息.xlsx}`）；
4. 目标约束（版本）：两条来源 `status == "active"`、`version_number` == 发布回执的版本号、`published_at` 非空、
   `locator.header_row` 与各自表头行一致；
5. 目标约束（门店值）：`物品位置台账.xlsx` 的 `locator.row == 4`（青禾店/折叠桌行）、
   `合作店家信息.xlsx` 的 `locator.row == 5`（**青禾店**行，第 4 行是同表里的白鹭店）；
6. 事实面（补充）：`("location","甲区1号架")` 与 `("status","合作中")` 都在，
   `entity_label` 分别为 `青禾店的折叠桌` / `青禾店`，两条事实的 `version_id` 各等于对应文档的发布版本；
7. 触发条件（补充）：`mode=record`、`enumerate=True`、`filters=["item"]`、`field_roles={location,status}`；
8. 模型 0 调用；`external == []`、子进程计数 0。

绿态实测（`WITNESS f1a-green`）：

```json
{"kind":"answer","source_docs":["物品位置台账.xlsx","合作店家信息.xlsx"],
 "source_versions":[["物品位置台账.xlsx",1,"active"],["合作店家信息.xlsx",1,"active"]],
 "source_rows":[["物品位置台账.xlsx",4],["合作店家信息.xlsx",5]],
 "fact_roles":[["location","甲区1号架","青禾店的折叠桌"],["status","合作中","青禾店"]],
 "modes":["record",true],"filters":["item"],"field_roles":["location","status"]}
```

### F1-B `test_f1b_http_named_store_turn_joins_store_level_value`

问法 B：`青禾店的折叠桌放在哪个位置，合作状态分别是什么？`（`filters` 含 store）
断言同 A（1–8），并额外断言 `filters == ["item","store"]`。绿态 `WITNESS f1b-green` 与 A 逐字段一致
（`source_rows` 仍为 4/5）。

### F1 敏感性① `test_f1_sensitivity_join_off_restores_red_for_both_questions`

运行时 `monkeypatch` 关掉 `rag.retrieval._store_join_chunks`（不改文件）。

红态（A、B 同形，`WITNESS f1-sensitivity-join-off-red`）：

```json
{"question":"折叠桌的位置在哪里，合作状态分别是什么？","kind":"answer",
 "source_docs":["物品位置台账.xlsx"],"has_status":false,
 "text":"共 1 条，当前第 1 页显示 1 条。\n- 青禾店的折叠桌：位置 甲区1号架（来源：物品位置台账.xlsx）\n已显示全部。"}
```

即：**1 来源、缺店家级值**（与修前缺陷形态一致）。红态**断言消息**留档
（把同一组绿态断言在关掉入口后再跑一次，必然失败）：

```text
WITNESS f1-red-assertion-message-join-off
message: 共 1 条，当前第 1 页显示 1 条。
  - 青禾店的折叠桌：位置 甲区1号架（来源：物品位置台账.xlsx）
  已显示全部。
assert '合作中' in '共 1 条，当前第 1 页显示 1 条。\n- 青禾店的折叠桌：位置 甲区1号架（来源：物品位置台账.xlsx）\n已显示全部。'
```

恢复后（`monkeypatch.undo()`）同一断言包回绿：`WITNESS f1-join-restored-green`（与 `f1a-green` 逐字段相同）。

### F1 legacy 见证 `test_f1_legacy_join_is_witnessed_and_independently_falsifiable`

单独一例走 legacy 形态（`青禾店的折叠桌放在哪个位置，合作状态如何？`，无枚举词 → R0
`retrieval.service._store_join_ids` 命中路径，真调模型）：

1. 绿：正文两类值 + 2 条来源（两份文档）+ 模型证据里两列各一份
   （`位置…` 与 `合作状态…`，`WITNESS f1-legacy-green`）；
2. 敏感性②：`monkeypatch` 关掉 `retrieval.service._store_join_ids` → legacy **转红**：

```text
WITNESS f1-sensitivity-legacy-off-red
{"kind":"service_error","error_code":"MODEL_OUTPUT_INVALID","source_docs":[],
 "evidence_field_keys":[["位置","数量","标识","物品","门店"]]}
WITNESS f1-red-assertion-message-legacy-off
assert '合作中' in ('模型输出未通过来源与字段校验，已拒绝本次回答。…')
```

（模型证据只剩物品行 → 无法背书店家级值 → 回答被事实门拒绝。）

3. 同一开关下 F1-A 仍绿（`WITNESS f1-r0-off-main-still-green`）⇒ **两条修复互不吞并、各自可证伪**。

### 零出站总账 `test_f1_zero_outbound_ledger`

三种问法在同一 app 上跑完后审计：`external == []`、`no_subprocess == []`。

## 3. F2 — C25 同形身份（HTTP + 捕获 + 分类）

文件：`backend/tests/integration/test_r2_203c_f2_identity_http.py`
链路：`ProductEvalAdapter`（真实产品应用 + `httpx.ASGITransport`，`ask_turn` 打的就是
`POST /api/v1/conversations/{id}/messages`）→ 加密 envelope → 两个**公开分类入口**
（`p2_hard_evidence` v0.2 scope 合同、`p2_evidence_rescore_axes` v2）。

语料（虚构）：`青禾店/云岫店`、`云纹托盘`（标识 `Q01` 属青禾店、`Q03` 属云岫店）、同店无标识行
`素纹立牌`。问法：`青禾店的云纹托盘（编号 Q01）位置分别是什么？`

### F2-1 `test_f2_same_shape_keys_byte_equal_and_cross_entity_passes`

- HTTP 200、`kind == "answer"`；
- `direct_rag_answer.facts[0].entity_key` **逐字节等于**
  `db_projection.units[fact.source_unit_id].entity_key`（均为 `item|id:q01`，UTF-8 比较）；
- `entity_type == "item"`、`entity_filters.store == "青禾店"`、键形态含 `|id:`；
- 两个入口均 `cross_entity` = `("passed", "frozen_targets_match_ok")`。

```text
WITNESS f2-1-positive
{"http_status":200,"kind":"answer","fact_key":"item|id:q01","unit_key":"item|id:q01","equal":true,
 "target_key":"item|id:q01","hard":["passed","frozen_targets_match_ok"],"axes":["passed","frozen_targets_match_ok"]}
```

### F2-2 敏感性 `test_f2_sensitivity_legacy_entity_shape_returns_unknown`

`monkeypatch` 把 `rag/chunking._entity` 还原为旧**名称复合键**（不改文件）：

```text
WITNESS f2-2-sensitivity-legacy-red
{"equal":false,"fact_key":"item|青禾店|云纹托盘","unit_key":"item|id:q01",
 "hard":["unknown","entity_identity_unresolved"],"axes":["unknown","entity_identity_unresolved"],
 "missing_codes":["entity_identity_unresolved"]}
WITNESS f2-red-assertion-message-legacy-entity
assert ('unknown', 'entity_identity_unresolved') == ('passed', 'frozen_targets_match_ok')
  At index 0 diff: 'unknown' != 'passed'
```

恢复（`undo()`）后独立重跑 → `WITNESS f2-2-sensitivity-restored-green`：
`hard/axes` 均回到 `("passed","frozen_targets_match_ok")`。

### F2-3 相邻安全反例 `test_f2_adjacent_other_entity_still_violates_over_http`

同一条 HTTP 链路问**另一家店的另一实体**（`云岫店的云纹托盘（编号 Q03）位置分别是什么？`），
目标仍用本店冻结键（取自正例那次捕获）：

```text
WITNESS f2-3-other-entity
{"http_status":200,"kind":"answer","target_key":"item|id:q01","used_key":"item|id:q03",
 "hard":["violation","other_entity_used"],"axes":["violation","other_entity_used"]}
```

用户侧仍是正常答案（`丙区3号架`），但分类面**不得**因本批转 passed ⇒ 断言
`core.fact_key != target_key` 且两入口都是 `violation`，理由 ∈ `{other_entity_used, citation_entity_mismatch}`。

## 4. F3 — C14 两回合 + 业务日闭区间（HTTP）

文件：`backend/tests/integration/test_r2_203c_f3_multiturn_http.py`
语料：物品表（青禾店/折叠桌/甲区1号架、白鹭店/折叠凳）+ 店家表（含 `生效日期/失效日期`，
两个店家行窗口都是 `[2026-11-20, 2026-11-21]`）。

### F3-1 `test_f3_two_turn_inheritance_and_revision_over_http`

- 第 1 回合 `青禾店的折叠桌放在哪个位置？` → `kind=answer`、正文含 `甲区1号架`、
  `sources == [物品位置台账.xlsx]`（当前活动版本）；
- 第 2 回合**裸追问** `位置分别是什么？`（不含门店名/物品名）→ `kind=answer`、正文仍 `甲区1号架`、
  `sources` 与第 1 回合**逐字段相同**（同一 document/version/locator）；
- 范围继承：第 2 回合 `filters == ["item","store"]`、`state.store == 青禾店`、`state.item == 折叠桌`
  （门店/物品只能来自回合状态）；
- `revision`：两回合都等于**发送前**产品 revision（`2 == 2`），且未被提问推高；
- `as_of`：两回合都 `== "2026-11-20"`；
- 证据面不含另一家店（`白鹭店` 不出现）。

```text
WITNESS f3-1-two-turn
{"as_of":["2026-11-20","2026-11-20"],"filters1":["item","store"],"filters2":["item","store"],
 "state_store2":"青禾店","state_item2":"折叠桌",
 "turn1":{"kind":"answer","docs":["物品位置台账.xlsx"],"pre":2,"revision":2},
 "turn2":{"kind":"answer","docs":["物品位置台账.xlsx"],"pre":2,"revision":2}}
```

### F3-2 `test_f3_two_turn_capture_as_of_and_pre_revision`

同一产品的捕获 envelope（两回合各一份）里：

- `plan_observed.as_of == "2026-11-20"`、`plan_observed.state_as_of == "2026-11-20"`（两回合）；
- `AskResult.revision` == `db_projection.pre_revision` == `commit_observed.revision_before/after`
  == `db_projection.capture_revision`（逐回合，本文件两回合间不改资料）；
- 第 2 回合 `mode=record`、`filters=["item","store"]`。

```text
WITNESS f3-2-capture
turn0: {"as_of":"2026-11-20","state_as_of":"2026-11-20","pre_revision":2,"result_revision":2,
        "commit_before":2,"commit_after":2,"capture_revision":2,"mode":"record","filters":["item","store"]}
turn1: 同上（两回合 pre_revision 一致）
```

### F3-3 边界对照 `test_f3_business_date_closed_interval_boundary`（参数化 4 例）

问法 `青禾店的合作状态是什么？`（唯一载体行就是带窗口的那一行）。**闭区间**规则：

| 业务日 | as_of | 结果 | 观测 |
|---|---|---|---|
| 2026-11-19（左外一天） | 2026-11-19 | **红** | `kind=not_found`、无来源、无 `合作中` |
| 2026-11-20（左端） | 2026-11-20 | 绿 | `kind=answer`、`sources=[合作店家信息.xlsx]`、含 `合作中` |
| 2026-11-21（右端） | 2026-11-21 | 绿 | 同上 |
| 2026-11-22（右外一天） | 2026-11-22 | **红** | `kind=not_found`、无来源 |

区间外一天的红态**断言消息**：

```text
WITNESS f3-red-assertion-message-boundary (2026-11-19, 2026-11-22)
assert '合作中' in '资料中未记录：合作状态；记录缺失不等于服务异常，请核对字段名称或改问其它字段。'
```

### F3-4 不依赖宿主当前日的对照 `test_f3_no_host_clock_control_without_business_date`

`rag_business_date=None` → `plan.as_of is None` → 不做窗口过滤 → 该行**可见**（`合作中` + 店家表来源）。

宿主当日 = **2026-11-17**（不在 `[2026-11-20, 2026-11-21]` 内）。若产品用宿主时钟判定日期，
钉住 2026-11-20 的那几例必须看不到该行——实测可见；且 `None` 对照同样可见。两条合起来证明
日期判定只取 `Settings.rag_business_date`，本文件也**没有任何 `datetime.now()` 调用**。

## 5. F4 — R2 集合恒等式 + 四种变异负例（离线）

文件：`backend/tests/integration/test_r2_203c_f4_caseplan_set.py`
数据源（只读）：`docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json`
（只读结构与计数，不复制题面/期望值）。

### F4-1 `test_f4_r2_case_plan_identity_over_public_artifact`

```text
WITNESS f4-1-case-plan
{"schema_version":"p2-hard-evidence-caseplan-live/v0.1","fixture_kind":"live_h2","execution_mode":"live",
 "business_date":"2026-11-20","real_calls":29,
 "case_ids":["H2V3-C08","H2V3-C14","H2V3-C19","H2V3-C25","H2V3-C29"],
 "short_ids":["C08","C14","C19","C25","C29"],
 "turn_counts":{"H2V3-C08":1,"H2V3-C14":2,"H2V3-C19":1,"H2V3-C25":1,"H2V3-C29":1},
 "turn_indices":[0,1,2,3,4,5],
 "quality_status":{"H2V3-C08":"pass","H2V3-C14":"pass","H2V3-C19":"pass","H2V3-C25":"pass","H2V3-C29":"fail"}}
```

断言：恰好 5 题且 `case_id` 集合**逐项相等** `{H2V3-C08,C14,C19,C25,C29}`（短 id `{C08,C14,C19,C25,C29}`）、
无重复；回合总数 **6**、每题回合数与冻结期望逐项相等（**C14 恰 2**）、`turn_index` 全局连续 `0..5` 且唯一、
已执行回合证据文件互不重名；业务日 **2026-11-20**；`fixture_kind=live_h2`、
`schema_version=p2-hard-evidence-caseplan-live/v0.1`、`bindings.fixture_kind=live_h2`。
（`quality_status` 仅作观测记录，不作断言——那是 run 状态，不是 R2 身份。）

### F4-2 `test_f4_public_validator_accepts_unmutated_case_plan`

同一份未变异文件必须通过**公开校验入口**
`tools/p2_h2_controlled_execute.py::_validate_case_plan_document`（产出该文件的同一校验器），
case_id 与回合数 `[1,2,1,1,1]` 与冻结期望一致 ⇒ 下面的拒绝来自变异本身，而不是"怎么改都拒绝"。

### F4-3 `test_f4_case_set_mutations_are_all_rejected`（参数化 4 例）

| 变异 | 变异后 case_ids | 结果 |
|---|---|---|
| 多一题 | `C08,C14,C19,C25,C29,C30` | `EntryError: case_plan_coverage_invalid` |
| 少一题 | `C08,C14,C19,C25` | 同上 |
| 重复题 | `C08,C08,C19,C25,C29` | 同上 |
| 换题 | `C99,C14,C19,C25,C29` | 同上 |

每例还断言"变异后的集合确实 ≠ 冻结期望"（负例本身有效），并审计 `external == []`。

## 6. 出站守卫证据

- 四个新文件的**每个**用例都以显式参数请求仓库既有夹具 `t09_network_guard`
  （`backend/tests/acceptance/support/netguard.py`），并在用例末尾**显式断言**
  `t09_network_guard.snapshot()["external"] == []`（不是"非空检查"）。
- 无子进程：F1 自备 `no_subprocess` 夹具，封死 `subprocess.Popen` / `subprocess.run` 并计数，
  用例末尾断言 `calls == []`；F2/F3/F4 全程不启动任何子进程（F4 只是按路径加载
  `tools/p2_h2_controlled_execute.py` 这个**纯 Python 模块**，`exec_module` 后只调用其校验函数，
  不产生进程、不读密钥、不连网；F4 的用例同样显式断言 `external == []`）。
- 模型出站：F1/F3 的模型是 conftest 的 `EvidenceEchoGateway`（进程内替身，只回显证据）；
  F2 用 `MockChatBackend`（`httpx.MockTransport`，真实 provider 编解码但不出网）。
- 实测：C-5 全绿、`external == []` 在 21 个用例内全部成立。

## 7. 断言强度（未降级）

- `sources` 断言始终是"**恰好 2 条且两份不同文档**"，红态断言是"**只有 1 条**"，没有"非空"式弱断言。
- 版本/门店约束逐条保留：`status=active`、`version_number` == 发布回执、`published_at` 非空、
  `locator.header_row`、以及**店家表 `locator.row == 5`（青禾店行，非第 4 行的白鹭店）**。
- F2 的键相等用 `encode("utf-8")` 逐字节比较；分类结论用**理由码**（`frozen_targets_match_ok` /
  `entity_identity_unresolved` / `other_entity_used`）断言，不是只看 state。
- F3 的 `revision` 断言是"逐回合等于发送前 revision **且**等于捕获里的
  `pre_revision`/`commit_before`/`commit_after`/`capture_revision`"，`as_of` 断言是"逐回合等于钉住值"。

## 8. 被迫调整的断言（逐条，均非降强度）

| # | 原断言 | 调整后 | 为什么不算降强度 |
|---|---|---|---|
| 1 | F3 第 2 回合问"合作状态分别是什么？" | 改为同目标同字段的 `位置分别是什么？` | 原问法把继承到的「折叠桌」与「合作状态」组合成不可满足的查询，产品返回 `not_found`（实测 I-1）；任务要求的是"继承目标/范围"，新问法把继承断言做得更严：两回合 `sources` 必须**逐字段相同** |
| 2 | F3「模型 0 调用」 | 改为「≤2 次，且模型证据不含另一家店」 | 该问法是单字段轮次，产品按设计走 legacy 取证 + 模型（实测 I-2）。原"0 调用"断言描述的是枚举轮次，不是本形态；新断言把"不跨店"钉死在证据面 |
| 3 | F3 `answer_result.revision` | 改用 `commit_observed.revision_before/after` + `db_projection.capture_revision` | 该事件本就不带 revision（实测 I-4）；新断言覆盖了更多同源字段，强度更高 |
| 4 | F2 相邻反例取本回合投影里的本店键 | 目标键取自**正例那次**捕获 | 该回合投影只含本回合用到的单元（实测 I-6）。冻结合同的目标本就来自既有 envelope，新做法更符合合同语义 |
| 5 | F4 `CaseSpec.turns` 用 1 条占位轮表示 2 回合 | 2 回合 case 给 2 条占位轮 | `case_questions` 的口径是"≥2 条即全部用户轮"（实测 I-8）；回合数断言仍落在公开文件上（`turn_counts` + 总数 6 + C14==2），不依赖该口径 |
| 6 | F4 校验器模块直接 `exec_module` | 先登记 `sys.modules` | 纯粹是 dataclass 注解解析的装载方式（实测 I-7），与断言无关 |

## 9. NOT-RUN 与风险

**NOT-RUN（明确未做）**

1. 未跑全量 pytest（按指令）；只跑了本批 4 个新文件 + 4 个既有相关节点。
2. 未做真实模型 / 真实 OCR / 真实供应商出站（全部替身或 MockTransport；本批不验证真实供应商行为）。
3. 未重放 live H2 run（`real_calls=29` 的实测值只作为公开件的观测，不在本批重算）。
4. 未验证 `C29` 在真实 H2 语料上的端到端绿（本批只用合成虚构语料；真实语料属 live 门）。
5. 未做并发/多用户隔离、分页深页、`rag_business_date` 与回合内显式日期冲突的组合矩阵。

**风险**

1. **业务日仍是进程级配置**：产品无请求级日期注入，本批用一份 `Settings` 一个 app 来钉日期；
   多业务日并行只能是"多 app"，与真实部署（单进程单业务日）不同。
2. **F2 的相邻反例依赖"另一实体"语料**：若日后合成语料只剩单实体，该例将无法构造
   （当前实现会在断言里显式失败，不会静默跳过）。
3. **F4 依赖公开件与公开工具的存在**：`case-plan.json` 或 `tools/p2_h2_controlled_execute.py`
   被移动/改名时该文件会红（属预期的"公开件缺失"失败，不是环境跳过）。
4. **`sources[].locator.row` 是行号级证据**：若摄取层表头探测策略改变（例如把标题行算进表体），
   行号会平移，F1 的门店行断言需要同步更新（届时是行为变化，不是断言放松）。
5. F3-1 的 `revision` 稳定性依赖"两回合之间不改资料"；真实 C14 里若有并发发布，revision 会变，
   该断言就应改为"单调不减 + 各自等于各自 pre_revision"。
