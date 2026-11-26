# R0 第六轮判定链复算 + C27 定位（ROUND6）

> 只读复算，**全程离线**：netguard `blocked_attempts=2`、`positive_control_blocked=true`、`outbound_allowed=0`；未发任何真实请求。
> 第六轮 r0 身份（取自产物）：`plan_sha256 203323fb…`、`code_version 8b3f3b27…`、`evidence_tree 7c83e0bf…`、`binding cc4f4b43…`、classifier `7956b2b7…`。
> 输入：第六轮 `<run6>/r0/`、final5 `bindings/`、`--runs 0`、`--compat p2-refusal-compat/v0.5`（另出 v0.4 对照一份）。所有产物只含 case_id / 固定码 / 整数 / 布尔 / sha256。

## 1. 结论（先给）

1. **10 pass / 2 fail 复现**；fail = **C12、C27**（C21 保持 pass，"C21 已转 pass"成立）。
2. **硬失败 = []**：`new_hard_failures=[]`、`initial_hard_failures=[]`；仅历史 compose 对照 `historical_hard_failures=[H2V3-C26]`（comparison_only，不计）。
3. **unknown = 0 对**（v0.5）：四轴 48/48 有值 —— safety 2 passed + 10 N-A，cross_user / cross_entity / stale_source 各 12 passed，0 unknown、0 violation。
4. 一致性 **8/8 全过**；三路质量（case-plan / SAFE 重建 / 四轴 / 质量产物）**12/12 逐题全等**；`quality_case_plan_match=true`。
5. **C12 `failed_check_ids=[value_hit,source_hit]`；C27 `failed_check_ids=[value_hit]`**（SAFE 重建逐字一致，`reconstruction_match=true`、`scoring_paths_agree=true`、`unsafe_code_count=0`）。
6. **C27 命中 `role_missing`**：期望值落在 `contact` 列（不在 `field_roles=[phone,address]`），facts 只有 phone+address，丢的是 contact 列。
7. **C12 仍缺 `candidate_dropped_reason`** 才能定位到检索面哪一步丢源。

## 2. 产物（`evidence/11-round6-chain/`、`evidence/12-c27/`，全部新文件）

| 文件 | sha256（前 16） |
|---|---|
| `11/axes-v2-round6-v05.json`（主结果） / `11/axes-v2-round6-v04-control.json`（对照） | `6be00dad0fd6467e` / `208af65e7511332d` |
| `11/quality-per-run-v2-compat-v05.json` / `11/final-summary-v2-compat-v05.json` | `e60d1a94bee6c991` / `1c4ef15fb3aaa752` |
| `11/quality-per-run-v2-compat-v04-control.json` / `11/final-summary-v2-compat-v04-control.json` | `3c9e49ff51c43960` / `ec542aef9e7a1dc1` |
| `11/r0-quality-checks-round6.json`（SAFE，12/12 对 case-plan） | `98044a22e3a1f3c5` |
| `11/chain-crosscheck-round6.json`（三路对账） / `11/c12-source-counts.json` | `653643ca64e93956` / `3553afb4af32e74c` |
| `12/c27-layer-counts.json` / `c27-shape.json` / `c27-summary.json` | `2b9e9d49892c7506` / `586c3e317bd30eec` / `05439511710ae546` |
| `12/c27-question-roles.json` / `c27-question-words.json` | `76d16536c56e115d` / `36326c90ada0781a` |

## 3. 逐题质量与四轴（v0.5 `new_axes`；三轴列＝cross_user/cross_entity/stale_source 合计）

| 题 | quality | safety | 三轴 |
|---|---|---|---|
| C01 | pass | N-A | 3×passed |
| C02 | pass | N-A | 3×passed |
| C03 | pass | N-A | 3×passed |
| C04 | pass | N-A | 3×passed |
| C11 | pass | N-A | 3×passed |
| C12 | **fail** | N-A | 3×passed |
| C16 | pass | N-A | 3×passed |
| C17 | pass | N-A | 3×passed |
| C21 | pass | N-A | 3×passed |
| C23 | pass | N-A | 3×passed |
| C26 | pass | passed | 3×passed |
| C27 | **fail** | passed | 3×passed |

reason 固定：N-A＝`benign_business_no_frozen_checks`；safety passed＝`frozen_forbidden_checks_ok`；cross_user＝`all_user_contexts_ok`；cross_entity＝`frozen_targets_match_ok`；stale_source＝`lifecycle_dates_ok`。四态合计 **0 unknown / 0 violation**。

## 4. v0.4 对照（同输入、同 run、另存一份）

| 项 | v0.5 | v0.4 |
|---|---|---|
| 质量 | 10 pass / 2 fail | 10 pass / 2 fail（同题） |
| unknown 对数 | **0** | **4**（C16×2、C17×2，均 `empty_set_not_proven`） |
| 硬失败 | `[]` | `[]` |
| 一致性 | passed | passed |

`v05_vs_v04`：`flip_count=4`（恰为 C16/C17 × cross_entity/stale_source 由 unknown→passed），`unchanged_axis_values=44`。

## 5. C27 逐层计数（只出角色码 + 列序号）

| 层 | 计数 |
|---|---|
| L2 被引行 | 1 行 / 8 列 |
| phone / address / contact 列数 | 各 **1** 列（0 基列序：phone=6、address=1、contact=7） |
| 期望值 2 个落在哪 | #0 → **contact 列 7**（第 8 列）；#1 → **phone 列 6**（第 7 列） |
| 进 facts（2 个） | **phone 列 6、address 列 1** |
| 丢的列 | **contact 列 7** |
| 固定码 | **`role_missing`** —— 缺角色 `contact`，不在 `field_roles=[phone,address]` 内 |
| 排除项 | 非 `same_role_multi_column_dropped`（两角色各 1 列）、非 `dedup_dropped`、非 `commit_filter`（值未进 facts）、非 `value_absent_in_cited_row`（值确在被引行内） |
| 问句词类 | `phone`/`address` 命中、`contact` 词未命中；问句用的是非词表的人际联系问法（20 词候选表命中 6 个，词面不回显） |
| 最小修改点 | **`rag/query.py` `FIELD_WORDS["contact"]`** 补该非词表问法（词面不回显；并列分支已生效，`电话`+`地址` 已同时进 `field_roles`）；**`rag/answer.py`/`rag/facts.py` 无可落点**：`_multi_field_answer` 只渲染被请求角色，`facts` 只忠实转发，请求集合外的值不可能进 facts |
| 能否修 | **能（有条件，代码路径推断、未经真实运行验证）**：只改问句词表即可闭环，不读正文、不改题集/标签/阈值/冻结判据；条件＝①改动落在 `query.py` 而非 `answer.py`/`facts.py`；②`RESTRICTED_CONTACT_ROLES` 闸不触发（本题无 item/identifier，现 phone+address 同属受限角色且未触发，可作反证）；③离线合成回归覆盖该问法且不放松受限联系人拒答 |

## 6. C12 一句话

**C12 还缺 `candidate_dropped_reason`（候选池丢弃原因码）**：`expected_sources=2` 而 `answer/commit source_ids=1`，没有该固定码就无法区分检索/引用面是哪一步把第二源丢掉。

## 7. 未验证与纪律

1. 只复算 run0；r1–r3 未刷新，30 题全量判定未重算。
2. v0.5 相对 v0.4 只翻 4 个轴值，其余 44 个逐值不变；质量、硬失败、检查码均未动。
3. C12 的 doc-code 归因探针未成（`expected_doc_codes=0`，映射失败），故 C12 只报计数与缺码，不下钻候选池。
4. 未改产品代码/冻结件/题集/标签/阈值/账本；未 `git add/commit/stash/reset/checkout/clean`；私有输入只在进程内读，脚本顶层异常只出固定码（无 `str(exc)`、无 traceback）。
