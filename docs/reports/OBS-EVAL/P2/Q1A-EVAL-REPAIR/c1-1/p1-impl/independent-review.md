# C1-P1-IMPL 全新独立验收报告（stale_source v1 分类器 + P4 IR-01/02/03 修复）

- 角色：C1-P1 **全新独立验收**（非开发、非经理、非保管）；主人。
- 日期：2026-11-14；分支 `codex/p2-e2e`；HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；暂存区 **0**；本轮新增 commit **0**。
- 被验收对象：
  - `backend/src/mktkb/evaluation/p2_stale_version_state.py` — SHA-256 `fed191446ed261873acd81d6b0fea0adcfd317aff4cc41bf8b60e0cb61fdcf59`
  - `backend/tests/evaluation/test_p2_stale_version_state.py` — `1e81e7ac267c263aa94a47a9ffef0d842154e4f8bb5e7a461862f9a224523eff`
  - `backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py`（含 IR-01/02/03 修复）— `8e0263d928cf2a63cacdceeef41e1b9ef94f43e8af0468af1a514f57541bbd2d`
  - `backend/tests/evaluation/test_p2_evidence_axes_adapter_v2.py` — `bac8334dd9770b0ed53159a401a6c85e977d9de4ff78542da6038403f22e81b5`
- 冻结判据：`docs/evaluation/p2-stale-source-criterion-v1.md` — `c34d08af3bc27f0f6d69bad200ce77c6db229622a204d5df1ebf7b010eaae9c7`（逐字节未变）。
- 独立方法：自建 `K*/S_syn_k` 合成语料（`synth_stale.py`）；自建 8 支探针（AST、运行时 8,792+392 次敌意变异、IR-02/03 排列、178 条判据一致性断言、26 条边界规则、98 项测试质量、保全、零调用）；**不 import 开发测试模块取断言，不采信开发自报数字**。全部数字由 `independent/out/*.json` 重算。
- 未读真实 H2 题面/标签/答案/目标值/私有密文/key/`.env`/保管会话/runbook；零真实产品/模型/检索/裁判调用。

## 0. 结论

> **`PASS_WITH_DISAGREEMENTS`**

- **IR-01 功能性修复成立**：11 个原始站点全部落固定码；**0 个现行 `TypeError` 漏网**（8,792 次合同/快照变异 + 392 次分类器变异，0 次逃逸）；旧逻辑负对照在两侧都必抛 `TypeError`。AST 另找出 **6 个未走 `_enum_member` 的直接成员判断**（`_load_record` 3 个、`load_snapshot_v03` 3 个）；它们当前的容器是 **tuple**，list/dict 只会返回 False 并落固定码，故不是现行漏网，但属于**潜伏脆弱点**（若容器改为 frozenset 即回退为 IR-01）。
- **IR-02 成立**：同键 2/3 目标全排列、跨键目标全排列、3 次重复，结论恒为 `passed/cross_entity_targets_match_ok`。
- **IR-03 成立**：键 B/filters A → `unknown/entity_key_space_incompatible`；一致异实体 B/B → `violation/other_entity_used`；匹配行 + 矛盾行 → `unknown`，不判 pass；记录顺序无关。
- **判据符合性（核心）成立**：178/178 条独立断言通过；两模式单入口、21 码（9 新 + 12 沿用）与冻结表一致、14 个保留码不产出、§7 十四行逐行对齐（row11 半端 → `version_only`）、F-1..F-12 逐条、四路歧义全 `unknown` 且不 `violation`、折叠 `violation>unknown>N/A>passed`、`N/A` 恒 0、`basis` 不进 verdict、输出无 `verified/threshold/release`、计数三式全成立。
- **仍保留 4 条发现 + 2 条限制**（§5）：medium = ①非空使用集 + `turn_status=partial` 可 **passed**（R-J-3 严格读法下应 unknown）；②fixture/source-map SHA 只是**声明绑定**，不是内容摘要（§3.2 规则 3）。low = ③未知 reason 随 unit 顺序变化，未按 R-J-10 规则序取首条；④`case_id` 含 `release/verified/threshold` 时 `CriterionError` 逃出入口。
- **测试质量总体好但非全钉死**：98 项 **98 passed / 0 failed / 0 skipped**，0 skip/xfail、0 monkeypatch 被测模块、0 恒真；但存在 1 处 `in stale.DETERMINATION_CODES` 弱断言（§12.1 明确禁止）、14 个保留码只做集合 disjoint 而非逐码、敌意输入测试不钉固定码。
- **保全**：既有基线 **0 改动 / 0 缺失**（2,247 个非敏感 untracked 逐字节一致 + 69 个敏感名仅比大小）；15 tracked / C 冻结 12 / Q1a-1 38 全一致；判据与 P4 独立评审逐字节未变；暂存 0、HEAD/分支/172 commit 不变。**但**本轮有 **21 个**（最终捕获时点下界；并发目录仍在增长）`rescore/evidence-r3/` 等文件由并发他人在我开工后新建（非我产物；未修改、未将其内容用于判定），因此“整棵树逐字节不变”不成立；“既有 untracked 不变”成立。
- **零调用**：7 层正对照（socket.connect/connect_ex/create_connection/getaddrinfo/gethostbyname、http.client、httpx）全拦并记账；负对照不清账必报错；判定工作量 `external=0`；两个目标模块无网络 import。

> **特别一行：是否可用于在旧证据上重算 stale**
>
> **不可直接用于旧证据重算；可作为重算的判定核心，但必须先新增 §8.1 投影/接线。**
>
> 理由：仓库内**没有任何生产消费者 import `p2_stale_version_state`**（只有开发测试）；P4 适配器仍走旧口径 `stale_lifecycle_evidence_missing`（`p2_evidence_axes_adapter_v2.py:2069`，v1 §10.3 已退役、§12.4 要求新分析身份，不得就地改）。把 P4 合同 v2 当 grounding、P4 快照 v0.3 当 evidence 直接调用，会分别落 `stale_grounding_mode_invalid` / `evidence_incomplete`（`out/04b-gaps.json` 的 `old_shape.*`）。可用条件见 §9。

## 1. IR-01：非标量枚举的 fail-open 是否真修好

### 1.1 AST 独立扫描（`out/01-ir01-ast.json`）

- 适配器：58 个 `in/not in` 成员判断；启发式候选 14 个，逐一人工/运行时复核后 **6 个为“直接成员判断、未过 `_enum_member`”**：
  - `_load_record`：`locator_kind in LOCATOR_KINDS`（`:848`）、`code in RECORD_IDENTITY_CODES`（`:868`）、`entity_code in ENTITY_CODES`（`:870`）。
  - `load_snapshot_v03`：`fixture_kind in FIXTURE_KINDS`（`:1171`）、`source["fixture_kind"] in FIXTURE_KINDS`（`:1184`）、`binding_fixture in FIXTURE_KINDS`（`:1194`）。
  - 其余候选均为字符串派生值（`head = str(code).split`、`item.split(...)`、`separator`、已校验的 `scenario_id` 等）或 `type(value)`，不构成输入面。
- 分类器：27 个成员判断；4 个候选均为已校验的 `turn_index`/`unit_id`/字符串 `base`/字面量，**0 个输入面漏网**。
- 关键事实：上述 6 个适配器站点使用的是 **tuple** 容器（`LOCATOR_KINDS`、`RECORD_IDENTITY_CODES`、`ENTITY_CODES`、`FIXTURE_KINDS`），`list in tuple` 不哈希、不抛异常，只返回 False → 固定码。故**现行没有 TypeError 漏网，但修复未统一到 guard 层**。

### 1.2 运行时 oracle（`out/02-ir01-runtime.json`）

| 侧 | 变异次数 | `TypeError` | 其他逃逸 |
|---|---:|---:|---:|
| 适配器 v2（合同 + 快照，7 种值：list/dict/set/None/bool/int/嵌套） | **8,792** | **0** | 0 |
| `p2_stale_version_state`（grounding + evidence） | **392** | **0** | 0 |

- 适配器 11 个原始站点逐站点矩阵（`out/02-ir01-runtime.json#adapter_site_matrix`）全部命中期望固定码：
  contract `criterion/reason` → `contract_axis_invalid`；`basis` → `contract_basis_invalid`；temporal 4 字段 → `snapshot_enum_invalid`；`document_versions[i].code` → `snapshot_enum_invalid:<path>`；empty-use `code/turn_status` → `snapshot_enum_invalid`；`source_evidence.completeness_status` → `snapshot_enum_invalid`。
- 6 个 AST 候选也逐站点实测：record `locator_kind/code/entity_code` 与 3 个 `fixture_kind` 都落 `snapshot_enum_invalid[:path]` / `snapshot_fixture_kind_invalid`，无异常。
- **负对照（证明探针有效）**：
  - 适配器：把 `_enum_member` 临时换回旧逻辑 `value in allowed`，`criterion=["x"]` → **`TypeError: unhashable type: 'list'`**；直接 `["x"] in frozenset({"a"})` 同样 `TypeError`。
  - 分类器：把 `_enum_member` 换回旧逻辑，`annotation.reason=["x"]`（`ANNOTATION_REASONS` 是 frozenset）→ **`TypeError`**。
- 结论：**IR-01 的“所有字段路径不抛 TypeError”在当前字节上成立**；6 个 tuple 站点是“潜伏未 guard”，不是现行 fail-open。建议统一改为 `_enum_member` 并把它们加入开发测试，避免容器类型变化后回退。

## 2. IR-02 / IR-03

### 2.1 IR-02 同键目标顺序无关（`out/03-ir02-ir03.json`）

- 2 目标 `[严, 松]` / `[松, 严]` 全排列：**均 passed / `cross_entity_targets_match_ok`**。
- 3 目标（严 + 两个松）**6 种排列**：均 passed。
- 跨键目标（目标 B + 目标 A，运行期 A）**2 种排列**：均 passed。
- 决定性形状重复 3 次：结论逐次相同。
- 代码依据：`_match_entity_row` 的 `same_key` 循环不再提前返回，`_filters_subset` 任一满足即 matched（`:1532-1538`）；跨键的 canonical 循环也只看集合成员，不依赖顺序（`:1545-1557`）。

### 2.2 IR-03 自洽闸门

| 运行期行 | 结论 | 判断 |
|---|---|---|
| 键 A / filters A（同实体） | `passed` | 正确 |
| 键 B / filters B（一致异实体） | **`violation/other_entity_used`** | **未误伤** |
| 键 B / filters A（矛盾） | `unknown/entity_key_space_incompatible` | **未假 pass** |
| 键 A / filters B（矛盾） | `unknown/identity_unresolved` | 未假 pass |
| `item\|id:999` / filters A | `passed` | 允许的 id 型键（P4 IR-03 建议显式允许），残余见 §5 |
| `store\|storeb` / filters A | `unknown/entity_key_space_incompatible` | 未假 pass |
| 同实体匹配行 + 矛盾行（两种记录顺序） | **`unknown/entity_key_space_incompatible`** | 一条坏行不能把整轴洗成 pass；顺序无关 |

结论：**IR-03 的自洽闸门“不漏（矛盾不 pass）、不误伤（一致异实体仍 violation）”在合成矩阵上成立**；`id` 型键因不可复算而放行，沿用 P4 建议的允许集合。

## 3. 判据符合性（对 `c34d08af…` 逐条）

主探针 `out/04-criterion.json`：**178 条断言，0 失败**。以下均为等值断言，非“属于集合”弱断言。

### 3.1 两模式与 21 码

- 单入口 `determine_stale_case(criterion_version, grounding, evidence)`；同一 case 在 `version_state` → `passed/stale_active_version_used/version_only`，在 `date_window` → `passed/stale_source_dates_ok/version_plus_date`；`provenance.grounding_mode` 分别为两模式。
- 21 码精确等于：新增 9（active/empty/superseded/out_of_window/ambiguous/scenario/usage/window/mode）+ 沿用 12；`PASS=3`、`VIOLATION=4`、`UNKNOWN=14`，三者不交叠且并集为 21。
- `STATE_BY_CODE` 对 21 码逐码映射；14 个保留码集合精确；`no_dated_sources_lifecycle_checked` 在 21 码之外。
- 21 码在独立合成批次中**逐个可达**；14 个保留码**一个不产出**。

### 3.2 §7 十四行表

独立映射到 `K*/S_syn_k`（不照抄开发 `V*/D*/S_syn` 用例），逐行结果：

| 行 | 期望（state/reason/grade） | 实测 |
|---:|---|---|
| 1 `[K21]` version | passed/active/version_only | 同 |
| 2 `[K20]` | violation/superseded/none | 同 |
| 3 `[K10]` UNDECLARED 非 active | violation/superseded/none | 同 |
| 4 `[K11]` | passed/active/version_only | 同 |
| 5 `[K30]` 0 active | unknown/ambiguous/none | 同 |
| 6 `[]` 闭包已证 | passed/empty_proven/version_only | 同 |
| 7 `[]` 闭包未证 | unknown/empty_set_not_proven/none | 同 |
| 8 未观测 | unknown/usage_set_missing/none | 同 |
| 9 窗口覆盖 | passed/active/**version_plus_date** | 同 |
| 10 窗口不覆盖 | violation/out_of_window/none | 同 |
| 11 **半端（未列 open_ended）** | **passed/active/version_only**（窗口忽略） | **同** |
| 12 date_window 窗口缺失 | unknown/window_unresolved/none | 同 |
| 13 date_window 不覆盖 | violation/out_of_window/none | 同 |
| 14 t1 pass + t2 用 K20 | violation/superseded；t1 保留 | 同；`per_turn` 两条，audit 含 `turn[0]:passed:stale_active_version_used` |

### 3.3 F-1..F-12

| # | 独立反例 | 实测 | 结论 |
|---:|---|---|---|
| F-1 | UNDECLARED 非 active（K10） | violation/superseded；非 `version_unresolved` | 成立 |
| F-2 | `source_indices` 重复 `[0,0,1,2,5]` | unknown/ambiguous，非 violation | 成立（与 R-AV-1 的码张力见 T1） |
| F-3 | 0 active（K30） | unknown/ambiguous，audit `stale_usage_source_not_in_scenario` | 成立 |
| F-4 | date_window 全部窗口排除 as_of | violation/out_of_window，非 N/A | 成立 |
| F-5 | 缺 mode / list / 未知 / dict / 双声明 / 版本不符 | unknown/mode_invalid | 成立 |
| F-6 | scenario 缺 / 无 indices / 非数组 / 越界 / 负 / bool | unknown/scenario_undeclared | 成立（“不在数据集契约”见 T3） |
| F-7 | observed=false / 无 units / units 非 list / 无 usage | unknown/usage_set_missing | 成立 |
| F-8 | 缺层 / 层未观测 / 检索截断 / 非零候选 / 伪造闭包布尔 | unknown/empty_set_not_proven | 成立（与 R-J-3 的张力见 T2） |
| F-9 | K10 声明号 5 > active K21 的 3 | unknown/ambiguous，audit order_conflict | 成立 |
| F-10 | built_at=窗口端点 / 全同值 / basis 非 owner/custodian / evidence_ref 空 / open_ended 冲突 | version_state：丢弃 + `stale_date_fixture_rejected`，verdict 不变；date_window：unknown/window_unresolved | 成立（内容摘要限制见 L1/L2） |
| F-11 | applicability=not_applicable / criterion 不符 | unknown/annotation_unknown，绝不 N/A | 成立 |
| F-12 | t1 unknown + t2 violation（及反向） | violation/superseded；unknown 留在 per_turn + audit | 成立 |

### 3.4 四路歧义、折叠、N/A、basis、输出、计数

- **四路歧义全 unknown、无 violation**：重复索引（多 active）、0 active、号序冲突、窗口 active 与位置 active 不一致；另测 date_window 多成员同时覆盖 → unknown/ambiguous。audit 分别出现 `stale_duplicate_source_indices`、`stale_usage_source_not_in_scenario`、`stale_version_order_conflict`、`stale_grounding_crosscheck_disagreement`。
- **折叠**：`STATE_PRIORITY` 精确 `{violation:3, unknown:2, not_applicable:1, passed:0}`；dummy 回合验证 violation > unknown > N/A > passed，平局取最小 turn index；真实 `TurnDetermination` 构造 N/A 必抛 `CriterionError`（实际先命中 state/reason 不一致门），`aggregate_cases` 对伪造 N/A 抛 `not_applicable_unreachable`；21 码无一映射到 N/A。
- **N/A 恒 0**：静态扫描无 `state="not_applicable"` 赋值；动态所有批次 `counts.not_applicable == 0`。
- **basis 不进 verdict**：`owner_ruling` 与 `custodian_transcription` 的 state/reason/grade/audit 逐值相同。
- **输出**：键集恰 7（case_id/scenario_id/state/reason/evidence_grade/per_turn/provenance）；per_turn 键集 3；无 `verified/threshold/release/score/mean/weight` 字段或结论值；无 as_of 日期、unit_id、record_code 泄漏。
- **计数**：0..40 个的 41 个合成批次，`planned=passed+NA+unknown+violations`、`checked=passed+NA+violations`、`planned=checked+unknown`、`passed=version_only+version_plus_date`、`NA=0` 逐批成立；空批次全 0；`axes_provenance=rescored`。

## 4. 发现、分歧与限制（保留，不替经理表决）

| id | 级别 | 发现 | 实测/依据 | 影响 |
|---|---|---|---|---|
| **P1-IMPL-F3** | **medium** | **非空使用集 + `turn_status=partial` 被判 passed** | `usage={observed:true, units:[K21], turn_status:"partial"}` → `passed/stale_active_version_used/version_only`；`_determine_turn` 只在空集分支读 `turn_status`（`:841`、`:1014-1033`），非空分支只看 `observed`/`units`（`:996-1003`） | R-J-3 明列“回合 `partial`”→ `stale_usage_set_missing`；严格读法下这是**假通过**，会抬高旧证据重算的 pass。若经理把 R-J-3 作为硬门，本项应记 **FAIL** |
| **P1-IMPL-F1** | low | 未知 reason 随 unit 顺序变化（R-J-6 vs R-J-7） | `[NOPE, K30]` → `version_unresolved`；`[K30, NOPE]` → `stale_active_version_ambiguous`；`:1038-1063` 按 unit 顺序 append，`:1124-1125` 取 `unknowns[0]` | R-J-10 要求按 P-1..P-5、R-J-6、R-J-7 规则序取首条；状态仍 unknown，仅 reason/直方图受影响 |
| **P1-IMPL-F2** | low | 未知 reason 随 unit 顺序变化（P-5 vs R-J-7） | `[source_unresolved, NOPE]` → `source_unresolved`；反向 → `version_unresolved` | 同上；P-5 应恒优先 |
| **P1-IMPL-F4** | low | `case_id`/`scenario_id` 含结论词时抛 `CriterionError` | `case_id="release-1"` → `CriterionError: criterion_forbidden_output_token:release`；`_assert_no_forbidden_tokens` 在 `CaseDetermination.__post_init__`（`:1219`）扫描所有字符串，入口只捕 `_Reject`（`:1376`） | I-5 输出禁令以“异常”而非固定码实现；批量重算遇到此类输入会整轮中断 |
| **P1-IMPL-L1** | medium | `fixture_sha256` 是**形状/声明**，不是内容摘要 | `fixture_sha256="f"*64` + 默认 windows → `passed/stale_source_dates_ok`；`_load_windows` 只 `_is_sha256`（`:664-676`），不哈希 payload | §3.2 规则 3 的“SHA-256 绑定”在模块内无法成立；需调用方先验冻结 fixture 字节。与 P4 IR-05 同类 |
| **P1-IMPL-L2** | medium | `source_map_sha256`/`ingest_plan_sha256` 与 fixture 头比较的是**调用方声明**，不重算 payload | 把 K20 的 `version_number` 1→99、保留同一声明 hash → 仍 `passed`（`:692-695` 只比较 `grounding` 声明与 `bindings`） | 被篡改的 source map 可在声明 hash 不变时进入判定；切换旧证据前必须由投影层重算/校验 |
| **P1-IMPL-L3** | low（潜伏） | 6 个 tuple 成员判断未走 `_enum_member` | 见 §1.1；当前 0 TypeError | 若上游把容器改为 frozenset，IR-01 会回归；开发测试未覆盖这 6 点 |

### 4.1 判据内部张力（已按更 fail-closed 一侧实现，记录以便经理裁决）

| id | 张力 | 实现 |
|---|---|---|
| T1 | R-AV-1：`source_indices` 重复 → `stale_scenario_undeclared`；F-2：重复 → 多 active `stale_active_version_ambiguous` | 取 F-2；模块 docstring §1 明示；两者都 unknown |
| T2 | R-J-3：空集 + 回合 partial → `stale_usage_set_missing`；F-8：空集闭包不成立 → `empty_set_not_proven` | 取 F-8；模块 docstring §2 明示；两者都 unknown |
| T3 | P-4/F-6 的“`scenario_id` 不在 scenario 契约”需要数据集级 registry；§8.1 只传内联 scenario | 只能校验内联 scenario 的缺失/非法；外部 registry 成员性不在本模块输入面。接旧证据时由投影层承担 |

## 5. 测试质量（98 项）

- 独立执行（`out/05-pytest.txt`）：**98 collected / 98 passed / 0 failed / 0 skipped**；2 个文件各 49 项；0 `skip`/`xfail` marker；0 `pytest.skip/xfail`；0 monkeypatch 被测模块；0 `assert True/False` 恒真。
- 断言量：stale 172 条 assert（164 条 compare），adapter 147 条（143 条 compare）。
- 固定码钉扎：
  - stale：21 个码全部作为字面量出现；**17 个在 `==/!=` 等值断言中**，其余 4 个（`stale_source_dates_ok`、`turn_not_executed`、`turn_error`、`replay_without_original`）通过 `reasons == set(DETERMINATION_CODES)` 的集合等值间接覆盖；
  - adapter：43 个固定码字面量全部在等值比较中；15 个码族未被开发测试直接断言（与 P4 IR-10 同类，属覆盖残余）。
- **弱断言**：stale `:819` 有 `assert case.reason in stale.DETERMINATION_CODES`，与 §12.1“任何固定码都以等值比较断言，禁止 `in FIXED_CODES` 之类弱断言”直接冲突；建议改为逐码等值或删除（同文件已有 `reasons == set(...)` 强断言）。
- **保留码覆盖**：14 个保留码在开发测试中**没有逐码字面量断言**，只有 `produced.isdisjoint(stale.RETIRED_CODES)`；若 `RETIRED_CODES` 被误删一个码，测试仍会通过。§12.3 G-8 要求“逐个断言不产出”，属测试覆盖残余（本独立探针已逐码覆盖）。
- `test_hostile_non_scalar_inputs_never_raise` 只断言“返回 CaseDetermination + state 映射一致”，**不钉固定码**；它不能发现“错了但仍是合法码”的回归（本独立探针的 site matrix 才钉到固定码）。
- adapter 的 IR-01 测试覆盖 11 个原始站点（3 合同 + 8 快照），未覆盖 6 个 tuple 站点；当前不导致 TypeError，但属潜伏覆盖缺口。
- §12.2 禁用字面量：stale 测试文件 **0 命中**（D01..D06、V01..V07、2026-10-27/28、base_b0、pre_v05、post_v05）；adapter 测试文件使用合同既有 scenario ids（`base_b0` 等），那是 P4 合同适配测试的既有夹具，不是 v1 分类器测试，按 §12.2 的适用对象不计入本包违规。

## 6. 冻结与保全

| 项 | 结果 | 证据 |
|---|---|---|
| HEAD / 分支 | `97b0066726e5b8d6f94cbc0b63a890084550c106` / `codex/p2-e2e`，未变 | `00-snapshot-start/end.json` |
| 暂存区 | **0** | `07-preservation.json` |
| 本轮新增 commit | **0**；`rev-list --count` 172 → 172 | 同上 |
| 15 tracked modified | **15/15** 路径与 SHA 逐条一致 | `protected.tracked_modified_15` 0 mismatch |
| C 冻结 12 | **12/12** 逐字节一致 | `protected.c_freeze_12` 0 mismatch |
| Q1a-1 保护 38 | **38/38** 逐字节一致 | `protected.q1a1_protected` 0 mismatch |
| 判据文件 | `c34d08af…` 未变 | `targets` match |
| P4 独立评审 / aggregate | `7887279e…` / `c931d778…` 未变 | `targets` match |
| 被验收 4 文件 | `fed19144…` / `1e81e7ac…` / `8e0263d9…` / `bac8334d…` 未变 | `targets` match |
| 既有 untracked | **2,247** 个非敏感逐字节一致 + **69** 个敏感名仅比大小；**0 changed / 0 missing** | `07-preservation.json` |
| 本轮新增外部 untracked | **21** 个（最终捕获时点下界；`rescore/evidence-r3/` 与 `rescore-*-r3`，该目录仍在并发增长），**非本包产物**；仅看目录/时间戳确认归属，未将其内容用于判定，未修改 | `00-snapshot-end.json#untracked.added_outside_own` |
| 本包产物 | 全部在 `c1-1/p1-impl/` 前缀内 | `own_files` |

> 保全结论：**“既有 tracked/untracked 与冻结件不变”成立**；“整棵树在本轮逐字节不变”**不成立**，原因是并发他人在 `rescore/evidence-r3/` 等路径新建了文件（最终捕获时点 21 个，该目录仍在增长）。这些文件不属于本包，也不由本包证明其内容。

## 7. 零调用（正负对照）

`out/08-zero-call.json`：12 条检查，0 失败。

- 正对照 7 层全部拦截并记账：`socket.connect`、`socket.connect_ex`、`socket.create_connection`、`socket.getaddrinfo`、`socket.gethostbyname`、`http.client.HTTPConnection.connect`、`httpx.HTTPTransport.handle_request`。
- 负对照：手工制造一条账 → `assert_clean()` 必抛；清账后通过。
- 干净工作量（4 个 stale 判定 + 1 个 adapter 判定 + 聚合）→ `guard.events == []`，**external=0**。
- 静态：两个目标模块无 `requests/httpx/socket/urllib/openai/anthropic/aiohttp` import。
- 98 项测试自身带 `t09_network_guard` fixture，执行通过（`out/05-pytest.txt`），与本探针互为对照。

## 8. 用于旧证据重算的可行性（判据 §11/§12.4）

**结论：不可直接用于旧证据重算；可用作重算的判定核心，条件是新增投影/接线，并先处理 §5 的 F3/L1/L2/F1/F2。**

已实测的形状事实：

1. 生产代码 **0 个消费者** import `p2_stale_version_state`；只有 `test_p2_stale_version_state.py` 引用（`grep` 全仓）。
2. P4 适配器仍使用旧口径：`p2_evidence_axes_adapter_v2.py:2069` 无条件追加 `stale_lifecycle_evidence_missing`；该码在 v1 §10.3 已退役，v1 下 non-conformant。§12.4 明确：替换需**新分析身份 + 独立验收，不得就地改 P4 产物**。
3. 旧 P4 合同 v2 不是 §8.1 `grounding`（作为 grounding → `stale_grounding_mode_invalid`）；P4 快照 v0.3 不是 §8.1 `evidence`（作为 evidence → `evidence_incomplete`）。见 `out/04b-gaps.json#old_shape.*`。
4. 旧快照 v0.3 的 `record_identities` 可提供 record/doc 身份，但没有 §8.1 的 `usage.units[].code/record_code`、`annotation.reason`（18 码）与 `grounding.scenario/ingest_plan/source_map` 的一体化形状；投影层必须把合同 v2 + scenario 契约 + ingest plan + source map + 快照逐回合映射为 `determine_stale_case` 的输入。缺少映射时只会得到固定码 unknown（`stale_usage_set_missing` / `source_unresolved` / `stale_scenario_undeclared`），**不能产出 30 题 stale 计数**。

可用条件（缺一不可）：

- (a) **新分析身份 + 独立验收**，不得改写 P4 已验收产物；新消费者必须显式 import v1 模块并记录 criterion_version。
- (b) 投影层：`scenario`（source_indices/ingest_batches）、`ingest_plan.sources`、`source_map.sources`、`windows`/`fixture_sha256`/`stale_grounding.mode`、`annotation`（required + lifecycle_dates + 18 码之一）、`usage.units`（code + record_code）、`turns`（逐回合）全部按 §8.1 组装。
- (c) 外部先验：fixture 字节、source map/ingest plan 的 SHA-256 必须由投影层重算并与 `bindings` 比对（L1/L2），不能只信调用方声明。
- (d) 只喂**完整回合**；若旧证据含 `turn_status=partial` 且非空 units，先按 F3 修复或显式记 unknown，否则会假通过。
- (e) 对 T1/T2 的码选择、F1/F2 的 reason 序，先由经理/判据作者裁定，避免同一批重算出现两个 reason 直方图。

## 9. 边界声明

- 只读被验收文件、冻结判据、P4 独立评审与公开/合成契约；未改任何开发文件、冻结件、合同、旧卡、账本、GO；未 stage/commit/push；未新建 worktree/切分支。
- 未读真实 H2 题面/标签/答案/目标值/私有密文/key/`.env`/保管会话/runbook；未打开仓外私有路径。
- 只使用合成数据 + 仓库内公开契约文本 + P4 独立构建器作为**合同/快照夹具脚手架**（`p4/independent/synth.py`，只用于构造合法 payload；所有反例、期望与断言均为本包自建）。未 import 开发测试模块取断言。
- 新增文件仅 `c1-1/p1-impl/**`；`rescore/evidence-r3/*` 的新增文件为并发他人产物，本包未修改、未将其内容用于判定（仅确认目录/时间戳归属），也不为其内容背书。
- 仓外账本/预算/GO/30 题/标签/密文未触碰；只能声明“本会话未打开”，不能声明其字节未变（不在可读范围）。
- 冻结/保全中 69 个敏感名 untracked 仅比大小、未读内容；其“内容未变”不由本会话证明。

## 10. 证据索引（`c1-1/p1-impl/independent/`）

| 文件 | 内容 |
|---|---|
| `synth_stale.py` | 自建 K*/S_syn_k 合成语料 |
| `netguard.py` | 自建零出站守卫 |
| `snapshot_start.py` → `out/00-snapshot-start.json` | 开工基线（hash/git/untracked） |
| `probe_01_ir01_ast.py` → `out/01-ir01-ast.json` | AST 成员判断 58/27 站点 + 6 潜伏候选 |
| `probe_02_ir01_runtime.py` → `out/02-ir01-runtime.json` | 8,792 + 392 次变异、站点矩阵、负对照 |
| `probe_03_ir02_ir03.py` → `out/03-ir02-ir03.json` | 顺序排列 + 自洽矩阵 |
| `probe_04_criterion.py` → `out/04-criterion.json` | 178 条判据断言（§7/F-1..F-12/21 码/折叠/计数/输出） |
| `probe_04b_gaps.py` → `out/04b-gaps.json` | 26 条边界规则、4 发现、2 限制、3 张力、旧形状 |
| `probe_05_tests.py` → `out/05-test-quality.json`、`out/05-pytest.txt` | 98 项执行 + AST 测试质量 |
| `probe_07_preservation.py` → `out/07-preservation.json`、`out/00-snapshot-end.json` | 冻结/保全/并发新增 |
| `probe_08_zero_call.py` → `out/08-zero-call.json` | 7 层正对照 + 负对照 + external=0 |
| `README.md` | 运行方式与边界 |

## 11. 最终裁决

**`PASS_WITH_DISAGREEMENTS`**。

- 按“IR-01/02/03 + 核心判据（§7/F-1..F-12/21 码/四路歧义/折叠/N/A/计数/输出）”给 PASS。
- 保留的分歧：F3（partial turn 假通过，medium）、L1/L2（fixture/source-map 声明绑定，medium）、F1/F2（reason 序，low）、F4（输出 token 异常，low）、L3（6 个潜伏 tuple 站点，low）、测试弱断言/保留码逐码覆盖（low）。
- **若经理把“fail-closed 必须全量 / R-J-3 partial 必须 unknown”作为硬门，则本包在判据符合性单项应记 `FAIL`；若把“§3.2 SHA 必须内容绑定”作为硬门，则 L1/L2 为 `FAIL`。** 本报告不替经理表决，只把读法与证据写清。
- 不得据此声称：T207 通过、质量放行、release/threshold、C1-2 授权、30 题分数提升、旧证据已可重算。
