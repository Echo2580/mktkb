# H2 v3 fix-1/R1 独立窄验收报告

主人，本报告由 **v3-fix-1/R1 独立窄验收** 出具。口径只有两件事：**N2 回归是否已关**、**R1 是否引入新回归**；并给出能否跑真实基线的结论。验收探针全部自建（门店/物品/问句均与开发用例不同），不照抄开发用例。

- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，172 commit，暂存 0。
- 改动：`backend/src/mktkb/rag/query.py` `f73fc735…` → `82776def…`；`backend/tests/observability/test_paths_e2e.py` `d357fdc3…` → `c0ff388f…`。
- 零真实调用/请求：所有探针为临时 SQLite + offline provider + 纯函数；pytest 与探针均有独立 socket 守卫，正对照 5/5 被拦（含本机代理端口），会话内外站尝试 **0**（§7）。
- **判定：`PASS_WITH_DISAGREEMENTS`**（N2 已关；A 正例全绿；未发现 R1 引入的新回归；4 类新回归面无“多目标整表假放行”，但 2 类仍是“有界作答”而非澄清，见 §4/§9）。
- **`可跑真实基线`**（本轮无阻塞项；条件与残余见 §9）。

---

## 1. N2 已关（自建探针，改前/改后同输入对照）

自建数据：门店 `北苑店/南湖店`（词表外 `西郊店`）、物品 `桌牌/横幅`、位置 `一层东侧/二层西侧/三层中庭/四层入口`、电话 `010-20000001/2`。全部合成，未读真实 H2 题面/答案。

**改前对照**：用本轮 `fix-r1.diff` 反向应用重建 fix-1 终态 `query.py`（SHA `f73fc735…`，与上一轮快照逐字节相同），加载为独立模块，并临时替换 `answer` 模块的 `parse_query` 跑内核对照。

| 用例（已点名门店 + 纯指代） | 改前 planner / 内核 | 改后 planner / 内核 | 判定 |
|---|---|---|---|
| `北苑店和南湖店的这两个分别放在哪里？` | `MULTI_TARGET_ENUMERATE`、`owns=true`、内核 **answer / 4 行** | `MULTIPLE_ENTITIES`、`owns=false`、内核 **clarification / 0 行** | **N2 关** |
| `北苑店和南湖店的这几个分别放在哪里？` | 同上、内核 **answer / 4 行** | `MULTIPLE_ENTITIES`、`owns=false`、clarification | **N2 关** |
| `北苑店和南湖店的这两个电话是多少？` | 同上、内核 **answer / 2 行** | `MULTIPLE_ENTITIES`、`owns=false`、clarification | **N2 关** |
| `北苑店和南湖店的这两个呢？`（无字段词） | `reason=null`、`owns=false`（legacy 澄清） | `ANAPHORA_NO_FIELD`、clarification（经 `identifier` 标记路由内核，但内核仍澄清） | 等价澄清 |
| `北苑店的这两个分别放在哪里？`（单店） | `reason=null`、内核 answer / 2 行 | 同改前：**有界** 2 行（该店两物品） | 未冒充多目标 |

- 改后澄清文案为既有 `multiple_entities_text`（`copy.py:766`），列出 `北苑店、南湖店`；内核 `kind=clarification`、`returned=None`，回答正文不含任何位置/电话值——**没有枚举作答**。
- 改前反向对照的两个 `这两个/这几个` 用例内核均返回 **4 行**（两店全部物品），与上一轮 N2/N2b 现象一致；R1 后归零。
- 单店 + 指代不进入多目标（`planner.reason` 不再是 `MULTI_TARGET_ENUMERATE`），只是按该店既有记录作答 2 行，**门店维没有冒充多目标**。

证据：`independent/probe-fix1r1.json`（N2a–N2e，含 `answers_pre_r1_kernel`）、`independent/_pre_r1_query.py`（SHA `f73fc735…`）。

---

## 2. A 正例未坏（4/4）

| 用例（自建） | planner | 产品/内核 | 证据面 |
|---|---|---|---|
| `北苑店和南湖店的桌牌在哪里？` | `MULTI_TARGET_ENUMERATE`、`owns=true` | answer | `returned=2`；只含 `一层东侧/二层西侧`，不含 `三层中庭/四层入口/五层仓库` |
| `北苑店的桌牌和横幅在哪里？` | 同上 | answer | `returned=2`；只含 `一层东侧/三层中庭` |
| `北苑店和南湖店的电话是多少？` | 同上 | answer | `returned=2`；两个电话逐条，正文无位置行 |
| `北苑店和南湖店的桌牌分别在哪里？` | 同上 | answer | `returned=2`；只含 `一层东侧/二层西侧` |

- 改前/改后 planner 与内核均**完全相同**（`changed_by_r1=false`），R1 没有碰到 A 的正例面。
- 复指限定语（不得过度拦截）也保持放行：`北苑店的桌牌和横幅这两个分别放在哪里？`、`…这两个物品…`、`北苑店和南湖店这两家的电话是多少？` 均 `MULTI_TARGET_ENUMERATE` + answer 2 行（S1–S3）。

---

## 3. 新回归排查（自造 4+ 类）

| 类 | 用例（自建） | R1 后行为 | 改前行为 | 结论 |
|---|---|---|---|---|
| 混合（1 显式 + 1 指代，单店） | `北苑店的桌牌和这两个分别放在哪里？` | answer 1 行（只答显式 `桌牌`，`reason=null`、`owns=true`） | 同改前（answer 1 行） | **非新回归**；未澄清（§4 D1） |
| 混合（1 显式 + 1 指代，两店） | `北苑店和南湖店的桌牌和这两个分别放在哪里？` | answer 2 行（只答显式 `桌牌`）；`reason` 从 `MULTI_TARGET_ENUMERATE` 变为 `null`，产品门控不变 | answer 2 行、`MULTI_TARGET_ENUMERATE` | **非新回归**；未澄清（§4 D1） |
| 混合（无“分别”） | `北苑店和南湖店的桌牌和这两个在哪里？` | `ambiguous` → 产品澄清（2 个候选，`owns=false`） | 改前 `MULTI_TARGET_ENUMERATE`、内核 answer 2 行 | 变严；符合“澄清” |
| 混合（2 显式 + 指代） | `北苑店的桌牌、横幅和这两个分别放在哪里？` | `ITEM_AMBIGUOUS`、clarification | 改前 `MULTI_TARGET_ENUMERATE`、answer 2 行 | 变严；**PASS** |
| 跨轮指代 | 上一轮 `北苑店和南湖店的桌牌在哪里？` → `这两个分别放在哪里？` | answer 2 行，延续上一轮 `桌牌`；不重开整表 | 同改前（answer 2 行） | **非新回归**；上下文延续（§4 D2） |
| 指代 + 词表外门店 | `北苑店和西郊店的这两个分别放在哪里？` | `MULTIPLE_ENTITIES`、clarification；不披露 `西郊店` | 改前 `reason=null`、`owns=true`、answer 2 行（只答北苑店） | 变严；**PASS** |
| 显式枚举含歧义物品 | `北苑店和南湖店的桌牌和横幅在哪里？` | `ITEM_AMBIGUOUS`、clarification | 同改前 | **PASS**（既有面） |
| 指代 + 物品维歧义 | `北苑店的这两个和桌牌、横幅分别放在哪里？` | `ITEM_AMBIGUOUS`、clarification | 改前 `MULTI_TARGET_ENUMERATE`、answer 2 行 | 变严；**PASS** |

- 四类中**没有一类**在 R1 后回到 `MULTI_TARGET_ENUMERATE` 的整表枚举；混合/跨轮是“有界作答”（只答显式/上文已确定的目标），不是“整表假放行”。
- 但“有界作答”不等于“澄清”：混合两店用例与跨轮用例在 R1 后仍 answer（分别为 2 行），与任务书的“澄清或拒绝”字面预期不一致；详见 §4/§9。

---

## 4. null/bare 分流与残余

| 用例 | 结果 |
|---|---|
| `这两个分别放在哪里？` | `MISSING_SLOT`、clarification（未点名对象） |
| `这两个电话是多少？` | `MISSING_SLOT`、clarification |
| 指代 + 物品维歧义（`北苑店的这两个和桌牌、横幅…`） | `ITEM_AMBIGUOUS`、clarification |
| 门店维（两店 + 这两个 / 这几个 / 这两个电话） | `MULTIPLE_ENTITIES`、clarification；**不冒充多目标** |
| 单店 + 这两个 | 有界 answer 2 行（该店两物品）；不改多目标 |

**残余观察（不计本轮硬失败，均与改前相同）**：

- `Z1 北苑店和南湖店的这俩分别放在哪里？`、`Z2 …这些…`、`Z3 …这2个…` 仍是 `MULTI_TARGET_ENUMERATE` + `owns=true` + **4 行整表**。R1 的正则 `_QUANTIFIED_ANAPHORA = (这|那)(两|几|俩)(个|家)`（`query.py:94`）只覆盖“这两个/这几个/这两家/那几家”，不覆盖“这俩/这些/这2个”；dev-report §6.4 已泛化披露“其它量化形式不在本包正则内”。**不是 R1 新回归**（改前同结果），但说明“纯指代守卫”是有限形态，不是通用规则。

---

## 5. diff 只追加 + 重建改前哈希自证

| 项 | 结果 |
|---|---|
| `fix-r1.diff` SHA-256 | `b01fbd213cbb6fb817c4cdeb3f61e60126caebb635b2af6243634fe0bddbcbe1`，19,637 B（与 dev `evidence/MANIFEST.json` 一致） |
| 反向应用当前 `query.py` | 得到 `f73fc7353501e09e65a474fc2599fa4235e1db5d72fc4ea802e0e881f680c372`（= 上一轮快照 fix-1 终态） |
| 反向应用当前 `test_paths_e2e.py` | 得到 `d357fdc392e95cfb32f112f2ee28c1d76c14338028fe019ed2b029af37770384`（= 上一轮快照） |
| 正向应用重建文件 | `query.py` → `82776def…`；`test_paths_e2e.py` → `c0ff388f…`，均逐字节回到当前工作树 |
| 新文件 `test_v3_fix1r1_anaphora_multi_target.py` | 反向应用后完全消失；正向应用后 SHA 与当前文件一致（220 行） |
| 删除行 | **仅 1 行**：`anaphora = any(word in question for word in ANAPHORA_WORDS)` 被扩成两行；**没有任何 fix-1/A 块被删**（`rollback_of_fix1_suspected=[]`） |
| 新增行 | `query.py` +90、`test_paths_e2e.py` +20、新测试 +220 |

**结论**：diff 与改后文件一致；重建改前哈希与上一轮独立验收快照逐字节相同，说明 **R1 没有回退既有未提交改动**。严格说它不是“零删除的只追加”——有 1 行被等价扩写（为接入 `quantified_anaphora` 变量），但没有删除任何 fix-1 内容；见 §9 D3。

证据：`independent/diff-verify.json`、`independent/verify_diff.py`。

---

## 6. 测试计数与 2 个失败定性

| 运行（独立 netguard 下） | collect | passed | failed | exit | 会话内外站尝试 |
|---|---:|---:|---:|---:|---:|
| 定向 34（新 R1 文件 + fix-1 多目标 + wiring + observability 相关） | 34 | **34** | 0 | 0 | 0 |
| `tests/unit tests/rag` | **756** | 754 | **2** | 1 | 0 |
| 2 条漂移定向 + `MKTKB_PROJECT_TOTAL_LIMIT_CNY=40` | 22 | 21 | 1 | 1 | 0 |
| 指代/状态继承/B 业务日相邻回归（5 文件） | 49 | **49** | 0 | 0 | 0 |

- 定向 34 项**真过**（34/34，exit 0；其中 16 条是 R1 新增用例）。上一轮 `tests/unit tests/rag` 是 740 collected / 738 passed / 2 failed；740 + 16 = **756**，说明新增只来自 R1 测试文件。
- 2 个失败与 R1 无关，是既有漂移：
  1. `tests/unit/test_s2h_r3_official_profile.py::test_official_profile_accepted_by_both_entries_and_worst_case_is_2103552`：未设环境变量时 `live_authorization.project_total_limit_cny()` 默认 10.0，与预算 40.0 比对报 `LiveGateError`（`live_authorization.py:627`）；设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=40` 后通过（21/22）。
  2. `tests/rag/test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan`：第 208 行硬编码 `budget["limit_cny"] == pytest.approx(20.0)`，当前 40 → 必红；与 R1 无关。
- 两个测试文件均**不在 tracked modified 清单**（未改）；上一轮 fix-1 独立日志（R1 之前）同样是这 2 条失败（738 passed / 2 failed）。

证据：`independent/pytest-targeted.log`、`pytest-unit-rag.log`、`pytest-drift-with-env40.log`、`pytest-anaphora-integration.log` 及对应 `*-netguard.json`。

---

## 7. 零调用（正负对照，不经本机代理）

独立守卫 `independent/netguard_plugin.py`（自建）：导入即删 `ALL_PROXY/HTTPS_PROXY/HTTP_PROXY/NODE_USE_ENV_PROXY/NO_PROXY`；接管 `connect/connect_ex/create_connection/getaddrinfo`，回环放行并计数，非回环拦截并计数；**本机代理端口 `127.0.0.1:7897` 单独拦截**（不计作回环放行）。

| 运行 | 正对照（4 外部 + 本机代理） | 会话内外站尝试 | 回环（放行/计数） |
|---|---|---|---|
| 定向 34 | **5/5 blocked**（本机代理对照 `proxy_attempts=1`） | **0** | 16 |
| `tests/unit tests/rag` | **5/5 blocked** | **0** | 55 |
| 漂移定向（env=40） | **5/5 blocked** | **0** | 0 |
| 指代/状态/B 相邻 | **5/5 blocked** | **0** | 569 |
| 自建探针 `probe_fix1r1.py` | 自身 socket 守卫 | **0**（`outbound_attempts=[]`） | — |

- 正对照：`dns_getaddrinfo`、`direct_tcp_192.0.2.1`、`urllib + ProxyHandler({})`、`httpx + trust_env=False`、`127.0.0.1:7897`（本机代理端口）。
- **本机代理事实**：删除环境变量后，Windows 注册表仍让 `urllib.getproxies()` 返回 `http://127.0.0.1:7897`；守卫对该端口单独拦截，`proxy_attempts_total=1` **仅来自该正对照**，会话内没有任何连接指向 7897；四组 `loopback_targets_unique` 均为 anyio/socketpair 的临时端口。**没有任何请求经过本机代理**。
- 未运行真实 H2、未调用模型/embedding/rerank、未解密、未发外部请求；真实 H2 题面/答案未读。

---

## 8. 保全（与 fix-1 收尾快照逐字节对比）

| 项 | 结果 |
|---|---|
| HEAD / 分支 / commit | `97b00667…` / `codex/p2-e2e` / 172，前后相同；**0 新 commit** |
| 暂存 | **0 项** |
| tracked modified | **22** 条，与 fix-1 快照路径集合相同；**只有** `backend/src/mktkb/rag/query.py`、`backend/tests/observability/test_paths_e2e.py` 哈希变化（即 R1 两文件） |
| C 冻结 12 | **12/12 逐字节相同**（与 fix-1 收尾快照相同；fix-1 已对冻结清单核过 12/12） |
| v2/v3 密文与语料 | 13 件全部相同，无额外文件（排除 `keys/`） |
| `fixtures/acceptance-h2v3` | 13 件全部相同 |
| 保护仓文件（14） | `p2_holdout_scenarios.py`、`p2_holdout_scenarios_v3.py`、`p2-h2-scenarios-H2v3.json`、`p2-holdout-v3.source-map.json`、`p2-source-lifecycle-v1.json`、`p2-stale-source-criterion-v1_1.md`、4 份 GO、`budget.json`、`live-ledger.jsonl`、`p2-ingest-plan-H2-v3.json`、`pre-registration.json` 全部相同 |
| v3 冻结 32 | **30/32**，仍为 `freeze_a_manager_acceptance`、`freeze_a_review_aggregate` 两件不一致（会话前即如此，本轮未变） |
| 账本/预算 | 账本 `ca9dceb9…`、1,932,692 B、952 次预留不变；预算 `79b21700…`（40 元）不变 |
| untracked | 2,628（`git status -uall`；含本包新增 18 个 `independent/` 文件 + 2 个根级交付 `review-aggregate.json`/`independent-review.md`；新增均在报告目录，未改产品） |
| 22 条 tracked modified 分解 | 15 条既有基线 + 7 条 fix-1 tracked 文件（`rag/types.py`、`rag/retrieval.py`、`retrieval/service.py`、`test_paths_e2e.py`、`test_p1_t103_record_fallback_http.py`、`test_t207_fix_conflict_r1.py`、`test_p1_t103_record_fallback.py`）；本轮没有新增 tracked 路径。15 条既有：`.claude/handoffs/_index.md`、`conversations/service.py`、`evaluation/cli.py`、`p2_diagnostics.py`、`p2_holdout_scenarios.py`、`p2_live.py`、`p2_runner.py`、`p2_scoring.py`、`product_adapter.py`、`qa/service.py`、`rag/index.py`、`rag/query.py`、`tests/rag/test_query_state.py`、`tests/unit/test_conversations.py`、`T207-QUALITY-REPAIR/manager.md` |

证据：`independent/preservation-after.json`、`independent/preservation-compare.json`、`independent/preservation_snapshot.py`。

---

## 9. 判定、分歧与“能否跑真实基线”

### 9.1 判定

**`PASS_WITH_DISAGREEMENTS`**：N2/N2b 回归已关（改前内核 4 行 → 改后澄清、0 行；产品层 `owns=false`/clarification）；A 四个正例全绿；R1 未引入新的多目标整表放行；diff/测试/零调用/保全均绿。

### 9.2 分歧（不隐瞒）

| # | 分歧 | 依据/裁定建议 |
|---|---|---|
| D1 | **混合（1 显式 + 1 指代）没有澄清**：`北苑店和南湖店的桌牌和这两个分别放在哪里？` R1 后只答显式 `桌牌` 2 行（`reason=null`、`owns=true`），不是“澄清或拒绝”。该路由在 R1 前、甚至 fix-1/A 之前的 baseline（`5a7ed26b…`，自建探针 `pre_fix1_baseline`）就是“有界 2 行”（`reason=null`、`enumerate=true`、`owns=true`），**不是 R1 新引入，也不是 fix-1/A 新引入**；dev-report §6.2 已披露，开发测试也锁定了 `returned=2`。若经理要求“未解析指代必须澄清”，需另开任务改 `enumerate && item_filter` 的既有路由。 | `probe-fix1r1.json` R1a/R1b、`answers_pre_r1_kernel`、`pre_fix1_baseline` |
| D2 | **跨轮纯指代不澄清**：上一轮两店一物品后，`这两个分别放在哪里？` 延续上文 `桌牌` 2 行（R1 前后相同，fix-1/A 前 baseline `5a7ed26b…` 也是 2 行）。这是上下文延续而非整表假放行；任务书“澄清或拒绝”的字面预期未满足。 | R2 用例、`pre_fix1_baseline.R2_cross_turn_turn2` |
| D3 | **“diff 只追加”不是零删除**：有且仅有 1 行 `anaphora = any(...)` 被等价扩写为两行（+90/−1）；没有删除任何 fix-1/A 内容，反向应用逐字节回到 `f73fc735…`。 | `diff-verify.json` |
| D4 | **相邻量化形式仍是旧路**：`这俩/这些/这2个 + 已点名门店` 仍 `MULTI_TARGET_ENUMERATE` + 4 行（R1 前后相同）。N2 命名的“这两个/这几个”已关，但正则不是通用纯指代守卫；dev-report §6.4 仅泛化披露。 | Z1–Z3 |
| D5 | v3 冻结 32 仍 30/32（`freeze_a_manager_acceptance`/`freeze_a_review_aggregate`），会话前即不一致；不是本轮改动，但跑前应知悉。 | preservation-compare |

### 9.3 能否跑真实基线

**`可跑真实基线`**——上一轮唯一阻塞项 N2/N2b 已关闭；本轮没有新的多目标整表假放行、没有回退既有未提交改动、没有破坏 C 冻结/密文/语料/fixtures/账本/预算/GO；2 条测试红是既有漂移。

条件/注意事项：

1. 真实跑必须用 **40 元口径的 rollback-40 计划/绑定/GO**（`D:\mktkb-p2-h2v3-20261115\rollback-40\`，计划/绑定/GO/check 均在；4/4 `check` `ok=true`、`zero_send` 0、`zero_write` 预算/账本不变、952 次预留）；`v3-go/report.md`、`plan-index.json` 仍是 50 元时代历史件，不能直接当可执行计划。
2. 已核 GO 哈希：r0 `dbc198c8…`、r1 `a8516ac3…`、r2 `d7edf6d2…`、r3 `d681b673…`；预算 `79b21700…`；账本 `ca9dceb9…`。
3. 混合指代（D1）/跨轮（D2）/相邻量化形式（D4）是**跑前已知残余**：不会造成整表假放行，但可能让个别问法只答显式目标或沿用上文；若真实 H2 场景含这些形态，请在评分口径中预先登记，或先另开任务收紧。
4. 报告中的“可跑”只覆盖本轮验收边界（N2 + 新回归 + 保全），不替代经理对 D1/D2/D4 口径与 2 条既有测试漂移的裁定。

---

## 10. 证据索引

- `independent/diff-verify.json` / `verify_diff.py`
- `independent/probe-fix1r1.json` / `probe_fix1r1.py` / `_pre_r1_query.py` / `probe-fix1r1-run.log`
- `independent/preservation-after.json` / `preservation-compare.json` / `preservation_snapshot.py`
- `independent/netguard_plugin.py`
- `independent/pytest-targeted.log` / `pytest-targeted-netguard.json`
- `independent/pytest-unit-rag.log` / `pytest-unit-rag-netguard.json`
- `independent/pytest-drift-with-env40.log` / `pytest-drift-official40-netguard.json`
- `independent/pytest-anaphora-integration.log` / `pytest-anaphora-integration-netguard.json`
- 开发包：`dev-report.md`、`evidence/fix-r1.diff`、`evidence/planner-before/after.json`、`evidence/before-after-summary.json`、`evidence/MANIFEST.json`（21/21 文件哈希核过）
- 上一轮：`docs/reports/OBS-EVAL/P2/H2V3/fix-1/independent-review.md`、`fix-1/independent/00-snapshot-end.json`
