# R0-CAPTURE-DROP：`retrieval_observed.candidate_dropped_reason`（C12 候选丢弃原因采集）

日期：2026-11-16　范围：**离线实现 + 测试，未发真实请求**　结论：**已交付，无需改冻结件**

## 1. 结论

- `retrieval_observed` 新增一枚**可选**枚举码 `candidate_dropped_reason`（`str | None`），取值只允许
  `filter_miss` / `kind_miss` / `term_miss` / `vector_unavailable` / `dedup_dropped` /
  `limit_dropped` / `no_drop` / `not_applicable`；不含正文/字段中文名/实体/值。
- 检索侧只接受可选 `diag` 字典写码：**默认 `None` 时不建键、不改控制流、不新增查询**；qa 侧按固定
  优先级 `kind_miss > term_miss > vector_unavailable > filter_miss > dedup_dropped > limit_dropped`
  合成一个值随事件发出；观察关闭时不构造 `diag`（`capture_enabled()` 门）。
- 局限（供下一轮定性）：C12 这类记录型意图 `intent.terms` 为空（结构性），记录面 `lexical` 必记
  `term_miss`，而正文面 `exact` 的结构性 `kind_miss` 按设计不参与合成 ⇒ 实际 run 该字段会稳定读到
  `term_miss`，只能确认词面这一环，不能单独区分正文面原因；若要区分，建议下一增量加**按面**可选键，
  而不是改既有优先级（可选键不升版）。

## 2. 改动清单（逐文件:行）

| 文件 | 行 | 改动 |
| --- | --- | --- |
| `backend/src/mktkb/observability/evaluation_capture.py` | 166-168 | 登记 `candidate_dropped_reason: _Field(_OPT_STR, required=False)`（唯一新键） |
| 同上 | 234-253 | `CANDIDATE_DROP_REASONS`（8 码闭集）+ `_ENUM_VALUES`（枚举约束唯一落点） |
| 同上 | 506-509 | 既有清洗路径内校验：未知码 → `candidate_dropped_reason_not_in_enum`（fail-closed） |
| `backend/src/mktkb/rag/retrieval.py` | 31-39 | `search(..., *, limit=None, diag=None)` + 写码契约说明 |
| 同上 | 62-63 | 非 record 计划的精确通道 → `diag["exact"]="kind_miss"` |
| 同上 | 78-79 | `match_expression(())` 为空 → `diag["lexical"]="term_miss"` |
| 同上 | 96-98 | 向量通道报错/关闭 → `diag["vector"]="vector_unavailable"` |
| 同上 | 107-108、114 | `diag` 传入 `_fuse` / `_enumerate_base` |
| 同上 | 121-122、131-132 | 枚举分页截断 / `fused[:top_k]` 截断 → `diag["limit"]="limit_dropped"` |
| 同上 | 329-335、449-450 | `_vector_recall(..., diag=None)`；向量窗口按配置截断 → `limit_dropped` |
| 同上 | 498-506、533-534 | `_fuse(..., diag=None)`；硬过滤真丢候选 → `diag["filter"]="filter_miss"` |
| 同上 | 594-598、611-612 | `_enumerate_base(..., diag=None)`；同一记录单元多 chunk 归并 → `dedup_dropped` |
| `backend/src/mktkb/rag/index.py` | 776-785 | `RagIndex.search(..., diag=None)` 透传（关键字可选） |
| `backend/src/mktkb/qa/service.py` | 55-73 | `CANDIDATE_DROP_PRIORITY` 固定序 + `_merge_candidate_drop_reason` |
| 同上 | 502-505 | `QaEngine.search(..., diag=None)` 透传 |
| 同上 | 545-590 | 记录面/正文面各建 `diag`，正文面 pop 结构性 `exact`，合成后随事件发出 |
| `backend/tests/evaluation/test_r0_12_candidate_drop_reason.py` | 新增 | 协议/枚举/旧 envelope/合成/优先级/冻结闭包（30 用例） |
| `backend/tests/rag/test_r0_12_candidate_drop_reason_retrieval.py` | 新增 | `search` 各早退/丢弃点固定码 + 无 diag 逐值不变（8 用例） |

去重口径：`dedup_dropped` 只记“同一记录单元多 chunk 归并”（真实减少候选行）；同一 chunk 跨通道重复
不算丢弃。FTS `no rows` / SQL `LIMIT candidate_limit` 侧截断不计数（需新增查询，违反诊断不改行为）。

## 3. 兼容性论证

1. **可选键**：缺键时 `clean_event_payload` 直接 `continue`，不合成键 ⇒ 旧 payload 清洗结果逐值相同
   （用例断言 `cleaned == 6 键旧载荷`，`emit` 后事件键集不变）。
2. **冻结件无需改**：`p2_hard_evidence.py` / `p2_empty_scope_proof.py` 从
   `EVENT_FIELDS` / `clean_event_payload` 动态读白名单（用例断言 `hard.CAPTURE_EVENT_FIELDS is
   cap.EVENT_FIELDS`）；旧 envelope 结论逐值不变，带合法新键的 envelope 仍 `empty_use_scope_ok`，
   非枚举值被同一清洗口径拒。`p2_evidence_capture.py` 只按需读 payload 既有键，新键不影响投影。
3. **不升版**：`CAPTURE_SCHEMA_VERSION` 仍 `mktkb.eval-capture/v0.1`（用例 pin）；无需升版。
4. **行为不变**：`diag=None` 时全部写码分支被 `diag is not None` 挡住，不新增查询/排序/截断；同一输入
   `diag=None` 与 `diag={}` 的 exact/lexical/vector/fused/evidence/计数/分页/降级投影逐值相同。

## 4. 红 → 绿

- **红（实现前，同一命令）**：27 failed / 11 passed。代表错误：
  `TypeError: RagIndex.search() got an unexpected keyword argument 'diag'`；
  `assert 'candidate_dropped_reason' in {'request_id','scope','unit_ids','candidate','truncated','empty'}`。
- **绿（实现后）**：38 passed（evaluation 30 + rag 8），无 skip/xfail。

## 5. 测试统计

| 批次 | 结果 |
| --- | --- |
| 新用例 `evaluation/test_r0_12_candidate_drop_reason.py` | **30 passed** |
| 新用例 `rag/test_r0_12_candidate_drop_reason_retrieval.py` | **8 passed** |
| `tests/rag` + `unit/test_retrieval.py` + `unit/test_conversations.py` | 583 passed / 1 failed（**已知** `test_s4_stage_limit.py` 40 vs 20） |
| `integration/test_visible_index.py` + `tests/observability` + `evaluation/test_p2_empty_scope_proof.py` | 482 passed / 1 failed（**已知** `test_paths_e2e.py::test_legacy_parse_early_not_found_is_reason_aware[...]`：工作树在途 `query.py` 的 `SECURITY_RESTRICTED_CONTACT` 使 path 变 rag，见 `R0-CAPTURE-ROLES.md:51`、`R0-CASE-MATRIX.md:218`，非本单改动） |
| 额外采集/快照兼容（仓库外 basetemp） | `test_p2_evidence_capture` 15、`test_p2_capture_contract_v02` 8、`test_p2_evidence_snapshot_v03` 26 全绿（仓库内 basetemp 被“证据根必须在仓库外”策略拒绝，属环境约束） |
| 其它在途交叉用例 | `test_r0_9_plan_observed_roles` 20、`test_r0_repair_c16_empty_scope` 29、`test_r0_repair_v05_projection_mirror` 36 全绿 |

命令：`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"; .\.venv\Scripts\python.exe -B -m pytest <路径> -q
-p no:cacheprovider --basetemp backend\.pytest-tmp\capdrop`；离线闸门（`t09_network_guard`）+ 正对照
（`getaddrinfo` 被拦），本轮真实出站 0。未读私有材料、未 `git add/commit/stash/reset/checkout/clean`。

## 6. 是否需要改冻结件

**不需要。** 本单未改 `evaluation/p2_*.py`、`docs/evaluation/*`、`fixtures/`、账本、预算、旧证据、
case-plan；加键通过共享白名单自动进入冻结闭包（§3.2 用例已证）。仅改产品侧 4 个文件 + 新增 2 个测试
文件；工作树其余在途改动未触碰。

## 7. 第二增量：按面丢弃原因（`candidate_dropped_reason_record` / `candidate_dropped_reason_document`）

日期：2026-11-16　范围：**离线实现 + 测试，未发真实请求**　结论：**已交付，无需改冻结件**

### 7.1 结论与动机

§1 的合成值把记录面 + 正文面**压成一个码**：记录型意图 `intent.terms` 结构性为空 ⇒ 记录面必记
`term_miss`；而正文面（document 计划）的结构性 `kind_miss` 按设计不参与合成 ⇒ 一次真实 run 只能
稳定读到 `term_miss`，无法定位 C12。本增量**不改**已落地语义，只让同一事件按面各带一枚可选键：

| 键 | 类型 | 取值 | 语义 |
| --- | --- | --- | --- |
| `candidate_dropped_reason_record` | `str \| None` | 同一 8 码闭集 | 记录面（主计划）的丢弃原因 |
| `candidate_dropped_reason_document` | `str \| None` | 同一 8 码闭集 | 正文面（记录型意图的正文补齐计划）的丢弃原因 |

- 合成值 `candidate_dropped_reason` **逐值不变**（优先级仍是 `kind_miss > term_miss > …`）；
  按面码可由两面各取一次同一优先级、再按同一优先级复算回合成值（用例已 pin）。
- 记录面的结构性 `term_miss` 在**按面键**里如实保留（它就是事实）；正文面仍是 document 计划，
  其结构性 `exact=kind_miss` 继续按设计 pop，不进入任何一面。
- 本轮未参与的面记 `not_applicable`：`mode="document"` 的记录面（唯一一面归 document）、
  未知模式的两面，均与合成值既有口径一致。
- 三键共用同一份 `CANDIDATE_DROP_REASONS` 与同一条 `clean_event_payload` 清洗路径（不复制码表），
  `CAPTURE_SCHEMA_VERSION` 不变。

### 7.2 改动清单（逐文件:行）

| 文件 | 行 | 改动 |
| --- | --- | --- |
| `backend/src/mktkb/observability/evaluation_capture.py` | 169-172 | `retrieval_observed` 增登记两枚 `_Field(_OPT_STR, required=False)` 按面键 |
| 同上 | 253-260 | `_ENUM_VALUES` 增两条，值直接复用 `CANDIDATE_DROP_REASONS`（同一 `frozenset` 对象，无第二份码表） |
| `backend/src/mktkb/qa/service.py` | 76-80 | `CANDIDATE_DROP_FACE_FIELDS`：两个按面键名的唯一字面量落点 |
| 同上 | 83-115 | `_face_candidate_drop_reason`（单面码；`diag=None` = 未观测 → `not_applicable`）+ `_face_candidate_drop_reasons`（按 `mode` 拆两面，不参与 = `not_applicable`） |
| 同上 | 592 | `document_diag` 初始化提前到分支外（控制流不变：正文面仍只在 `mode=="record"` 建） |
| 同上 | 617-638 | `capture_enabled()` 分支内先算 `face_reasons`，与合成值在**同一次** `emit_capture_event` 发出（`**face_reasons`）；观察关闭仍不发事件 |
| `backend/tests/evaluation/test_r0_12_candidate_drop_reason.py` | 467-693 | 第二增量 44 用例（协议登记/枚举闭集/按面拆分/合成一致性/观察关闭/冻结闭包） |

**采用的最小调整**：没有改合成优先级（§1 的 `CANDIDATE_DROP_PRIORITY` 原样）。按面键只把两面各自的
`diag` 折一次，仍用同一优先级函数 ⇒ 合成值可由按面码复算，不存在“改前改后两套语义”。
`mode="document"` 的 record 面记 `not_applicable`（而不是把唯一一面挂到 record）是刻意选择：
键名必须与事实相符，否则下一轮又会误读一面。

### 7.3 红 → 绿

- **红（实现前，同一命令）**：`-k face` → **25 failed / 19 passed / 28 deselected**。代表错误：
  `AssertionError: candidate_dropped_reason_record`（`EVENT_FIELDS` 未登记，`R0-CAPTURE-DROP.md` §7.2 行 1）；
  `KeyError: 'candidate_dropped_reason_record'`（真实事件只带合成值，缺按面键）；
  `test_frozen_closures_accept_face_keys_without_changes` 断言按面键不在共享白名单。
  当时 19 passed 的构成：16 条 `clean_rejects_face_values_outside_enum`（“未知字段”本来也 fail-closed）
  + 2 条旧用例（名字含 `face`：`..._absent_exact_face`、`two_face_recall_...`）+ `faces_are_not_built_when_capture_is_closed`。
  说明 fail-closed 本身不是新增能力，**枚举闭集**才是本增量要 pin 的点。
- **绿**：`test_r0_12_candidate_drop_reason.py` **74 passed**（既有 30 + 新增 44）。
  实现后补的 2 条枚举报文用例断言 `candidate_dropped_reason_{record,document}_not_in_enum`；
  改前该键未登记只会得到 `unknown_event_fields`（不含该子串），故这两条同样先红后绿。

### 7.4 测试统计

| 批次 | 结果 |
| --- | --- |
| `backend/tests/evaluation/test_r0_12_candidate_drop_reason.py` | **74 passed**（30 旧 + 44 新） |
| `tests/observability` + `tests/rag` + 上述文件 + `test_p2_empty_scope_proof.py` | **1050 passed / 2 failed**（均为已知，见 §5 行 3：`test_s4_stage_limit.py` 40 vs 20；`test_paths_e2e.py::test_legacy_parse_early_not_found_is_reason_aware[...]` 的 path 被工作树在途 `query.py` 判成 rag） |
| 采集契约/冻结闭包（**仓库外** basetemp）：`test_p2_evidence_capture` + `test_p2_capture_contract_v02` + `test_p2_hard_evidence` | **339 passed** |
| 快照/适配器消费面（**仓库外** basetemp）：`test_p2_evidence_snapshot_v03` + `test_p2_eval_tool_repair_e2e` + `unit/test_conversations.py` | **84 passed** |
| C12 正文面：`integration/test_r0_c12_text_face_recall_synthetic.py` + `rag/test_r0_c12_text_face_recall_synthetic.py` | 全绿（并入 6 文件合跑，未在失败清单） |

命令：`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"; .\.venv\Scripts\python.exe -B -m pytest <路径> -q
-p no:cacheprovider --basetemp backend\.pytest-tmp\capdrop2`。离线闸门（`t09_network_guard`）正对照
`getaddrinfo("api.deepseek.com")` 被拦（`T09-D1`）且该自证后清账，本轮真实出站 0。仓库内 basetemp 下
`test_p2_evidence_capture` 等报 `evidence_root_inside_forbidden` 是既有**环境约束**（证据根必须在仓库外），
换仓库外 basetemp 即 339 全绿，与本单改动无关。

### 7.5 兼容性论证

1. **缺键不合成**：可选键缺省时 `clean_event_payload` 直接 `continue`；只给 record 面时 document 面
   不会被补默认值（用例断言），三键也可只出现两键。
2. **合成值逐值不变**：同输入下仍是 `term_miss` / `kind_miss` / `no_drop` / `vector_unavailable` /
   `not_applicable`（逐值 pin），且 `_merge_candidate_drop_reason` 对两面按面码复算 = 合成值。
3. **`diag=None` 不改控制流**：`collect_diag` 与 `capture_enabled()` 两道门都未改；观察关闭时
   不发事件、不构造按面键、候选集与默认入口逐值相同（monkeypatch 断言 0 次 emit）。
4. **旧 envelope 逐值不变**：冻结构件生成的 `retrieval_observed` 仍是旧 6 键；带合法按面码的
   envelope 仍 `empty_use_scope_ok`，非法码被同一清洗口径 fail-closed。
5. **冻结件零改动**：两处冻结闭包从共享 `EVENT_FIELDS` / `clean_event_payload` 读键集与校验
   （`hard.CAPTURE_EVENT_FIELDS is cap.EVENT_FIELDS` 用例）；`p2_evidence_capture.py` 的候选层投影
   只读 `scope/candidate/unit_ids/truncated/empty/seq`，按面键不进入任何投影/摘要。
6. **不升版**：`mktkb.eval-capture/v0.1` 不变。
7. **未触碰**：`evaluation/p2_*.py`、`docs/evaluation/*`、`fixtures/`、账本、预算、旧证据、case-plan
   均未改（按面新符号在 `p2_*.py` 中 0 命中）；工作树其余在途改动未触碰；未 `git add/commit/stash/
   reset/checkout/clean`；未安装依赖；未读私有材料；未发真实请求。

