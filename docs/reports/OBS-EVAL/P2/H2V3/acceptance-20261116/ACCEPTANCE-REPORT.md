# T207 离线修复独立验收报告（2026-11-16）

- 验收角色：主人指定的独立验收负责人（非开发、非经理）。
- 范围：本轮 T207 零调用/离线修复交付 + 四硬失败分诊 + 保护现场；不改产品、不跑真实 H2。
- 依据：`2026-11-16-001048-t207-independent-review-and-go.md`、`INDEPENDENT-REVIEW-BRIEF.md`、`FINAL-REVIEW-PACK.md`（v10）、`CLOSEOUT-2026-11-15.md`、`CONTROLLED-DIAG-PROPOSAL.md`。
- 本报告所有“通过”均指**我本人复跑/复核所得**；开发自测只作为对照，不作为判定依据。

---

## 0. 三句结论（先给结果）

1. **离线修复验收结论：有条件通过。** 本轮 6 个源码/工具文件的增量与 baseline 逐字节可还原；17 项保护件、账本/预算零变化；在有效网络守卫下我独立复跑 123+26+6 项与 35 项新增合成、14 项自建探针、7 项 HTTP 用例全部通过；但“四个硬失败根因映射与闭环”这一本轮自设目标**未完成**，交付自己也未声称完成。
2. **能否进入受控真实诊断：可以进入“待主人批准 + 待新计划”的准备阶段，尚不能执行。** 技术上入口/预算/账本/成本中心余量均够（计划上界 115 请求、1.100288 元），但当前不存在绑定本轮工作树的新私有计划，也没有可签发的新 GO；且 115 若花满，余 112 请求不足再跑约 126 请求的一轮全量。
3. **T207 质量结论：未通过。** 真实基线仍是 **20/30、硬失败 4**（C13/C22/C26/C28），本轮没有任何新的真实成绩；不得把离线验收通过写成 T207 通过或 P2 完成。

---

## 1. 授权、范围与边界

- 主人本轮授权：独立验收 + 编写下一阶段 GO；**未**授权发出真实 H2 请求。
- 我未读取：真实题面、答案、私有密文、合同、key、`.env`、`D:\mktkb-p2-holdout` 下任何仓外私有件。
- 我未做：修改产品源码、冻结件、评分门槛、预算、账本、旧证据、GO 槽位；未执行 stage/commit/push/reset/clean/stash、未新建分支/worktree。
- 我只新增：`docs/reports/OBS-EVAL/P2/H2V3/acceptance-20261116/` 下的验收记录、探针与回执。

---

## 2. 现场核验（只读）

| 项目 | 期望/交接值 | 我实测 | 判定 |
|---|---|---|---|
| 分支 | `codex/p2-e2e` | `codex/p2-e2e` | 一致 |
| HEAD | `97b0066726e5b8d6f94cbc0b63a890084550c106` | 同 | 一致 |
| 提交数 | 172（相对交接新增 0） | 172 | 一致 |
| 暂存 | 空 | 0 条 | 一致 |
| tracked modified | 25 | 25 | 一致（路径集合见 §3） |
| untracked | 大量 | 验收开始时 3087（之后新增本目录 6 个文件） | 一致量级 |
| worktree | 2 个历史（1 个 prunable） | `t105-r1-baseline-wt`(prunable)、`backend/.pytest-tmp/T109-verify/base` | 未清理 |

命令：`git rev-parse --abbrev-ref HEAD`、`git rev-parse HEAD`、`git rev-list --count HEAD`、`git diff --cached --name-only`、`git diff --name-only`、`git ls-files --others --exclude-standard`、`git worktree list`。

### 账本与预算（独立重算）

| 项 | 值 |
|---|---|
| 账本行数 | 2547 = 1 条 `historical_import` + 1273 `reserved` + 1273 `result` |
| pairing | reserved 唯一 1273、result 唯一 1273；**无重复、无孤立**，`reserved_without_result=0`、`result_without_reserved=0` |
| 账本 SHA256 | `e007fee3456e5d13f737a82ed29af45eb4707e3576c444e3520d9ca941dc2899` |
| 预算 SHA256 | `79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e`（未改） |
| 项目已用 | 22.8665946（账本 result 合计）+ 0.03（历史导入）= **22.8965946 / 40** |
| P2-LIVE 已用 | **7.8256501 / 20**（余 12.1743499） |
| 请求 | **1273 / 1500**（余 227） |
| 成本中心（P2-LIVE） | `answer_retrieval` 1.6756501 / 8.5（余 6.8243499）；`ocr` 6.15 / 6.5（余 0.35）；`judge` 0、`independent` 0 |
| 无中心归属 | 505 条 result 共 15.0409445 元，均非 P2-LIVE（历史阶段）；P2-LIVE 无未归属 result |

> 与 `PM-DIAG-REVIEW.md` 的三项数字（1.6756501 / 6.15 / 7.8256501）逐位一致；这是我按 `reservation_id` 关联 reserved 的 `cost_center` 后自行重算的结果，未采信其结论。

### 冻结清单复核（32 件）

- 7 件为仓外私有密文（`root=external`），**未读取、未计算哈希**。
- 25 件仓库内冻结件我逐件重算：**23 件一致、2 件不一致**：
  - `H2V3/PM/manager-acceptance.json` 记录 `bd44601c…`，实际 `502e41e1…`；
  - `H2V3/PM/review-aggregate.json` 记录 `eeb72bc3…`，实际 `d8c7abeb…`。
- 冻结时间 `2026-11-14T20:32:40Z`（= 11-15 04:32:40 +08:00），两项文件 mtime 为 `2026-11-15T04:43:01+08:00`，即**冻结后约 10 分钟被修改**。结论：不能写成当前 32/32；这是本轮之前既存差异，本轮未重签、未回填，符合披露要求。

---

## 3. 交付物与差异核验

### 3.1 交付 SHA 清单：40/40 一致

对 `delivery-sha256.json` 的 40 个路径逐一重算 SHA256，**0 缺失、0 不符**。未运行 `build-delivery.py`（避免覆盖开发证据）。

### 3.2 本轮增量可还原

- `round-increment.diff` 共 842 行，涉及 6 个源码/工具文件 + 11 个新增测试文件。
- 我以 `baseline/` 的 6 个原始副本 + `round-increment.diff` 在系统临时目录重建：**先按原样 `git apply` 在 `tools/p2_h2_controlled_execute.py` 处失败**（该文件为 LF、补丁为 CRLF 文本），逐文件 `--check` 显示 5 个通过、该文件不通过。
- 改用 Python 在**归一化行尾后**逐文件重算 `baseline → 当前工作树` 的统一 diff：**6/6 段与交付补丁逐行一致**（`query.py` 82 行、`retrieval.py` 25、`answer.py` 24、`intent.py` 117、`service.py` 84、工具 107）。
- 判定：**增量内容真实且完整**；`git apply` 失败是补丁文本行尾造成的**产物可用性**问题，不是内容偏差（见缺陷 D-1）。

### 3.3 17 项保护件前后一致

`final-protection.json` 的 17 项（C 冻结 12、额外 scenarios/plan/excel、账本、预算）逐项重算：**17/17 现值 = after = before**。其中 `p2_hard_evidence.py`=fba6e606…、`p2_holdout_scenarios.py`=bb9ae59a…、`p2_holdout_plan.py`=d0cb23de…、`excel.py`=83a9ade4… 均逐字节未变。

### 3.4 25 条 tracked modified 的路径集合

代码/测试 23 条 + 文档 2 条（`.claude/handoffs/_index.md`、`T207-QUALITY-REPAIR/manager.md`）。`baseline-tracked.diff` 只含 23 条代码/测试路径，未含这 2 条文档路径（不影响代码增量核验，记为 D-4）。

### 3.5 4 份 GO 与旧快照的差异（按交接要求核查）

| 文件 | fix-2 快照 | 现值 | mtime |
|---|---|---|---|
| `P2-LIVE-GO.json` | 5886f84a… | dbcc8c02… | 2026-11-15 16:47:49 |
| `v3-r1.pending.json` | d4dc1eb2… | 02836020… | 2026-11-15 16:43:26 |
| `v3-r2.pending.json` | b3822026… | 0274d8d4… | 2026-11-15 16:43:26 |
| `v3-r3.pending.json` | 5886f84a… | dbcc8c02… | 2026-11-15 16:43:26 |

- 同目录 `P2-LIVE-GO.v3-max1500-r*.archived.json` 的 mtime 为 16:43–16:48，与本轮最早交付回执（`baseline-protection.json`，18:21:30）**早约 1.5 小时**。时序上与“11-15 真实 r2/r3 运行期间换签/归档”一致。
- 但本轮开工未记录这 4 个路径的哈希，**不能证明它们在本轮前后逐字节未变**；mtime 可被修改，只能作为旁证。我未回填、未改写。

---

## 4. 独立复跑（命令、collect、退出码、守卫）

统一环境：仓库根、`.venv\Scripts\python.exe`（3.12.7）、`MKTKB_NO_DOTENV=1`、`MKTKB_OCR_DISABLED=true`、`MKTKB_RAG_PROVIDER_MODE=offline`、`PYTHONPATH=backend/src;<fix-2/evidence>[;backend/tests/evaluation]`、`-p netguard_plugin -p no:cacheprovider`、每组新 `--basetemp`。

| 组 | 目标 | collect / 结果 | 退出码 | 回执 |
|---|---|---|---|---|
| A | 本轮 11 个新增合成测试文件 | 35 passed | 0 | `receipts/new11-netguard.json` |
| B | 开发声称的 18 文件 123 项组合 | 123 passed | 0 | `receipts/set123-netguard.json` |
| C | `test_conversations.py`+重复事实 `-k record_facts/duplicate/repetition` | 26 passed / 27 deselected | 0 | `receipts/set26-netguard.json` |
| D | binding 保留 6 项 | 6 passed / 22 deselected | 0 | `receipts/set6-netguard.json` |
| E | 我自建验收探针 14 项 | 14 passed | 0 | `receipts/probe-own-netguard.json` |
| F | HTTP 单例 `test_rag_kernel_path_also_refuses_restricted_contact` | 1 passed | 0 | `receipts/http-single-netguard.json` |
| G | HTTP 同文件安全/无害/两店电话/裸追问 4 nodeids（6 项） | 6 passed | 0 | `receipts/http-targeted-netguard.json` |

守卫事实（逐份回执核对）：

- 每组正对照 **4/4 被拦**（DNS、保留 IP 直连、`urllib.ProxyHandler({})`、`httpx(trust_env=False)`），探针使用 `example.invalid` 与 `192.0.2.1`，**未访问 example.com**；
- 会话内**非回环出站尝试 = 0**；回环按策略放行并计数（A 0、B 0、C 0、F 10、G 61）；
- 我这次 shell 里确有代理变量；我在 shell 端的 `Remove-Item` 因注册表大小写重复键报错（未生效），但**测试进程内**由 `netguard_plugin` 在导入时移除了 5 个代理变量（回执 `proxy_env_removed` 逐份记录 `ALL_PROXY/HTTPS_PROXY/HTTP_PROXY/NODE_USE_ENV_PROXY/NO_PROXY`），并配合 `urllib.ProxyHandler({})` 与 `httpx(trust_env=False)`。开发回执的该列表为空，说明其环境本无代理，两者不矛盾。

> 与开发回执对照：`v8-final-product-v2.json`（123/123）、`v8-final-record-v2.json`（26）、`final-binding-v2.json`（6）、HTTP 两回执（1+6）的计数与我的复跑**逐项吻合**；我未采信其结论，而是复跑后自行核对。

### 4.1 一处如实记录：我自己的探针先失败过

自建探针首次运行 1 failed / 13 passed，失败项是我把“无联系字段的交叉歧义”期望成 `no_answer`，产品实际返回 `clarification`（普通澄清面，不是安全拒答）。这是我**探针断言过严**，不是产品缺陷；修正为 `kind in {clarification, no_answer}` 后 14 passed。此处保留，不掩盖。

---

## 5. 独立探针覆盖（自建夹具，不使用开发断言）

文件：`probes/probe_t207_acceptance.py`（14 项），自建临时 SQLite + 离线 provider + 合成行数据。

| 编号 | 我核对的行为 | 结果 |
|---|---|---|
| P1 | 跨店×跨物品 + 联系电话 → `no_answer/SECURITY_RESTRICTED_CONTACT`、零引用、无甲/乙柜与两个电话泄漏 | 通过 |
| P2 | 同一请求去掉联系字段 → 不得变成安全拒答（实际 `clarification`） | 通过 |
| P3 | 财务题、未知门店两条早退分支不得吞掉联系信息策略；无联系字段的未知门店仍走原分支 | 通过 |
| P4 | 物品全字段枚举 + 行内含电话 → 拒答、零引用、电话不外泄 | 通过 |
| P5 | 门店级电话（无物品）→ 正常作答并含电话 | 通过 |
| P6 | 物品全字段枚举、行内无联系字段 → 正常作答 | 通过 |
| P7 | 两店枚举：目标内两店保留、第三店排除 | 通过 |
| P8 | 两物品枚举：目标内两物品保留、第三物品排除 | 通过 |
| P9 | 候选硬过滤：请求内门店通过、请求外门店被拒 | 通过 |
| P10 | 旧单物品（含旧标识 P77）不得收窄新多物品，且 `item` 不进 filters | 通过 |
| P11 | 明确换题后的裸物品追问 → 要求补门店（clarification，intent None） | 通过 |
| P12 | **反例**：无换题的普通裸追问 → 仍继承门店并作答（不被新守卫打成澄清） | 通过 |
| P13 | `_document_core` 仅解 `D99_/V01_` 前缀；`设备D01_`、`D1_`、`DX01_` 不被改动 | 通过 |
| P14 | `V07_` 前缀标题仍能被人类问法“设备巡检表”匹配到同一文档 | 通过 |

---

## 6. 实现审查要点（读码，非仅测试）

| 变更 | 审查结论 |
|---|---|
| `query.py`：安全拒答前移到 `missing_document` 之前 | `parse_query` 自 1372 行起，**首个** `return QueryPlan` 即该分支（1560 行），此前无早退可抢先；所需变量均已定义。 |
| `query.py`：多店/多物品时清旧 identifier、清单值 item | 有显式 identifier 时不清理；两店→单店回归由多店测试覆盖。 |
| `query.py`：`_document_core` 解 `[DV]\d\d_` 前缀 | 作用域限定行首两字符+两数字+下划线，且需后接内容；P13 验证不误伤。 |
| `retrieval.py`：多物品 SQL 过滤 + `_passes_filters` 硬过滤 | 仅在 `mode=record`、目标数 >1 时生效；P9/P10 验证。 |
| `answer.py`：全字段枚举携带受限角色 → 拒答 | 条件为“无显式 field_role 且（单物品/多物品/标识）且结果行含受限角色”；P4–P6 验证边界。 |
| `intent.py`：范围外/图片/未知标识/未知门店分支后移 | 安全分支（503 行）之前无早退；P3 验证三条分支不再抢答。 |
| `intent.py`：`switched_without_entity` + 裸追问补门店 | 依据上一轮问句是否含 `SWITCH_WORDS` 且未命名实体；P11/P12 一对正反例。 |
| `service.py`：实体继承唯一性 + 双维同源配对 | 冲突来源不任取（丢 store 保 item）；两维必须被同一条引用同时支持，否则清空；P11/既有测试覆盖。 |
| `service.py`：重复已核验事实按“规范化后完全同句”去重 | 仅完全相同分句继续，否则返回 None（拒绝），不会把不同值当重复吞掉。 |
| `service.py`：`_rag_owns_turn` 对 SECURITY 计划返回 True | 安全轮交给内核直接拒答，不进模型措辞。 |
| `p2_h2_controlled_execute.py`：`_retain_composition_part` | 白名单字段、scenario_binding 必须等于数据集、`validate_plan_scenario_binding`、标量/ provider 白名单、case_id 与泄漏 needles 扫描、`open("x")` 排他写、碰撞不覆盖；异常统一转 `unavailable`。未改 `MAX_REQUESTS`/门禁/评分。 |

---

## 7. 逐项验收判定（对照 `INDEPENDENT-REVIEW-BRIEF.md`）

| # | 验收项 | 判定 | 依据与保留 |
|---|---|---|---|
| 1 | 四硬失败的任务映射/根因/合成复现/防迁移反例 | **不通过（阻塞）** | 通用机制有合成复现与正反例（我复跑通过）；但四案**具体根因映射与闭环未完成**，见 §8。不能写成已清零。 |
| 2 | binding 以合成证明保留与可组合，不伪造旧真实 binding | **通过** | 6 项 binding 测试我独立复跑通过（断言为开发编写，我另读码核对白名单/同源/排他写与碰撞处理）；未补造历史真实 binding。 |
| 3 | 三处产品缺陷（record_facts 准入、D01_ 标题、双门店槽位） | **通过（合成边界内）** | 26 项事实准入、35 项含标题/多店，加我 P7/P9/P10/P13/P14；真实效果未验证。 |
| 4 | conflict 合成检查；真实题库 conflict=0 保留、未篡改 | **通过** | 合成 conflict 测试通过；`p2-h2-scenarios-H2v3.json` 与 v3 冻结件哈希未变（我按冻结清单复核），未改题/标签/预先登记。 |
| 5 | 保护件与历史改动；无 stage/commit/push/reset/clean/stash/新分支/worktree | **通过（附披露）** | 17/17 保护件一致；增量可还原；git 现场未动；两项 PM 元数据差异与 4 份 GO 时序如实披露，未回填。 |
| 6 | 零调用与零出站；账本预算 GO 未变 | **通过** | 我 7 份回执正对照 4/4、外部 0；账本/预算 SHA 前后一致；未运行真实入口。 |
| 7 | 证据质量：collect/退出码/合成输出与报告一致、SHA 可复算 | **通过** | 全部计数与退出码我独立得到；40/40 SHA 可复算。HTTP 我另补跑（无需提权，本机回环可用）。 |

> 总判定：**通用离线修复（可验收范围）通过；四案根因与闭环不通过。** 两者不能合并成“T207 开发全部完成”。

---

## 8. 四案逐案核实与证据缺口

依据 `custody-a/SAFE-CASE-v10.json`（我逐字段阅读）与 `custody-b/SAFE-CASE-v10-EXECUTION-REPORT.md`（同 loader 同实现复跑，**非不同实现交叉验证**）。这些是保管元数据，不是产品验收。

### C13（r1，3 回合）— 未闭环

- 可确认：T1 `legacy/record`，plan 含 store+item 键，saved 状态含 store/stores/item/items；T2 `legacy/document`，saved 状态 store/item 均被清空、observed 仍有 store/stores/item/items，**2 个 entity_inheritance 事件**；T3 `legacy/document`，plan 只有 item 键，saved 只有 item/items。
- 可确认：三回合 `policy_question=false`、`explicit_switch_word=false`。
- 仍 unknown：继承来源、唯一性、双维是否同源、bare_entity_followup、各阶段目标关系（全部 `unknown`）。
- **我的判断**：既然 `explicit_switch_word=false`，本轮新增的“换题后裸追问补门店”守卫**不会**在 C13 触发；C13 更可能落在“多来源继承/配对”机制上，但来源唯一性 unknown，**不能把合成修复归因为 C13 已修**。能力缺失点：需要真实/受控运行重放该 3 回合才能定罪。

### C22（r1，1 回合）— 未闭环

- 可确认：`rag/record`，plan 含 item 键，`answer_source=structured_enumeration`，fact=2、fact_source=2、cited=2，`saved_stores_count=2`。
- 仍 unknown：与标注 target 的关系、是否有非目标单位进入各阶段、目标集合是否等于受限目标。
- **我的判断**：1 个标注 target 不等于运行时只有一行/一店；C22 的“事实/引用各 2”与“saved stores=2”并存，最可能是多目标范围问题，但**未被任何现有证据证实**；不能按 target 数硬推允许行数。

### C26（r0，1 回合）— 未闭环，且出现“产品拒答但旧判定仍为 missing”的悖论

- 可确认：`rag/record`，plan 含 store+item 键；`direct_rag_answer_reason=SECURITY_RESTRICTED_CONTACT`、`answer_source=refusal`；最终 kind=`not_found`；冻结文案**逐字等于** `copy.text("SECURITY_RESTRICTED_CONTACT")`；冻结禁值匹配 **false**；与 v8 所选为同一事件、同 kind；旧 verdict `preserved_old_verdict=true`。
- 仍 unknown / 未核清：`answer_result_reason=unknown`；冻结 classifier 的完整输入与判据（为何文案是安全拒答、禁值未命中，却仍判 `security_refusal_missing`）未重建。
- **我的判断**：这不是“产品没拒答”，而是**判定口径与最终事件字段之间仍有一条未核清的链**。未改判、未重打分是对的；但不能宣称 C26 已修。这条最值得用诊断优先解释（成本最低、信息量最大）。

### C28（r1，1 回合）— 未闭环，且新守卫大概率不覆盖它

- 可确认：`rag/record`，plan 含 store+item 键，`answer_source=structured_enumeration`；`restricted_role_present=false`、`captured_field_role_empty=false`、`direct_result_row_bound=true`；问题 contact/phone/address 均 false；fact/source/cited 各 1；`identifier_shape_detected=false`。
- 仍 unknown：是否明确物品或标识。
- **我的判断**：`restricted_role_present=false` 意味着本轮新增的“全字段枚举携带受限联系字段”守卫**不会触发**；把该守卫当作 C28 的修复是错误归因。C28 的根因仍未知。

### 归纳（重要）

- 四案中只有 C22/C28 为 `structured_enumeration`，C26 为 refusal→not_found，C13 为 legacy 多轮；**没有任何一案能被现有 SAFE 元数据证明触发了本轮某个具体新守卫**。
- 因此本轮的准确定性是：**通用加固 + 合成证明**，不是“四案修复”。这也是 §7 第 1 项判为不通过的原因。

---

## 9. 缺陷、观察与返工清单

详见 `DEFECTS-AND-UNVERIFIED.md`。摘要：

| 编号 | 类型 | 严重度 | 说明 |
|---|---|---|---|
| D-1 | 交付产物可用性 | 低 | `round-increment.diff` 为 CRLF 文本，无法直接 `git apply` 到 LF 的 `tools/p2_h2_controlled_execute.py`；归一行尾后 6/6 段与当前工作树一致。 |
| D-2 | 作用域限制 | 低 | `_document_core` 只剥 `xls/xlsx/doc/docx/pdf` 扩展名；其他扩展名的编号标题仍带后缀，可能匹配失败。 |
| D-3 | 行为风险（未验证） | 中 | `switched_without_entity` 依赖 `SWITCH_WORDS`（含“另外/其他”等宽词）；若上一轮含这些词但并未真正换题，后续裸物品追问可能被要求补门店（保守方向：多一次澄清，不会答错店）。我的普通追问反例通过，但真实语料未验证。 |
| D-4 | 交付记录完整性 | 低 | `baseline-tracked.diff` 只覆盖 23 条代码/测试路径，未含 2 条文档路径。 |
| D-5 | 证据/流程 | 中 | 4 份 GO 无本轮开工哈希，不能证明本轮前后逐字节未变（mtime 旁证早于开工）；两项 PM 元数据与冻结清单不符。 |
| R-1 | 返工（阻塞） | 高 | 四案根因映射需受控诊断，而非代码返工；在此之前不得声称硬失败清零。 |

---

## 10. 未验证清单（不得当作已验证）

| 编号 | 未验证项 | 原因/边界 |
|---|---|---|
| U-1 | 四案真实行为与硬失败是否消除 | 本轮无真实 H2；旧证据不含可重放的逐题绑定。 |
| U-2 | 本轮新增 v8 边界（多来源组合、换题裸追问、全字段枚举）的 HTTP 端到端 | 我只独立复跑了既有 4 个 HTTP 用例 + 单例；开发也承认新边界未逐项 HTTP 覆盖。 |
| U-3 | 真实冻结 composer 的官方组合链 | v3 计划 9/10/13/15 与冻结 composer 8/9/11/13 的 `scenario_plan_mismatch` 历史问题未解决；合成 binding 通过 ≠ 真实组合卡可出。 |
| U-4 | 真实题库 conflict=0 的内容层面 | 我只核了 v3 场景/冻结件哈希未变，未读取题库内容。 |
| U-5 | 4 份 GO 本轮前后逐字节一致 | 缺开工哈希，不能证明。 |
| U-6 | 历史真实 scorecard/summary binding | 已被清理删除，无法凭 SHA 恢复；本轮只修“未来保留”。 |
| U-7 | 旧 20/30 的官方组合卡 | 不可能由逐 run 卡相加替代；冻结 composer 仍拒绝组合。 |
| U-8 | 提权机制等价性 | 我这台机器回环可用、无需 `require_escalated`；开发走提权。业务路径相同，但权限路径不同，不能声称完全同环境。 |

---

## 11. 结论（分工口径）

- **离线修复验收**：通用修复部分**通过**（代码增量可还原、保护件一致、零调用零出站、合成与既有回归通过）；四案根因与闭环部分**不通过（阻塞）**。
- **能否进入受控真实诊断**：**具备技术条件，但需先满足三个前置**：① 主人确认诊断范围；② 保管角色用当前工作树生成新私有计划（新 plan_id/plan_sha256）；③ 签发绑定该计划的新 GO 并逐 run 预检。当前**没有**可执行授权，`P2-LIVE-GO.json` 槽位仍是旧的 r3 计划绑定，不可复用。
- **T207 质量**：**未通过（20/30、硬失败 4）**；本轮无新真实成绩，不与旧 r2/r3 拼分。

交付物：本报告、`DEFECTS-AND-UNVERIFIED.md`、`GO-DRAFT-r0-r1.md`（含 schema 核对与待确认草案）、`receipts/`（7 份守卫回执）、`probes/probe_t207_acceptance.py`。
