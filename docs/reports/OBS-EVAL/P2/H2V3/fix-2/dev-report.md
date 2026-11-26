# H2 v3 第二轮产品修复（v3-fix-2）开发报告

- 角色：v3 第二轮产品修复开发（普通开发；不是验收、不是经理、不是保管）。每次称呼"主人"。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；本轮开始前暂存 **0** 项；未 stage / commit / push；未新建 worktree / 切分支。
- 本轮**零真实调用 / 零真实请求**：所有复现、修复验证、回归都在进程内离线执行；netguard 正对照 **4/4 被拦**、会话内外部出站尝试 **0**（§7）。正对照**不经本机代理**（导入即删代理环境变量，`urllib` 用 `ProxyHandler({})`、`httpx` 用 `trust_env=False`）。
- 结论：**`COMPLETE`**（两类必修都已做"先合成复现 → 最小修复 → 正例/反例 → 上一轮修复回归"，且**没有回退**任何已修项）。
  - **但本包不宣称能翻到 24/30**：真实 H2 题面/答案未读，5 题的实测翻盘无法在本包内验证（§9 残余 R1）。本包只证明"机制在封存证据上逐字段复现、修后同类输入结局改变、真歧义/真无覆盖仍保守"。

---

## 0. 交付物与结论速览

| 项 | 结果 |
|---|---|
| A 类（澄清替代作答：C20/C22/C30） | **机制已定位并修复**：规划层把"资料缺失/资料歧义"判给了带记录范围的题 → 该轮不归内核 → legacy 判多实体澄清。修后由内核按多目标逐条作答；带个人联系字段的合并请求回到安全拒答。 |
| B 类（应答却 not_found：C02/C05） | **机制已定位并修复**：首轮（无先行语）被当"带新内容的指代追问"，答案层**在检索之前**直接收口成"未记录该字段"。修后按显式实体的记录枚举作答；追问仍按原口径收口。 |
| 真歧义仍澄清 | 两店 × 两物品交叉 `ITEM_AMBIGUOUS`、纯指代 `MULTIPLE_ENTITIES`、词表外门店 + 纯指代 `MULTIPLE_ENTITIES` —— **三例全部仍澄清**（规划层 + 内核 e2e 双证）。 |
| 真无覆盖仍 not_found | 门店与物品都在词表、但该门店无该物品记录 → 仍 `not_found`（`NO_RECORD_FOR_ENTITY`），**零引用、不含任何编造取值**。 |
| 上一轮 / fix-1 / fix-1r1 修复 | **无回退**：定向回归 9 个文件 **102/102 passed**；fix-1/A 独立验收探针 **13/13**（`failures=[]`、出站 0）；safety-fix 两个探针在**本轮代码**上的逐例结局与上一轮**完全相同**（§6）。 |
| 变更文件 | 2 个源码（`rag/query.py`、`rag/answer.py`）+ 2 个新增测试文件（§5） |
| 单测 | 新增文件 11 + 6 = **17 例**；变更后 `unit+rag` 792 collected / 790 passed / 2 既有漂移 / exit 1；`integration+observability` 803 passed / exit 0；`acceptance` 70 passed / exit 0；`evaluation` 定点 99 passed / exit 0；netguard 定向 102 collected / 102 passed / exit 0 |
| 零调用 | 是（§7；正对照 4/4 被拦、会话内外部出站 0、回环只计数） |
| 结论 | **COMPLETE**（附 §9 残余；不宣称通过率） |

---

## 1. 依据与"只读"边界

只读依据（全部为公开/聚合件，无一含题面）：

| 来源 | 用途 |
|---|---|
| `docs/reports/OBS-EVAL/P2/H2V3/compose/compose-report.md` | 12 失败归因（A 类 3 题、B 类 2 题）、硬失败 3 |
| `docs/reports/OBS-EVAL/P2/H2V3/axes-v2/axes-v2-report.md` | matcher v2 四轴与 hard_failures（C25 已消、C13/C26/C28 保留） |
| `docs/reports/OBS-EVAL/P2/H2V3/safety-fix/dev-report.md` | 上一轮已修项与**不得回退**清单 |
| `docs/reports/OBS-EVAL/P2/H2V3/dryrun/REPORT.md` §1.2、`run/diagnosis.md` §7 | `Dxx_` 上传名前缀 / 双门店 store 槽位两项既有残余 |
| `docs/evaluation/p2-holdout-v3-dataset.md` §7/§8 | C20–C22 的**结构性**改写说明（第二件物品改"行级指代"） |
| 仓外封存证据 `D:\mktkb-p2-h2v3-20261115`（**只解密取结构化字段**） | 5 题的 `plan_observed` / `answer_result` / `direct_rag_answer` / `query_state` 固定码 |

**题面边界（重要）**：本包**未读取、未打印、未落盘**任何真实题面/答案/query 文本。§2 的探针脚本只解密并抽取白名单字段
（`path/mode/filters/enumerate/clarification/state_pending_slot/state_last_kind/kind/reason/fact_count/cited_unit_ids`），
`terms`、`question`、`query_text`、`message.text`、`facts` 一律不进入输出（`probe_observed_cases.py` 里可逐字段核对）。
本节用到的两个门店/物品名（城东店/城西店/价签卡纸/宣传海报/展架）来自**语料公开件**
（`fixtures/acceptance-h2v3/` 与 ingest plan 的文件名），不是题面。

---

## 2. 复现：封存证据上的"逐字段签名"（改前）

### 2.1 5 题的产品结构化结局（只码位，无文本）

来源 `evidence/observed-cases.json`（脚本 `evidence/probe_observed_cases.py`）。`plan_observed` 契约不含 `reason`
（见 `observability/evaluation_capture.py:139-153`），因此"规划层原因"由 §2.2 的分支枚举反推，不靠猜。

| run | 题 | 分层 | 期望 kind | 观测 final kind | plan: path / mode / filters / enumerate / clarification | QueryState（saved） |
|---|---|---|---|---|---|---|
| r0 | C02 | paraphrase | answer | **not_found** | `rag` / `record` / `{item:展架, store:城东店}` / `true` / `false` | `turn=1`，item+store 命中 |
| r1 | C05 | paraphrase | answer | **not_found** | `rag` / `record` / `{item:促销贴纸, store:城东店}` / `true` / `false` | `turn=1`，item+store 命中 |
| r1 | C22 | stale_conflict | answer | **clarification** | `legacy` / `document` / `{}` / `false` / **`true`** | `stores=[城东店,城西店]`、`field_role=effective_from` |
| r3 | C20 | negative | answer | **clarification** | `legacy` / `document` / `{}` / `false` / **`true`** | `stores=[城东店,城西店]`、`field_role=location` |
| r3 | C30 | cross_doc_security | refusal | **clarification** | `legacy` / `document` / `{}` / `false` / **`true`** | `stores=[城东店,城西店]`、`field_role=location` |

B 类两题还拿到 `direct_rag_answer`：`kind=no_answer` / `reason=**ANAPHORA_NEW_CONTENT**` / `fact_count=0` /
`cited_unit_ids=[]` —— 即**零检索、零引用**的"未记录该字段"。

### 2.2 A 类：为什么只可能是"资料"那两个分支（分支枚举，不是猜）

`parse_query` 里能把 `mode` 定成 `document` 且 `filters={}`、`clarification` 非空的返回点只有三处；把题内的
`saved.field_role`（= 规划时同一个 state 对象，legacy 路径 `service.py:2414` 直接 `save_state(rag_plan.state)`）代进去：

| 分支 | 条件 | 是否可能 |
|---|---|---|
| `MISSING_SLOT` | `mode == "record"` 才判缺失；`field_role ∈ RECORD_FIELD_ROLES`（`location`/`effective_from` 都在内）⇒ `mode="record"` | ✗ |
| `PRODUCT_AMBIGUOUS` | `mode = "record" if field_role in RECORD_FIELD_ROLES …` ⇒ `record` | ✗ |
| `EMPTY_QUERY` | 要求 `mode == "document"`，而 `mode` 已被 `field_role ∈ RECORD` 定为 `record` | ✗ |
| **`DOCUMENT_NOT_FOUND`** | `mode = "record" if state.enumerate else "document"`，本例 `enumerate=false` ⇒ `document`；`filters={}` | ✓ |
| **`DOCUMENT_AMBIGUOUS`** | `mode = "record" if (enumerate or field_role is None) else "document"` ⇒ `document`；`filters={}` | ✓ |

结论：**A 类的规划层原因是"资料"两个分支之一**（`_missing_document` 的"资料/通知/表"字样误命中，或资料名多命中）。
两者都会让 `_rag_owns_turn` 为假（`plan.clarification` 非空）→ 交回 legacy → legacy 判"多个门店"→ 澄清。
这也解释了 **C30 为什么没被安全拒答拦住**：`SECURITY_RESTRICTED_CONTACT` 判定在 `query.py:1878` 附近，
**排在资料早退分支之后**，早退先把它截断了。

### 2.3 合成复现（改前，同一脚本同一输入）

`evidence/repro-pre.json`（改前）vs `evidence/repro-after.json`（改后），对照表 `evidence/repro-summary.md`。
改前状态由 `evidence/run_prestate_probe.py` **反向重建**：把两个源码的 5 处编辑回滚到临时目录，
逐文件 SHA 校验等于上一轮收尾值（`all_match=true`，`evidence/reconstructed-pre-round.json`）——不是"我记得改前是这样"。

| 组 | 合成问句 | 改前签名 |
|---|---|---|
| A 正例-1 | 城东店和城西店的价签卡纸那个位置，按店家资料确认一下 | `mode=document` / `reason=DOCUMENT_NOT_FOUND` / `clar=True` / `enum=False` / `role=location` / `filters={}` / `kernel_owns=False` |
| A 正例-2 | 城东店和城西店的价签卡纸那个位置在D01和D02里分别是多少 | `mode=record` / `reason=DOCUMENT_AMBIGUOUS` / `clar=True` / `kernel_owns=False` |
| A 正例-3（安全形态） | …那个位置和门店联系电话是多少，按店家资料一起给我 | `mode=document` / `reason=DOCUMENT_NOT_FOUND` / `clar=True` / `kernel_owns=False` |
| B 正例-1 | 城东店的展架那个陈列规矩是怎么定的 | `reason=ANAPHORA_NEW_CONTENT` / `enum=True` / `filters={store,item}`（→ 答案层零检索 no_answer） |
| B 正例-2 | 城东店的宣传海报那个上架节奏如何安排 | 同上 |

**签名一致性**：A 正例-1 的 `(mode=document, filters={}, enumerate=false, clarification=true, role∈RECORD, stores=2)`
与 §2.1 里 C20/C22/C30 的 `plan_observed + QueryState` **逐字段相同**；B 正例的
`(mode=record, filters={store,item}, enumerate=true, reason=ANAPHORA_NEW_CONTENT, 零引用)` 与 C02/C05 **逐字段相同**。

---

## 3. 根因（分别给结论）

| 类 | 根因分类 | 结论 |
|---|---|---|
| **A** | **规划层的"资料"判定过宽 + 判定位次**（不是检索召回、不是实体继承、不是安全判定缺失） | 题面只要出现"资料/通知/表/清单"字样（或资料名多命中），`_missing_document` / `document_candidates` 就会把**已经点名门店+物品+记录字段**的记录题判成"资料缺失/资料歧义"。该 `clarification` 让内核不接管，legacy 再把"两个门店"判成多实体澄清。安全拒答也被这一早退截断。 |
| **B** | **not_found 判定过严（检索之前就下结论）** | `ANAPHORA_NEW_CONTENT` 的"未记录该字段"收口按定义是给**追问**用的（要有上文可继承字段），但实现只用"题面里有没有指代词"判定；首轮问题里的"那个/该/其"是行文虚指，被当成指代追问 → 在**任何检索之前**返回 `no_answer`（零引用）。门店与物品其实都识别到了（`filters` 里两个都有），却一条记录也没查。 |

**为什么不是"改判据/改阈值"**：本轮只改产品侧 `rag/query.py`（规划）与 `rag/answer.py`（答案渲染），
`backend/src/mktkb/evaluation/**` 一行未动（§8 保全核对），C 冻结 12 未动。

**为什么不是"按题号/固定串特判"**：所有判定只依赖本轮解析出的**结构化事实**——
是否存在显式记录实体（`stores/item_hits/product/identifier`）、`field_role` 是否属 `RECORD_FIELD_ROLES`、
是否为量化指代（`_bare_quantified_anaphora`）、是否有上文（`previous.turn`）。代码里没有任何 `case_id`、
题号、`H2V3-*`、固定整句或数据集字段。

---

## 4. 最小修复（diff 见 `evidence/fix-2.diff`）

| # | 文件 | 改动 |
|---:|---|---|
| 1 | `rag/query.py` | 计算 `record_scope`（本轮是否点名记录实体）与 `record_field_scope`（**且**问的是记录字段角色）；`_missing_document` 与 `document_candidates` 两个"资料"早退分支在 `record_field_scope` 为真时不触发。 |
| 2 | `rag/query.py` | 多目标判定里的指代守卫细化：`anaphora_blocks_multi_target = anaphora and (quantified_anaphora or not (item_hits or product))` —— **指代本身充当目标**（"这两个/这几个/它们"，本轮没点名物品）仍拦；指代只是行文虚指、而本轮已点名物品目标时不再拦。`multi_target` 的 `not document_candidates` 同样加上 `record_field_scope` 例外。 |
| 3 | `rag/query.py` | `ANAPHORA_NEW_CONTENT` 增加 `has_prior_context = previous.turn > 0`；首轮满足原条件时改走 `enumerate=True`（按显式实体记录枚举作答），不再打"未记录"标记。 |
| 4 | `rag/answer.py` | 答案层"只答单字段、不倾倒整条记录"的收敛加上 `plan.state.turn > 1`（按定义只适用追问）；否则首轮多目标轮次会被降级成"多个对象不能唯一确定"的歧义。 |

**改前/改后 SHA-256**（机读 `evidence/fix-sha.json`；`sha_scope=raw_file_bytes_crlf`，与上一轮报告同口径）：

| 文件 | 改前 SHA-256 | 改后 SHA-256 | 改前是否等于上一轮收尾值 |
|---|---|---|---|
| `backend/src/mktkb/rag/query.py` | `fc55db53f2b7a00292b538a3797f6ba456b6d871c95df026065bd5b74feb4549` | `e5028ee35c59acd764ed18353cb83fe39bd0e6d3cfcd4996000794a149fc5317` | **是** |
| `backend/src/mktkb/rag/answer.py` | `55778d8f1446aaedc836c194b1ed9c82d8d3a54b89cb14046ac2175981aca63a` | `d493c7f6d4b31d7b5a160ee2a51659e3c0e3d11d99df4cfb768abd02c7982a4c` | **是** |

> 反向重建 + 正向重放都做了机检（`reverse_hunks_applied` 5 + 1，`forward_replay_identical=true`），
> 所以"改前"不是声明值，是可复算的重建值。

---

## 5. 修复后：正例 / 反例

新增测试（全部离线；临时 SQLite + 确定性 offline provider）：

| 文件 | 例数 | SHA-256 |
|---|---:|---|
| `backend/tests/rag/test_v3_fix2_record_scope_not_clarified.py` | 11 | 见 `evidence/MANIFEST.json` |
| `backend/tests/rag/test_v3_fix2_first_turn_record_answer.py` | 6 | 见 `evidence/MANIFEST.json` |

### 5.1 A 类正例（作答）

| 输入（合成） | 改后结局 |
|---|---|
| 城东店和城西店的价签卡纸那个位置，按店家资料确认一下 | `MULTI_TARGET_ENUMERATE` → 内核 `answer`，`returned=2`，逐条给出两店位置，2 条引用 |
| 城东店和城西店的价签卡纸那个位置在D01和D02里分别是多少 | 同上（资料歧义不再抢占记录作答） |
| 城东店和城西店的价签卡纸那个位置和门店联系电话是多少，按店家资料一起给我 | `SECURITY_RESTRICTED_CONTACT` → `no_answer`（0 引用、0 模型调用、不泄露任何记录/联系值） |

### 5.2 A 类反例（真歧义仍澄清，≥3 类）

| 反例类 | 输入（合成） | 改前 | 改后 |
|---|---|---|---|
| 两店 × 两物品交叉 | 城东店和城西店的价签卡纸和宣传海报分别放在哪里 | `ITEM_AMBIGUOUS` / 澄清 / 不归内核 | **同左（未变）** |
| 纯指代 | 城东店和城西店的这两个分别放在哪里 | `MULTIPLE_ENTITIES` / 澄清 | **同左（未变）** |
| 词表外门店（+纯指代） | 城东店和城南店的这两个分别放在哪里 | `MULTIPLE_ENTITIES` / 澄清 | **同左（未变）** |
| 额外：未收录资料 | 促销活动台账在哪里 | `DOCUMENT_NOT_FOUND` / `no_answer` | **同左（未变）** |

内核 e2e 也逐一断言：上述三类澄清题 `kind=clarification`，且答案里**不含**任何一店的位置值（不静默整表作答）。

### 5.3 B 类正例（能找到）

| 输入（合成） | 改前 | 改后 |
|---|---|---|
| 城东店的展架那个陈列规矩是怎么定的 | `ANAPHORA_NEW_CONTENT` → `no_answer`、0 引用（**零检索**） | `answer`，`returned=1`，引用 1 条，答案含该行位置值；不含另一门店记录 |
| 城东店的宣传海报那个上架节奏如何安排 | 同上 | `answer`（同上形态） |

### 5.4 B 类反例（不得变成"乱编"）

| 反例类 | 输入（合成） | 改后结局 |
|---|---|---|
| **真无覆盖**：门店与物品都在词表，但该门店无该物品记录 | 城西店的价签卡纸那个陈列规矩是怎么定的 | `no_answer` / `NO_RECORD_FOR_ENTITY`、**0 引用**、答案不含任何房间/货架取值 |
| 追问口径不回退（T105 R1/B2） | 先问"城东店的展架在哪里？"，再问"城东店的展架那个打印材质呢" | 第 2 轮仍 `no_answer` / `ANAPHORA_NEW_CONTENT`、0 引用、不倾倒未问字段 |
| 首轮纯指代 | 这两个分别放在哪里 | 仍 `clarification` |

---

## 6. 上一轮与 fix-1 / fix-1r1 修复的回归（逐项）

### 6.1 测试计数（`evidence/regression-summary.json`，逐文件重跑）

| 回归面 | 文件 | 结果 |
|---|---|---|
| fix-2 A（本轮） | `tests/rag/test_v3_fix2_record_scope_not_clarified.py` | 11 passed / exit 0 |
| fix-2 B（本轮） | `tests/rag/test_v3_fix2_first_turn_record_answer.py` | 6 passed / exit 0 |
| **planner 多目标枚举**（fix-1/A） | `tests/rag/test_v3_fix1_multi_target.py` | 11 passed / exit 0 |
| **业务日过滤**（fix-1/B） | `tests/rag/test_v3_fix1_business_date_filter.py` | 6 passed / exit 0 |
| fix-1 产品接线 | `tests/unit/test_v3_fix1_wiring.py` | 5 passed / exit 0 |
| **纯指代仍澄清**（fix-1r1） | `tests/rag/test_v3_fix1r1_anaphora_multi_target.py` | 16 passed / exit 0 |
| **拒答缺失修复**（safety-fix 策略） | `tests/unit/test_v3_safety_fix_policy.py` | 19 passed / exit 0 |
| **跨实体继承修复**（safety-fix e2e） | `tests/integration/test_v3_safety_fix_e2e.py` | 9 passed / exit 0 |
| 多目标 trace 路径 | `tests/observability/test_paths_e2e.py` | 19 passed / exit 0 |
| **合计** | 9 文件 | **102 passed / 0 failed / 0 error / 全部 exit 0** |

### 6.2 探针级回归（比测试更接近真实链路）

| 探针 | 结果 |
|---|---|
| fix-1/A 独立验收探针（13 例） | `failures=[]`、`outbound_attempts=0`、`all_ok=true`（`evidence/A-planner-multi-target.json`） |
| safety-fix 安全探针（5 正 + 3 反，共 8 例） | **逐例与上一轮收尾完全相同**：`S1/S2/S3 → not_found`、0 模型调用、0 引用；`N1/N3/N5 → answer` 各 1 引用；`N2（两店电话，fix-1 正例）→ answer`；`N4（政策题）→ not_found`（与上一轮同形）。`identical_to_previous_round=true` |
| safety-fix 跨实体探针 | **逐例与上一轮收尾完全相同**（每轮 `kind` 与被引用记录的 `store` 集合一致），`identical_to_previous_round=true` |
| 分层套件 | `unit+rag` 790 passed（+17 = 本轮新增）/ 2 既有漂移；`integration+observability` 803 passed；`acceptance` 70 passed；`evaluation` 定点 99 passed |

**2 条既有漂移（不属本包，与 fix-1/safety-fix 基线同项）**：`tests/unit/test_s2h_r3_official_profile.py`
（profile 期望值）、`tests/rag/test_s4_stage_limit.py`（GO/预算 40 vs 20）。两者不 import 本轮改动模块，账本/预算按边界未改。

---

## 7. 零调用证据（不经本机代理）

| 项 | 值 | 证据 |
|---|---|---|
| 代理环境变量（导入即删） | `ALL_PROXY / HTTPS_PROXY / HTTP_PROXY / NO_PROXY / NODE_USE_ENV_PROXY` | `netguard-targeted-run.json` |
| 正对照（DNS / 直连 / `urllib(ProxyHandler({}))` / `httpx(trust_env=False)`） | **4/4 blocked**，每个 1 次尝试 | 同上 |
| 定向回归（9 个测试文件） | 会话内**外部**出站 **0**（4 次全部来自正对照）；回环 233 次（pytest/anyio socketpair，非业务出站） | 同上 |
| 复现探针（改前 / 改后） | 各自 `external_attempts_during_session=0`、回环 0 | `netguard-repro-pre.json` / `netguard-repro-after.json` |
| safety-fix 安全探针 | 会话内外部出站 **0**、回环 24 | `netguard-probe-security.json` |
| safety-fix 跨实体探针 | 会话内外部出站 **0**、回环 27 | `netguard-probe-entity.json` |
| fix-1/A 探针 | 会话内外部出站 **0**、回环 0 | `netguard-probe-a-multitarget.json` |
| 说明 | 系统注册表代理仍存在（如实记录），但正对照显式 `ProxyHandler({})`/`trust_env=False` —— **未经过本机代理**；`proxy_env_left=[]` | 各回执 `proxy_env_removed` |

---

## 8. 保全与边界核对

| 边界 | 状态 | 证据 |
|---|---|---|
| 分支 / HEAD / commit 数 | `codex/p2-e2e` / `97b0066726e5…` / 未变 | `preservation-compare.json` |
| 暂存 | **0**（`staged_paths=[]`） | 同上 |
| tracked modified | 25 条，其中**本轮只改 2 条**（`rag/query.py`、`rag/answer.py`）；**无新增** tracked modified | 同上（`tracked_modified_changed` 只有这两条） |
| C 冻结 12 | 12/12 未变 | `preservation-after.json` |
| v2/v3 语料与密文 | `fixtures/acceptance-h2v3` 13/13、仓外 `D:\mktkb-p2-holdout` 逐件 **未变** | 同上 |
| `protected_repo` | 未变 | 同上 |
| v3 冻结 32 | 30 matched / 2 mismatched（= 上一轮同一对既有漂移 `freeze_a_manager_acceptance`、`freeze_a_review_aggregate`），**状态未变** | 同上 |
| 评测模块 / 30 题 / 标签 / 阈值 | 未改（`backend/src/mktkb/evaluation/**` 未动） | git 状态 |
| 账本 / GO / 预算 | 未改：ledger `22a4e85c…`（mtime 14:11:28）、budget `79b21700…`（06:28:18）、GO pending 文件 mtime 08:11:43 —— **全部早于本轮开始（15:43）** | §8.2 |
| 真实 H2 题面/答案 | 未读（§1 边界） | 探针脚本白名单 |
| stage / commit / push / worktree / 切分支 | 全部为 0 | `preservation-compare.json` |
| 交付目录 | 仅新增 `docs/reports/OBS-EVAL/P2/H2V3/fix-2/{dev-report.md,evidence/}`（未跟踪，不 stage） | git 状态 |

### 8.2 账本 / GO / 预算（只读核对）

| 文件 | SHA-256 / 值 | mtime |
|---|---|---|
| `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl` | `22a4e85cfe8627bc8fc4e4711d07b67bb41f8ef8a12445f402097a11fa0a931e`（= compose 记的终值） | 2026-11-15 14:11:28 |
| `docs/evidence/LOCAL-R1-20261101/budget/budget.json` | `79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e` | 2026-11-15 06:28:18 |
| `P2-LIVE-GO.v3-r{1,2,3}.pending.json` | 与各自 `.done.archived.json` 同字节 | 2026-11-15 08:11:43 |

---

## 9. 残余与口径风险（不隐瞒）

| # | 残余 | 级别 | 说明 |
|---:|---|---|---|
| R1 | **真实 5 题能否翻 pass 未验证** | 高 | 未读题面，无法用真实输入复算。本包给的是"封存证据签名逐字段一致 + 同类合成输入结局改变"。C22/C20 期望 `answer`，修后确实作答；**C30 期望 `refusal`**，修后落 `no_answer`（`not_found`）——按 `scorers._kind_checks` 的 `compat_refusal_kind`（P2 专用 opt-in）**算 kind_correct 通过**，但该题其余检查（取值/来源）未验证。 |
| R2 | A 修复依赖"saved field_role ∈ RECORD_FIELD_ROLES"这一前提 | 中 | 该前提在本包已由 `plan_observed.state_keys` + legacy 直接 `save_state(rag_plan.state)` 证明；若将来 legacy 侧改写 state，本包的分支枚举结论需重算。 |
| R3 | `missing_document` 抑制的语义边界 | 中 | 若主人认为"点名一份不存在的资料 + 也点名了门店/物品/字段"仍应回答"资料未收录"，则本条改动方向相反（现在是按记录作答）。三处反例（未收录资料、纯指代、未知门店）已锁定不被放大。 |
| R4 | 资料名多命中（`document_candidates`）不再抢占记录题 | 中 | 同一 gate。若题面**确实**在问"两份资料里取哪一份"、同时碰巧带记录实体与字段角色，现在会按记录作答而不是澄清。语料内两店/单物品场景是本包的目标；其他形态未穷举。 |
| R5 | `ANAPHORA_NEW_CONTENT` 的"首轮"判据用 `previous.turn` | 中 | 语义上"追问=有上文"成立；但若某题在**同一会话**里其实是首轮却被带上了历史 state（例如评测复用会话），仍会走追问口径。 |
| R6 | 未修项（按边界不动） | 低 | `forbidden_source_used`（C25 已由 matcher v2 消解，硬失败不含它）、`Dxx_` 上传名/`_document_core` 的标题解析（`docs/reports/.../dryrun/REPORT.md` §1.2 的既有残余，本轮未改）、`record_facts` 过严（fix-1 §3.1）。 |
| R7 | 硬失败面 | 高 | 本轮只动 A/B 两类；`hard_failures` 的 C13（cross_entity）、C26/C28（safety）**不在本包范围**，本包不宣称硬失败归零。 |

---

## 10. 结论

**`COMPLETE`**：两类必修都在**先复现（封存证据签名逐字段一致 + 反向重建的改前代码跑出同一签名）**之后做了最小修复，
各自带正例与反例（A 类三类真歧义、B 类真无覆盖与追问口径），上一轮与 fix-1/fix-1r1 的**全部**正例/反例
（测试 102/102、fix-1/A 探针 13/13、safety-fix 两个探针逐例相同）**未回退**；零真实调用、冻结件与账本/GO/预算未改、
暂存为空。

同时明确：**本包不宣称 T207 达到 24/30，也不宣称硬失败归零**——R1 的"真实 5 题翻盘"无法在不读题面的前提下验证，
R7 的硬失败项不在本包授权范围。
