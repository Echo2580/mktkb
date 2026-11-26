# H2 v3 第一轮修复 · 独立验收 + 预算回退报告

主人，本报告由 **v3 第一轮修复的独立验收 + 预算回退执行者** 出具。先按经理裁定完成预算回退，再对 `docs/reports/OBS-EVAL/P2/H2V3/fix-1/` 做独立验收；验收反例自建，不照抄开发用例。

- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存 0，172 commit。
- 本包零真实调用：所有验证为纯函数、临时 SQLite、offline provider、进程内 ASGI；正对照 4/4 被拦（见 §2.5）。
- **结论：FAIL**（窄口径：A 的“纯指代”反例被放行，且是 fix-1/A 引入的行为回归；其余项绿）。判“不可进入真实 v3 跑”，先补该反例（§3）。

---

## 1. 第一部分：预算回退（经理裁定，已执行）

### 1.1 `budget.json`：`limit_cny` 50 → 40

| 项 | 值 |
|---|---|
| 文件 | `docs/evidence/LOCAL-R1-20261101/budget/budget.json` |
| 改前 | `5fcb4be5a68bb9437ff82be8dc73794bc712a5e5fe3b6312f70a4218f3d0b25f`，1,738 B |
| 改后 | **`79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e`**，1,738 B（等于原 40 值） |
| 字节差异 | 仅 **offset 17**：`'5'` → `'4'`；等长；前缀 `[0:17]` 与后缀 `[18:]` 逐字节相同 |
| 深度差异 | 唯一变化叶子 `/limit_cny`（50→40）；`stages`、`historical_conservative_accounted_cny`、`ledger`、键序全不变 |
| 原子写 | 同目录临时文件 + `os.replace`；无 `.tmp`/`.lock` 残留；未写账本 |
| 附带 | 50 时代的两处陈旧元数据（`remaining_conservative_cny_at_start=39.97`、`stage_revision.arithmetic` 按 40 描述）随回退自动恢复一致；v3-go 残余 R2 关闭 |
| 证据 | `independent/budget-rollback.json` |

### 1.2 `p2_holdout_plan.py`：撤销环境变量读取

| 项 | 值 |
|---|---|
| 当前 SHA-256 | **`d0cb23de2cff80a743c086a8723edd80654d64b22f4e18f97973dd83b153cd25`**（15,634 B） |
| 与改前基线 | 一致（目标值即此） |
| 与 `HEAD` 内容 | 一致（`git show HEAD:…` 内容 SHA 同值；`git diff` 为空） |
| 撤销内容 | `import os`、`H2_PROJECT_TOTAL_LIMIT_CNY` 改为 `float(os.environ.get(...))` 及其注释（1 处语义改动） |
| 证据 | `independent/rollback-summary.json` §`p2_holdout_plan` |

### 1.3 tracked modified：实际为 **22 条**，不是 15 条（需经理更正口径）

回退后 `git status` 为 **22 条 tracked modified**，逐条分解：

- **15 条既有基线路径**全部在列；**在本会话前后逐字节未变**（其中 `rag/query.py`、`conversations/service.py` 含 fix-1 在会话前的既有改动，见 §2.3）。路径：`.claude/handoffs/_index.md`、`evaluation/cli.py`、`p2_diagnostics.py`、`p2_holdout_scenarios.py`、`p2_live.py`、`p2_runner.py`、`p2_scoring.py`、`product_adapter.py`、`qa/service.py`、`rag/index.py`、`rag/query.py`、`conversations/service.py`、`tests/rag/test_query_state.py`、`tests/unit/test_conversations.py`、`T207-QUALITY-REPAIR/manager.md`。
- **7 条 fix-1 新改的 tracked 文件**仍在列：`rag/types.py`、`rag/retrieval.py`、`retrieval/service.py`、`test_paths_e2e.py`、`test_p1_t103_record_fallback_http.py`、`test_t207_fix_conflict_r1.py`、`test_p1_t103_record_fallback.py`。它们在 fix-1 之前是 **HEAD 干净态**（逐文件与 dev-report 的“改前”SHA 相同），是 fix-1 的正当产物。
- 差额结构：`15 既有 + 7 fix-1 = 22`。**“回到 15 条”只有把 fix-1 的 7 条也回退才可能，那等于撤销被验收的修复**，不在本包边界内。
- dev-report §0.1/§4.2 的“status 集合仍为 16 条 modified”与事实不符（它自己 §4.1 列了 7 条 tracked 测试文件）；fix-1 完成时实际为 **23 条**（16 + 7），回退 `p2_holdout_plan.py` 后为 22 条。经理的“15”沿用了该笔误。
- 证据：`independent/preservation-compare.json`（`tracked_removed` 仅 `p2_holdout_plan.py`；`tracked_added=[]`；`tracked_common_sha_changed=[]`）。

### 1.4 受影响 2 条既有测试：**没有恢复绿**（需经理裁定）

| 测试 | 不设环境变量 | `MKTKB_PROJECT_TOTAL_LIMIT_CNY=40` | 原因 |
|---|---|---|---|
| `tests/unit/test_s2h_r3_official_profile.py::test_official_profile_accepted_by_both_entries_and_worst_case_is_2103552` | **FAIL** | **PASS**（14/14） | `live_authorization.project_total_limit_cny()` 默认 10.0；未设环境变量时与 budget 40 比对报 `LiveGateError`。与 40/50 无关，属运行时环境契约（v3-go 残余 R5）。 |
| `tests/rag/test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan` | **FAIL** | **FAIL** | 第 208 行硬编码 `budget["limit_cny"] == 20.0`（20 元时代）；40/50 都不可能过。其“`sum(stages)+historical == limit`”断言现已通过（39.97+0.03=40.00）。 |

- 结论：原来的“40≠50 漂移”已修复；但 2 条测试仍红，原因是 (a) 环境变量默认值、(b) 陈旧的硬编码 20。**“确认恢复绿”不成立**；修测试会新增 tracked modified/改变测试语义，未擅自执行。
- 计数：`unit+rag` = 740 collected / 738 passed / 2 failed / exit 1；环境变量 40 下两条定向 = 22 collected / 21 passed / 1 failed / exit 1。
- 证据：`independent/pytest-unit-rag-after-rollback.log`、`pytest-drift-2-after-rollback.log`、`pytest-drift2-with-env40.log`。

### 1.5 4 份 GO 与 4 份计划：已按 40 重新生成/对齐

- 计划：用唯一受控入口 `tools/p2_h2_v3_controlled_execute.py plan-private` 重新生成到仓外 `D:\mktkb-p2-h2v3-20261115\rollback-40\`；`contract_validate_run` 四 run 全 `ok=true`、`differing_keys=[]`（50 时代的 `scenario_plan_mismatch` 残余 R1 已关闭）。与 50 版计划逐值比较：**唯一差异 `project_total_limit_cny`**；`items`/`scenario_binding`/`max_requests` 全同。
- GO：4 份均 `budget_total_limit_cny=40`、`max_requests=1137`（不变）、`stage_limits_cny={"P2-LIVE":20.0}`、`max_request_cny=0.5`；旧 50 版逐字节归档为 `P2-LIVE-GO.v3-limit50-r{0..3}.archived.json`。
- 安装：r0 → 固定槽 `P2-LIVE-GO.json`；r1–r3 → `P2-LIVE-GO.v3-r{1,2,3}.pending.json`。
- 零发送/零写复核：真实入口 `check-only --plan-only` 四 run **4/4 `ok=true`**，12 项检查全 true，`zero_send`/`zero_write` 全 true；账本 `ca9dceb9…`、952 次预留、预算 SHA 前后不变。

| run | plan_sha256（新） | GO SHA-256（新） | 旧 GO（归档，逐字节） | 余量 |
|---:|---|---|---|---:|
| 0 | `a109894e6ff99bbe2019e783b5bf379fea42c9574b56c3d957fb627ad5953c65` | `dbc198c8bf8ee11c844d0393c9091b25a0b5e6d1281c872cd6b254854fe5217d` | `8effb4b1…ffdbf` | 185 |
| 1 | `4691e9c366fa4393640f7bbf4d5e25de7b012b8f9fd4a5425f519867d281ad97` | `a8516ac3d71a9fd9595a000652c534b4809b6cc288cc505a40773688a82fb1b2` | `5cdde637…c578` | 121 |
| 2 | `9896ae4ecb30ea5c696dcc160bb9a318194808f15badccde4f92e75980f857bb` | `d7edf6d256cd19882a682604bb31689e9f0be9ed76a8d8d6f8f09de2a3e4d4e1` | `cbce4ba4…af8` | 72 |
| 3 | `8f662d59f9a8988f601e5c8de419ba46f118fae498f48b0c5e74ff25c0e48e9f` | `d681b673837d681574dfcf18a11984463599d1856c0641411580146916e3b1a4` | `8a4c94fb…bc0` | 37 |

- 计划文件 SHA-256（仓外，可复算）：r0 `3f1c0014…dad81`、r1 `b1ba1ffc…4f577`、r2 `59ae317b…6b6e2`、r3 `989cdc94…01293`。
- **配套代码回退**：`tools/p2_h2_v3_controlled_execute.py` 的 `V3_PROJECT_TOTAL_LIMIT_CNY` 50.0→40.0（该文件 untracked，导入期写入环境变量；不改则 check-only 会 `env_total_limit_mismatch`）。SHA：`aa8e8cb4…e97cb` → `465cc07a…2ac02`。
- **历史文档仍写 50**：`docs/reports/OBS-EVAL/P2/H2V3/v3-go/report.md` 与 `plan-index.json` 是 50 时代的历史记录，不是可执行计划；本次未改写（避免把历史证据改成“当时就是 40”）。真实跑请用 `rollback-40\` 下的计划/绑定或重跑 `plan-private`。
- **隐私边界披露**：计划重生成走唯一受控入口 `plan-private`，该入口按设计加载 v3 冻结件（含 annotations/review）以做契约校验；本包未输出/未查看任何真实题面、答案、标签或 case_id，仓内证据均为计数与 SHA。计划/绑定含 case_id，只留在仓外 `D:\mktkb-p2-h2v3-20261115\rollback-40\`，未入库。
- 证据：`independent/rollback-40/{plan-index.json,go-regeneration.json,go-install.json,check/run*.json}`、`independent/rollback-summary.json`。

---

## 2. 第二部分：fix-1 独立验收

### 2.1 A · planner 多目标：正例全过，纯指代反例失败（FAIL）

自建探针：`independent/probe_A_multi_target.py`（合成 5 行记录 + 2 行电话；临时 SQLite + offline provider；socket 守卫）。结果：`independent/A-planner-multi-target.json`。

**正例（4/4 通过）**

| 用例 | planner | 产品结局 | 证据面 |
|---|---|---|---|
| 两店一物品 | `enumerate=true`、`MULTI_TARGET_ENUMERATE`、`_rag_owns_turn=true` | `answer` | `returned=2`；只含 A/B，不含 C/D |
| 一店两物品 | 同上，`state.items=("宣传海报","易拉宝")` | `answer` | `returned=2`；只含 A/C，不含 B/D |
| 两店 + 门店级字段（电话） | 同上 | `answer` | `returned=2`；两个电话逐条 |
| 两店一物品 + “分别” | 同上 | `answer` | `returned=2`；只含 A/B |

**反例（4 类，3 类通过、1 类失败）**

| 类别 | 用例 | 结果 | 判定 |
|---|---|---|---|
| 两店×两物品交叉 | `城东店和城西店的宣传海报和易拉宝在哪里？` | `ITEM_AMBIGUOUS`、`clarification`、`owns=false` | **PASS** |
| 交叉（每物品前带店） | `城东店的宣传海报和城西店的易拉宝在哪里？` | `ITEM_AMBIGUOUS`、`clarification` | **PASS** |
| 交叉 + “分别” | 两店两物品 + “分别” | `ITEM_AMBIGUOUS`、`clarification` | **PASS** |
| 词表外门店 | `城东店和城南店的宣传海报在哪里？` | 不进入多目标；`missing_stores=("城南店",)`；只答已知店 | **PASS**（未知名不披露是既有残余） |
| 缺字段角色 | `城东店和城西店的宣传海报和易拉宝` | `ITEM_AMBIGUOUS`、`clarification`、`owns=false` | **PASS** |
| **纯指代（bare）** | `这两个分别放在哪里？` | `MISSING_SLOT`、`clarification` | **PASS** |
| **纯指代（带已点名门店）** | `城东店和城西店的这两个分别放在哪里？` / `…这几个…` | **`MULTI_TARGET_ENUMERATE` + `owns=true` → `answer`，`returned=4`** | **FAIL** |
| 指代（“它们”） | `城东店和城西店的它们分别放在哪里？` | planner 不进入多目标；legacy 仍澄清 | **PASS**（未变） |

**失败机理（改前/改后对照，证据 `independent/A-anaphora-regression.json`）**

- 改前基线（由当前文件反向删除 fix-1 追加块逐字节还原，SHA `5a7ed26b…`）：该问句 planner 无澄清，但 `_rag_owns_turn=false` → 产品走 legacy；legacy `parse_question` 返回“问题中包含多个门店，请选择要查询的门店。” → **澄清**。
- 改后：`multi_target=true`（`stores≥2`、`items` 为空、`field_role=location`、非 `anaphora`）→ `MULTI_TARGET_ENUMERATE` + `_rag_owns_turn=true` → rag 内核作答；证据面为**两店全部物品 4 行**。
- 根因：`ANAPHORA_WORDS` 含 `这个/那个/该/它/…`，但不含 **“这两个/这几个”**（“这 + 两 + 个”不是“这个”的子串）；A 的守卫因此未触发。dev-report 的“纯指代仍澄清”只覆盖了不带门店的 bare 形式，未覆盖“已点名门店 + 指代物品”的组合。
- 影响：这是 fix-1/A **引入的行为回归**（改前澄清 → 改后作答 + 整表 4 行），正是任务书“真歧义必须仍澄清/拒绝、不得把多目标变成整表枚举”要防的情形。修复建议（**未改代码**）：把 `(这|那|哪)\s*(两|几|俩)\s*个` 纳入指代判定，或在多门店目标且物品提及为指代时要求显式物品；并补一条带门店的纯指代回归用例。

### 2.2 B · 业务日过滤：全过（PASS）

自建探针：`independent/probe_B_business_date.py`。四版本同标识（P02）窗口互斥：V1 `2025-11-01..2026-02-28`、V2 `2026-03-01..2026-08-31`、V3 `2026-09-01..2026-12-31`、V4 `2027-01-01..未声明`；另加单现行版本（P03）与缺生效日期（P04）。结果：`independent/B-business-date-filter.json`，`failures=[]`。

| 观测 | `as_of` | kind | units | 位置 |
|---|---|---:|---:|---|
| 过滤前（=改前行为） | 无 | `conflict` | 4 | 旧A架 / 现C柜 / 旧B架 / 新D区 |
| 过滤后（同输入） | 2026-10-15 | `matches` | 1 | 现C柜 |
| 左端点 | 2026-03-01 | `matches` | 1 | 旧B架 |
| 右端点 | 2026-08-31 | `matches` | 1 | 旧B架 |
| V3 左端点 | 2026-09-01 | `matches` | 1 | 现C柜 |
| V3 右端点 | 2026-12-31 | `matches` | 1 | 现C柜 |
| 未声明末端 | 2028-01-01 | `matches` | 1 | 新D区 |
| 单现行版本不误杀 | 2026-10-15 | `matches` | 1 | 西区唯一架 |
| 缺生效日期 | 2026-10-15 | `matches` | 1 | 北区无起点架 |

- 顺序：`after_ids` 是 `before_ids` 的子序列（只删行、不重排）。
- 召回/排序未改：`_visible_units` 前后逐值相同；`_drop_out_of_window(units, None)` 原样返回；diff 只在 `_visible_units` 之后插入过滤，未触碰 `_fts_unit_ids` / `match_expression` / `selected_units.sort` / `candidates`。
- 服务转发：`conversations.service._retrieve(..., as_of=)` 与直接 `retrieve` 逐值一致（`service_forward_none/dated` 均 true）。
- 日期接线：`_legacy_evidence_as_of(qa=None)=None`、`plan=None=None`、`as_of=None=None`、`as_of=日期→日期`、`include_future=True→None`（`wire_ok=true`）。
- `as_of` 校验：`2026/10/15`、`2026-02-30`、`not-a-date`、`2026-1-5`、整数 `20261015` 全部 `QueryRejected`；`None` 放行；`" 2026-10-15 "` 归一为 `2026-10-15`。

### 2.3 未回退既有工作：逐字节还原证明（PASS）

- `backend/src/mktkb/rag/query.py`：当前 `f73fc735…`（= dev-report 改后）。把 13 处 fix-1/A 追加块逐一反向删除后，得到 **`5a7ed26b73a3ab658deff6384b5fdcc67596860345153cec4ec4f72cb350e1e1`**（78,740 B，CRLF 保持）——与 dev-report 的“改前”SHA **逐字节相同**。证据：`A-query-baseline-reconstruct.json`。
- `backend/src/mktkb/conversations/service.py`：当前 `29b0a295…`（= dev-report 改后）。把 15 处 fix-1 A/B 追加块反向删除后，得到 **`fd04136b6b450b45a98045bcb9b16c21531d35070e73529263a1507690dae75a`**（123,283 B）——与“改前”SHA **逐字节相同**。证据：`A-service-baseline-reconstruct.json`。
- 结论：fix-1 只追加了 A/B 接入块（含必要的函数签名/调用转发与一处 `if len(item_hits) > 1 and not multi_target` 的守卫），**没有删除/回退任何既有未提交改动**；上述两文件之外，15 条基线中的其余 13 条在本次会话前后逐字节不变。
- 7 条 fix-1 tracked 文件：改前 SHA = HEAD 干净态，当前 = dev-report 改后值（逐条见 `preservation-compare.json` 与 dev-report §4.1）。

### 2.4 测试计数

| 命令 | collect | passed | failed | exit | 日志 |
|---|---:|---:|---|---:|---|
| `tests/unit tests/rag` | 740 | 738 | 2（§1.4 两条） | 1 | `pytest-unit-rag-after-rollback.log` |
| 新增 22 用例（3 文件） | 22 | **22** | 0 | **0** | `pytest-new-22-after-rollback.log` |
| 两条漂移定向（无 env） | 22 | 20 | 2 | 1 | `pytest-drift-2-after-rollback.log` |
| 两条漂移定向（env=40） | 22 | 21 | 1 | 1 | `pytest-drift2-with-env40.log` |
| fix-1 触达的 3 个 integration/observability 文件 | 23 | **23** | 0 | **0** | `pytest-fix-touched-tests.log` |
| `tests/unit tests/rag`（独立 netguard 下） | 740 | 738 | 2 | 1 | `pytest-unit-rag-netguard.log` |

新增 22 用例**真过**（22/22，exit 0）；但“回退后无 GO/预算漂移失败”**不成立**：仍剩 2 条，原因见 §1.4（一条需 env=40，一条硬编码 20）。

### 2.5 零调用：正负对照（不经本机代理）

独立守卫：`independent/netguard/`（`sitecustomize.py` + `netguard_independent.py`），导入即删 5 个代理环境变量，拦截 `connect/connect_ex/create_connection/getaddrinfo`，回环放行并计数。

- **正对照 4/4 被拦**：`dns_getaddrinfo`、`direct_tcp`（1.1.1.1:80）、`urllib` + `ProxyHandler({})`、`httpx` + `trust_env=False` 全部 `netguard-independent: outbound blocked`。
- **本机代理事实**：删环境变量后 `urllib.getproxies()` 仍从 Windows 注册表读到 `http://127.0.0.1:7897`；但所有出站都在 socket 层被拦，**没有任何请求经过该代理**。
- **负对照**：22 用例 + `tests/unit tests/rag` 在守卫下运行，`external_count=0`（回环 55 次，仅 anyio/socketpair）；A/B 探针自身 `outbound_attempts=0`。
- 证据：`independent/netguard/netguard-positive-control.json`、`netguard-tests22-run.json`、`netguard-unitrag-run.json`。

### 2.6 保全

| 项 | 结果 |
|---|---|
| 分支 / HEAD / commit | `codex/p2-e2e` / `97b00667…` / 172，前后相同；0 新 commit |
| 暂存 | 0 项（前后相同） |
| tracked modified | 23 → 22；**只少 `p2_holdout_plan.py`**；无新增；公共路径 SHA 全同 |
| C 冻结 12 | **12/12 逐字节相同**（含 `product_adapter.py`、`cli.py`） |
| v3 冻结 32 | 30/32；2 个不一致为 `freeze_a_manager_acceptance`、`freeze_a_review_aggregate`（会话前即不一致，会话内未变；属历史更新，不是本包） |
| v2/v3 密文与语料 | `D:\mktkb-p2-holdout\{v2,v3}` 下 13 个 v2/v3 文件（含 v3 review 工作件；不含 `keys/`）SHA 全部不变 |
| `fixtures/acceptance-h2v3` | 13 件（12 源 + manifest）逐字节不变 |
| `p2_holdout_scenarios.py` / `_v3.py` | SHA 不变 |
| 账本 | `ca9dceb9…`、1,932,692 B、952 次预留，未改 |
| budget / GO | 仅按裁定改动：budget 回 40；4 份 GO 换 40（旧 50 逐字节归档） |
| 新增 untracked | 全部在 `fix-1/independent/`；independent 外无新建文件（`tools/p2_h2_v3_controlled_execute.py` 是既有 untracked，仅改 1 行常量） |

证据：`00-snapshot-start.json`、`00-snapshot-end.json`、`preservation-compare.json`。

---

## 3. 第三部分：能否进入真实跑

**不可进入真实 v3 跑**——唯一阻塞是 A 的纯指代回归（N2/N2b：`城东店和城西店的这两个/这几个…` 由改前 legacy 澄清变成改后 rag 以 4 行整表作答）；预算/计划/GO 闸门本身已 4/4 对齐（预算 40、`max_requests=1137`、check-only 零发送零写全过），C 冻结、密文/语料、账本、HEAD/暂存均未破。建议先补 A 的指代守卫（+1 条带门店的纯指代回归用例），再重跑独立验收；同时请经理对 §1.3（22 条而非 15 条）与 §1.4（2 条测试仍红）给出裁定。

---

## 4. 结论与分歧清单

**判定：FAIL**（窄口径：A 的“纯指代”硬性反例失败；其余 A 正例、B、未回退、测试 22、零调用、保全均绿）。

| # | 分歧/更正 | 依据 |
|---|---|---|
| D1 | tracked modified 回退后是 **22**（15 既有 + 7 fix-1），不是 15；dev-report 的“16 条”笔误 | `preservation-compare.json`、7 文件改前=HEAD |
| D2 | 2 条漂移测试**未恢复绿**：1 条需 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=40`，1 条硬编码 `limit_cny==20.0`（line 208） | §1.4 日志 |
| D3 | A 的“纯指代仍澄清”只覆盖 bare 形式；带已点名门店的“这两个/这几个”被放行，且是 fix-1 引入的回归 | `A-anaphora-regression.json`、`A-planner-multi-target.json` |
| D4 | dev-report §0.1/§4.2 的 status 集合描述与 §4.1 的 7 条 tracked 文件自相矛盾 | dev-report 原文 |
| D5 | `v3-go/report.md`、`plan-index.json` 仍是 50 时代历史件；真实跑须用 `rollback-40\` | §1.5 |

**残余（不隐瞒）**：未知门店只答已知名、不披露未知名（既有）；2×2 交叉仍澄清（可能偏保守，按“配对不明=真歧义”处理）；多物品缺记录不披露；`record_facts` 过严与 `D01_` 前缀两项未修（dev-report §3，未复验）。

## 5. 证据索引

- `independent/00-snapshot-start.json` / `00-snapshot-end.json` / `preservation-compare.json`
- `independent/budget-rollback.json` / `rollback-summary.json`
- `independent/rollback-40/{plan-index.json,go-regeneration.json,go-install.json,check/run*.json}`
- `independent/A-planner-multi-target.json` / `A-anaphora-regression.json` / `A-query-baseline-reconstruct.json` / `A-service-baseline-reconstruct.json`
- `independent/B-business-date-filter.json`
- `independent/netguard/*`
- `independent/pytest-*.log`
