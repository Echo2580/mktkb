# H2 v3 第一轮产品修复开发报告（v3-fix-1）

- 角色：v3 第一轮产品修复开发（普通开发；不是验收、不是经理、不是保管）。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；暂存 0 项；未 commit / 未 push / 未新建 worktree / 未切分支。
- 本包**零真实调用**：所有验证都在进程内离线完成（正对照 4/4 被拦、会话外部出站尝试 0），证据见 §5.3。
- 结论：**COMPLETE**（A/B 两处修复接通产品链路，各有正例 + 反例；另有 **§0.1 一条前置口径需主人复核**，若口径相反本包改判 PARTIAL）。

---

## 0. 口径与边界

### 0.1 本轮采用的裁定（无人可问，按最可交付口径执行，请复核）

任务书写"15 条原有 tracked modified + 第 16 条 `p2_holdout_plan.py` 逐条不变"，同时又写"除修复涉及的既有文件外不改其他"。A/B 的最小接入点**只落在**工作树里已 modified 的两条：

- A：`backend/src/mktkb/rag/query.py`（planner 多目标分支）+ `backend/src/mktkb/conversations/service.py`（`_rag_owns_turn` 路由）；
- B：`backend/src/mktkb/conversations/service.py`（legacy 取证入口；业务日期只能从产品本轮 `QueryPlan.as_of` 取）。

不改这两条，legacy 记录型多目标仍由 `service` 判 `ambiguous→clarification`，legacy 取证也没有日期入参——两处都接不通产品链路。因此按"**16 条路径集合不变、允许在修复涉及的这 2 条内部改**"执行：

| 项 | 结果 |
|---|---|
| 16 条 tracked modified 里未涉及修复的 14 条 | **逐字节相同**（改前/改后 SHA 见 §4.2） |
| 涉及修复的 2 条 | `rag/query.py`、`conversations/service.py` 改动，改前/改后 SHA 见 §4.1 |
| status 条目集合 | 仍为原来的 16 条 modified（新增只有未跟踪测试/证据文件） |

若主人要求这 16 条**字节不变**，则 A/B 只能停在"合成复现 + 补丁草案"，本包应改判 **PARTIAL**——请以本口径裁定为准。

### 0.2 硬边界核对

| 边界 | 状态 |
|---|---|
| 零真实调用 / 零真实请求 | 是（§5.3；正对照先删代理环境变量 + `ProxyHandler({})`） |
| v2/v3 语料与密文 | 未改（未写 `fixtures/`、未碰密文） |
| C 冻结 12 | 未改 |
| `p2_holdout_scenarios.py` | 未改（SHA 与基线相同，§4.2） |
| 账本/GO/预算 | 未改；两个预算类测试的失败是既有漂移（§5.2） |
| 已接收评测模块 | 未改（`backend/src/mktkb/evaluation/**` 全部未动） |
| 真实 H2 题面/答案 | 未读（未解密、未打开仓外运行证据） |
| stage / commit / push | 全部为 0 |

---

## 1. 修复 A：单轮多目标不再判澄清

### 1.1 复现（改前，合成问题 + 离线替身/纯函数）

探针 `evidence/probe_planner.py`（只调产品 `rag.query.parse_query` / `conversations.intent.parse_question` / `service._rag_owns_turn`；不建库、不检索、不调模型）在改前实测：

| 合成问题 | rag 计划（改前） | 产品实际结局（改前） |
|---|---|---|
| Q2 `城东店和城西店的宣传海报在哪里？` | 无澄清，`enumerate=false`、`filters={item}` | 轮次不归内核 → legacy 意图层判"多个门店"**澄清** |
| Q3 `城东店的宣传海报和易拉宝在哪里？` | `ITEM_AMBIGUOUS` **澄清** | legacy 再判"多个物品"**澄清** |
| Q4 `城东店和城西店的宣传海报和易拉宝在哪里？` | `ITEM_AMBIGUOUS` | 澄清 |
| Q5 `城东店和城西店的宣传海报分别在哪里？` | 已 `enumerate=true`（命中"分别"） | 已能枚举（说明缺口只在"没有枚举词"） |

改前机读证据：`evidence/probe_planner_before.json`（同一脚本、同一合成问题，在任何代码改动之前运行，原文照录）。机制与登记 `PLANNER_MULTI_TARGET_CLARIFICATION`（PR-PLAN-01..06）一致：`clarification` 使 `kind_correct` 必失配。

### 1.2 修复点（最小改动）

| 文件 | 改动 |
|---|---|
| `backend/src/mktkb/rag/query.py` | 新增"同维度 ≥2 个**明确**目标 + 另一维度 ≤1 + 有可回答字段角色 + 目标全在词表内 + 非指代/非政策/无资料或产品歧义"判定：置 `enumerate=true`、`reason=MULTI_TARGET_ENUMERATE`，目标写入 `state.stores`/`state.items`；该轮不再走 `ITEM_AMBIGUOUS`。多物品时 `_required_missing` 不再要求补门店 |
| `backend/src/mktkb/rag/types.py` | `QueryState.items`（多物品目标；与既有 `stores` 同口径，`to_dict/from_dict` 往返） |
| `backend/src/mktkb/rag/retrieval.py` | 记录型证据面：本轮点名多个物品时只取这些物品（`ITEM IN (...)`），与既有"多门店 `STORE IN (...)`"完全同口径——多目标不做整表枚举 |
| `backend/src/mktkb/conversations/service.py` | `_rag_owns_turn`：`reason=MULTI_TARGET_ENUMERATE` 的轮次交给内核。多门店时 `store` 槽位按产品设计留空（`query.py:1720`），不能因为 `filters` 为空退回 legacy 的"多实体→澄清" |

**为什么不是"一切多目标都放行"**：判定要求(a) 同一维度 ≥2、另一维度 ≤1（两个维度都 ≥2 的交叉配对仍澄清）；(b) 目标全部是词表内实体（词表外门店/区域仍走原有未知实体面）；(c) 本轮有可回答的记录字段角色（纯名词串、无字段问题不进入）；(d) 非指代追问、非政策正文题、无资料/产品歧义。

### 1.3 修复后行为（正例 / 反例）

证据：`evidence/probe_planner_after.json`、`backend/tests/rag/test_v3_fix1_multi_target.py`、`backend/tests/unit/test_v3_fix1_wiring.py`、`backend/tests/observability/test_paths_e2e.py::test_multi_target_single_turn_answers_instead_of_clarifying`。

| 用例 | 结局 |
|---|---|
| **正例** Q2 两店一物品 | `answer`；逐条列出两个门店的位置；`returned=2`，同店其它物品不进证据面 |
| **正例** Q3 一店两物品 | `answer`；逐条列出两个物品；`returned=2`，另一门店与其它物品不进证据面 |
| **正例** 两店 + 门店级字段（电话） | `answer`；两条电话逐条列出（无单值实体过滤也能作答） |
| **正例** 产品层路由 | 该类轮次 `trace.path=rag`、`outcome=answer`，无伪造的 legacy `intent_parse/retrieve` |
| **反例** Q4 两店两物品（交叉配对不明） | 仍 `clarification`（`ITEM_AMBIGUOUS`），legacy 侧也仍澄清 |
| **反例** 未点名目标的纯指代（`这两个分别放在哪里？`） | 仍 `clarification`（不因"可能多个"放行） |
| **反例** 词表外门店（`城东店和城南店…`） | 不进入多目标执行；`missing_stores` 含未知名（不吞） |
| **反例** 多个目标但没有可回答字段 | 不进入多目标执行（`reason` 非 `MULTI_TARGET_ENUMERATE`，不归内核） |

### 1.4 残余（不隐瞒）

1. **legacy-only 装配仍澄清**：`qa` 未注入时（产品 `main.py` 总会注入，故生产路径不受影响）多目标仍由 `conversations/intent.py` 判澄清。本轮不改 `intent.py`，避免与既有单测 `test_intent_multiple_stores_requires_clarification` 的语义冲突。
2. **多物品目标缺记录时不披露**：`_enumerate_answer` 只有 `missing_stores` 披露口径；多物品里某个目标无行时只会"少列一条"，不会说"未找到该物品"（门店维有披露）。
3. **2×2 交叉仍澄清**：可能是偏保守的一侧（真值可能是"四条都列"）；本轮按"配对不明=真歧义"处理。

---

## 2. 修复 B：legacy 证据面按业务日过滤

### 2.1 复现（改前）

合成数据（真实 `LegacyIndex` + `SourceUnit` + 检索索引）：同一 `标识`（P01）在三个版本里位置不同，窗口互不重叠：

| 版本 | 位置 | 生效日期 | 失效日期 |
|---|---|---|---|
| V03 | A区3号货架第二层 | 2026-01-05 | 2026-04-30 |
| D01 | D区暂存柜 | 2026-05-01 | 2026-10-31 |
| V05 | E区新柜 | 2026-12-01 | 未声明（L1 null = not_asserted） |

改前（`as_of=None`，即 legacy 路径原行为）：同一标识三行同属一个实体组 → `kind=conflict`、`3 units`，其中 V03 在 run 0 业务日 `2026-10-15` **已过期** → 冻结分类器 `source_expired` 硬失败（与登记 `P01_VERSION_COLLISION` 机制一致）。

### 2.2 修复点（只做时间维度过滤）

| 文件 | 改动 |
|---|---|
| `backend/src/mktkb/retrieval/service.py` | `retrieve(..., as_of=)`；在 `_visible_units` 之后、**分组/冲突/字段裁剪/排序之前**按"行自带窗口"裁剪；闭区间 `from <= as_of <= to`；未声明的一侧不参与判定；非法 `as_of` 在服务边界 `QueryRejected`。`as_of=None` 时与改前逐值相同 |
| `backend/src/mktkb/conversations/service.py` | legacy 取证入口（含"同实体冲突复核" `_same_entity_evidence` 与正文 overshoot 回退 `_document_overshoot_evidence`）显式传 `as_of`；取值只来自本轮产品的 `QueryPlan.as_of`（题面显式日期优先，否则 Settings 级 `rag_business_date`）；`include_future`（未来/调整后）不过滤；`qa` 缺失时不过滤（不臆造日期） |

**窗口来源**：记录行自带的 `生效日期`/`失效日期` 单元格（v3 语料按 L1 生命周期表逐值写入；本包实测四个位置表版本的窗口与 L1 逐值一致）。产品不读数据集、manifest 或报告字段，也不回填。

**没有改召回/排序**：召回渠道、`_merge_text_fact_groups`、分组键、组内排序 `(document_id, ordinal)`、候选计数口径全部未动；只多了一次时间维裁剪。

### 2.3 过滤前后同输入对比 + 不误杀

证据：`evidence/probe_business_date_before_after.json`、`backend/tests/rag/test_v3_fix1_business_date_filter.py`。

| 观测 | `as_of` | kind | units | 说明 |
|---|---|---:|---:|---|
| 过滤前（= 改前行为） | 无 | `conflict` | 3 | 三个版本同时"现行" |
| 过滤后（run 0 业务日） | 2026-10-15 | `matches` | 1 | 只剩 D01；引用不再含过期行 |
| 闭区间右端点 | 2026-04-30 | `matches` | 1 | V03 仍有效（不误杀端点当天） |
| 闭区间左端点 | 2026-05-01 | `matches` | 1 | D01 生效当天有效 |
| 末端"未声明" | 2026-12-15 | `matches` | 1 | V05 不被当过期（not_asserted 侧不判定） |
| **不误杀**：只有现行版本 | 2026-07-15 | `matches` | 1 | 单现行版本正常作答 |

`order_preserved=true`：存活单元在过滤前后的相对顺序完全一致（只删行、不重排）。

### 2.4 残余（不隐瞒）

1. **纯正文资料无窗口列**：pdf/docx 的来源窗口只存在于 L1（不在产品数据里），legacy 对这些来源不做日期过滤（本包不改 ingest/文档元数据）。
2. **`conflict` 状态仍不可达**：窗口连续互斥 ⇒ 过滤后同一槽位至多一版有效；登记 `CONFLICT_STATE_UNCOVERED` 的覆盖缺口不变（本包不新增 conflict 题）。
3. **日期语义只有 run 级**：请求/界面级业务日期仍不存在（`p2_holdout` 的 run 日期经适配器进 `RagConfig.business_date`）。

---

## 3. 顺带核（只核不改）

### 3.1 run2 `MODEL_OUTPUT_INVALID(record_facts)`

- **最小复现**：`evidence/probe_run2_record_facts.py`（纯函数，用产品自己的 `service._facts` / `_record_facts` / `_match_record_clause` 重放 dryrun `echo-all` 替身的输出）。
- **结论（形态 A）**：同一问字段**同值**出现在两条证据行（表格行 + 独立通知/同值行）时，替身按行回显全部字段，得到两个 `位置：同值` 分句；第二条命中 `_record_facts` 的 `if role in seen: return None` → 整段不可验证 → `ModelOutputInvalid` → `MODEL_OUTPUT_INVALID(record_facts)`。
- **形态 B（对照）**：两条证据行同字段**不同值**时**不触发**（不同值分句按"其它字段回显"跳过）——说明拒绝只发生在"被问字段的同值重复回显"，不是"多行证据"本身。
- **是否产品缺陷**：属**产品侧过严的准入限制**（fail-closed，不会产出错答，也不是数据/判据问题、不是安全缺陷）。可改进点两条：① 同值重复分句可去重而非整段拒绝；② 失败码只有 `record_facts`，不指出哪条规则（可定位性弱）。
- **未验证**：run 2 实际第 5 回合是否就是该形态（需运行证据回放；本包零调用，未回放）。另：本轮 A 修复会把同类"多目标"轮次改走内核枚举、不再进入 `_record_facts`，可能顺带减少该失败形态——同样未验证。

### 3.2 文档标题 `D01_` 前缀解析不到

- **复现**：`evidence/probe_doc_title_prefix.py`。同一句自然提问（只写中文标题，不写 `Dxx` 代号）：
  - 标题 `D01_物品位置表` → `_document_core="D01"` → `reason=DOCUMENT_NOT_FOUND`（`resolved=false`）
  - 标题 `物品位置表` → `mode=record`，`filters` 含 `doc_id`（`resolved=true`）
- **成因**：**ingest 命名侧为主**——上传名就是源文件名（带 `Dxx_` 代号前缀），产品文档标题取自上传名；**解析侧为辅**——`rag.query._document_core` 用第一个 `_`（或括号）截断，只留下 ASCII 代号、丢掉中文标题核心，自然提问匹配不到任何资料。
- **修法（二选一，本轮不改）**：ingest 上传名去前缀；或让 `_document_core` 剥掉 `^[A-Za-z]+\d+[_\-]` 形态的代号前缀。

---

## 4. 变更清单与 SHA-256

### 4.1 本包改动（9 条）

| # | 文件 | 改前 SHA-256 | 改后 SHA-256 | 备注 |
|---:|---|---|---|---|
| 1 | `backend/src/mktkb/rag/types.py` | `0e738ef79ce55d4d3b60110e7b6d5b822a0fb7b081824a959d930834dcafe7e7` | `bf7a957a621784e01f026ae5e86ec97695e767cf6b1ab7576d382a6fb600273d` | 新增 `QueryState.items` |
| 2 | `backend/src/mktkb/rag/query.py` | `5a7ed26b73a3ab658deff6384b5fdcc67596860345153cec4ec4f72cb350e1e1`（修复前工作树） | `f73fc7353501e09e65a474fc2599fa4235e1db5d72fc4ea802e0e881f680c372` | **属 16 条既有 modified**；多目标分支 |
| 3 | `backend/src/mktkb/rag/retrieval.py` | `afa376557a3351d5317ae677b91f83bccf461833f47a8369c54c4614a1548e97` | `234fd93083179fddd91c14cd046404eeb1c90434203c28e62138dc70e6f04fcb` | 多物品证据边界 |
| 4 | `backend/src/mktkb/retrieval/service.py` | `d13e2c559da47edfe1ceaa41f0eed8e3add7b8b9cd69f62ebd2750ac6e658e25` | `28b04038468783e8a14005a4689f496a1cd2a1b35837da190004e053affd2323` | `as_of` 时间过滤 |
| 5 | `backend/src/mktkb/conversations/service.py` | `fd04136b6b450b45a98045bcb9b16c21531d35070e73529263a1507690dae75a`（修复前工作树） | `29b0a29582ee08298c842087ce9f50b4b2c2ccba4103fa03e0c3920bb48984f0` | **属 16 条既有 modified**；路由 + 日期接线（含 overshoot 回退转发） |
| 6 | `backend/tests/observability/test_paths_e2e.py` | `cdddd5ccf0a57ad5bbb1d6b2d9038ec965b3d1c2b63ae506674b9172d0cb4244` | `d357fdc392e95cfb32f112f2ee28c1d76c14338028fe019ed2b029af37770384` | 改前=HEAD：多目标用例改判 + 新增答案用例 |
| 7 | `backend/tests/integration/test_p1_t103_record_fallback_http.py` | `acba5a24018dd9cc306846f9f772bab5c5748ac5141a623e045b6d55e11646b0` | `0df8de184d85561faef67e9658bf9e2eca461d29b9162d120a0bcacef9fc41c7` | 测试替身接受 `as_of` |
| 8 | `backend/tests/integration/test_t207_fix_conflict_r1.py` | `370c01db347d3f9aefba340761261c8c15b5449df6125fd381bb2108cd49929c` | `2bca42e2fa109e6de7681083b85b8e6f6e13379044502e93be8f768917269a9c` | 测试替身接受并转发 `as_of` |
| 9 | `backend/tests/unit/test_p1_t103_record_fallback.py` | `ddb0c82f61796b695e7551e404226bc71d6df8e0e5632af56dc3052418e58145` | `fddb73ba2da504944ed18a03e134b2be0b12e1a8d24a17537931f5bca9d75792` | 测试替身接受 `as_of` |

新增（未跟踪）：

| 文件 | SHA-256 |
|---|---|
| `backend/tests/rag/test_v3_fix1_multi_target.py` | `73f081b41e98991e742bc28ebe4beb59cf7857aa7c7331cbd20917c4a6a24508` |
| `backend/tests/rag/test_v3_fix1_business_date_filter.py` | `5c738a87b0e26ecf3fae4d2f21aa8b810d075cef32647c6042eec3828a56ed17` |
| `backend/tests/unit/test_v3_fix1_wiring.py` | `053b99369cbeada88993e444ce9bc47624d6f3a1038604ef14d50e711d1d87b4` |
| `docs/reports/OBS-EVAL/P2/H2V3/fix-1/`（本报告 + `evidence/`） | 逐件见 `evidence/MANIFEST.json` |

### 4.2 保全核对（16 条 tracked modified）

未涉及修复的 14 条与基线**逐字节相同**（`.claude/handoffs/_index.md`、`evaluation/cli.py`、`p2_diagnostics.py`、`p2_holdout_plan.py`、`p2_holdout_scenarios.py`、`p2_live.py`、`p2_runner.py`、`p2_scoring.py`、`product_adapter.py`、`qa/service.py`、`rag/index.py`、`tests/rag/test_query_state.py`、`tests/unit/test_conversations.py`、`T207-QUALITY-REPAIR/manager.md`）。机读核对：`evidence/preservation-check.json`。

---

## 5. 测试与零调用

### 5.1 合成测试（新增 3 文件 / 22 用例；每条修复 ≥1 正例 + ≥1 反例）

| 文件 | 用例数 | 覆盖 |
|---|---:|---|
| `backend/tests/rag/test_v3_fix1_multi_target.py` | 11 | A 正例（双店/双物品/门店级字段 + 端到端枚举）、A 反例（2×2 交叉、纯指代、未知门店、无字段） |
| `backend/tests/rag/test_v3_fix1_business_date_filter.py` | 6 | B 正例（过滤前后同输入、闭区间端点、未声明侧、`as_of` 校验）、B 反例（单现行版本不误杀、`as_of=None` 与改前一致） |
| `backend/tests/unit/test_v3_fix1_wiring.py` | 5 | 产品层接线（日期取值、`_retrieve` 转发、多目标路由、非歧义不放行） |

全部离线：临时 SQLite + 确定性 offline provider + 纯函数；无模型/embedding/rerank/OCR/检索服务调用。

### 5.2 分层回归（collect / passed / failed / exit）

| 命令（`backend/`，venv `python -m pytest`） | collect | passed | failed / error | exit | 日志 |
|---|---:|---:|---|---:|---|
| `tests/unit tests/rag` | 740 | **738** | 2 failed（既有漂移，见下） | 1 | `evidence/pytest-unit-rag-final.log` |
| `tests/integration tests/observability` | 793 | **793** | 0 | 0 | `evidence/pytest-integration-observability-after.log` |
| `tests/evaluation`（定点：evidence capture / model failure / multiturn / refusal controls / safe diagnostics） | 119 | **119** | 0 | 0 | `evidence/pytest-evaluation-targeted.log` |
| `tests/evaluation`（全量） | 2318 | **2199** | 30 failed / 74 error（全部在既有 scenario/ingest 哈希路径，见下） | 1 | `evidence/pytest-evaluation-summary.txt` |
| `tests/acceptance` | 70 | **70** | 0 | 0 | `evidence/pytest-acceptance.log` |
| 修复相关 7 个文件（**netguard 守卫生效**下） | 49 | **49** | 0 | 0 | `evidence/pytest-netguard.log`、`evidence/netguard-run.json` |

**2 个 unit/rag 失败（既有，不属本包）**：`tests/unit/test_s2h_r3_official_profile.py` 与 `tests/rag/test_s4_stage_limit.py` 断言 GO/预算账本守恒，实测 `sum(stages)=40 ≠ limit=50`（工作树 `docs/evidence/LOCAL-R1-20261101/budget/budget.json` 已含 `P2-LIVE=20`）；二者不 import 本包任何改动模块，且账本/预算按边界未改。

**evaluation 全量失败/错误（既有，不属本包）**：`scenario_ingest_invalid` 103 次（`p2_holdout_scenarios.py` 拒绝冻结 v3 ingest plan；该模块本身属 16 条既有 modified，本包未改）、`p2_holdout_scenarios.py` 26 failed、`p2_v3_wiring.py` 3 failed、`p2_public_cases.py` 1 failed（manifest/ingest SHA 绑定漂移）、`p2_h2_historical_audit.py` 40 error、`p2_hard_evidence.py` 27 error、`p2_eval_tool_repair_e2e.py` 7 error（缺冻结运行卡/工具产物）。这些用例均不在本包改动模块上。

**说明**：全量 `pytest` 基线跑在 25 分钟仅 12% 时被中止，改为分层验证（unit+rag / integration+observability / evaluation / acceptance 四段分开跑）；四段合计覆盖 3921 个用例（含 16 skip），除本包列出的既有漂移外全绿。

### 5.3 零调用证据（`evidence/netguard-run.json`）

| 项 | 值 |
|---|---|
| 代理环境变量（导入即删除） | `ALL_PROXY`、`HTTPS_PROXY`、`HTTP_PROXY`、`NO_PROXY`、`NODE_USE_ENV_PROXY` |
| 守卫 | `socket.connect` / `connect_ex` / `create_connection` / `getaddrinfo` |
| 回环策略 | 放行并计数（Windows 上 anyio 阻塞 portal 用 loopback socketpair；实测 184 次，均非业务出站） |
| 正对照（DNS / 直连 / urllib `ProxyHandler({})` / httpx `trust_env=False`） | **4/4 blocked**，全部错误为 `netguard: … blocked` |
| 会话内**外部**出站尝试 | **0** |
| 守卫下跑测试 | 49 collected / 49 passed / exit 0 |

产品/模型调用计数：0（测试只用 offline provider、纯函数与进程内 ASGI；无 `.env` 读取、无 var 业务库、无密文解密）。

---

## 6. 残余与风险（汇总）

1. **口径风险**：§0.1——若"16 条字节不变"是硬约束，本包应改判 PARTIAL（A/B 只能停在复现 + 草案）。
2. A：legacy-only 装配仍澄清；多物品缺记录不披露；2×2 交叉仍澄清（可能偏保守）。
3. B：纯正文资料无窗口列不过滤；conflict 覆盖缺口不变；日期只有 run 级。
4. §3.1 的 `record_facts` 过严（未修）；§3.2 的 `D01_` 前缀（未修）。
5. 测试证据更新：3 个既有测试替身接受 `as_of`；`test_paths_e2e.py` 一个用例的期望按修复后的产品行为改判，并新增一条"多目标→answer"的 trace 用例；新增 4 条未跟踪测试文件（不 stage）。
6. 全量套件改为分层验证（四段合计 3921 用例）：A/B 的模块级分层回归 + acceptance 全绿（除既有漂移 2 条与既有 evaluation 数据/产物漂移）。

---

## 7. 结论

**COMPLETE**（在 §0.1 口径下）：A/B 两处修复都接进了产品链路，复现证据、修复后证据、正例/反例、零调用证据、变更 SHA 与保全核对齐全；两处"顺带核"给出最小复现与成因定性，按要求未修。残余与口径风险已在 §0.1、§6 如实列出。
