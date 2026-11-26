# R2-204 独立预验收：T-R2-202C「跨实体取数联结」9 hunk

- 执行者：`r2-204-independent`（**未参与**本次开发任何环节：未写 202A/202B/202C/202D 的源码、未写 203A/203B/203C 的用例、未参与材料包撰写）
- 时间：2026-11-17 18:43–19:05（首轮 A–G）+ 19:18–19:45（**增量复验 T-R2-202D**，见 §2.5）；仓库 `D:\GPT项目\市场部AI知识库`；HEAD `97b0066`（未做任何 git 写操作）
- Python：`..\.venv\Scripts\python.exe -X utf8`；cwd=`backend/`；basetemp=`D:\mktkb-p2-h2v3-r2-20261117\basetemp-204`（仓库外）
- 立场：**证伪**。下文每个 PASS 都是我本人跑出的命令 + 退出码 + 用例名/节点名；开发报告只作为"待证命题"。
- 只读范围遵守：`backend/src/**` 一行未改（§2C 有 3 文件 sha256 与 mtime 证据）；既有测试未改；`docs/evidence/**`、`fixtures/**`、`docs/evaluation/**`、账本/预算/GO 槽位未改（§2C）。
- 我只新增了两处：本目录（`evidence/08-independent/`）与 `backend/tests/integration/test_r2_204_independent_probes.py`。

---

## §0 结论

| 判据 | 结论 | 一句话依据（详见 §2） |
|---|---|---|
| **A** C29 根因红例是否**同形** | **PASS** | 自建同形件：修前（运行时关 `_store_join_chunks`）`kind=answer` / 值 1/2 / 来源 1/2 / 模型 0 调用，与 SAFE 重建的 C29 逐项同形；修后 2 值 2 来源（两份不同文档）；红态断言消息原文已留档 |
| **B** C25/C29 未知轴解释是否成立 | **PASS**（1 处表述瑕疵记入 §4-②） | `recompute-v2-run2.json` 两案 `cross_entity=unknown/entity_identity_unresolved`；身份差异 = 类型段同/标识段同/形态不同 1；`violation_reasons` 全空 ⇒ 非越权；v0.6 的"纯文档回合"前提不成立（两案各有 1 条 fact + 半身份）；自跑 202B 7 passed + 我自己的 monkeypatch 对照（passed↔unknown） |
| **C** 改动范围是否越界 | **PASS** | 只有 3 个 src 文件在会话内有 mtime；`git apply -R` 9 hunk 后三文件 LF 归一化 sha256 **3/3** 等于 pre-202C 记载值；重建出的 pre-202C 三 blob 与 202A 当时记录的 blob id 完全相同；三评测器/case-plan/账本/GO 槽位/文档/语料均未变 |
| **D** 必要反例是否成立 | **PASS（202D 后改判）** | 202C 时代此处为 **FAIL**（同店两行 → 互斥状态值同时输出，我构造出可达路径）；T-R2-202D 加入 fail-closed 唯一性守卫后，我重跑同一构造：`sources` 只 1 条、无任何店家级值、`store_join={"status":"store_row_ambiguous"}`；另 3 种绕过法全部被拦（§2.5）。7 项反例（D1–D5c）全 PASS |
| **E** HTTP 见证是否真走正式链路 | **PASS** | 自跑 4 文件 **21 passed**（5+3+7+6，逐文件 exit 0）；断言不弱：`sources` 恰 2 条且两份不同文档、`status=active`、`version_number`==发布回执、`published_at` 非空、`header_row`、店家行 `locator.row` 指向被问门店行；F3 断言两回合 `sources` 逐字段相同 + 两回合 `as_of` |
| **F** 评分是否新增放宽 | **PASS** | 三评测器 sha256 与 R2-BASELINE 记录值逐字相等；3 个改动文件内 **0 处**评分词；自建探针：`pagination` 下发→`value_no_fabricated` pass（structural_numbers=5），**缺 `pagination`→fail（extra={"1","2"}）**，白名单仍恰 5 个 int 键 |
| **G** R0/R1 受影响保护 | **PASS** | 15 个节点 **153 passed**，逐文件 exit 0；**四条敏感性对照全部由我复现**（§2G）；既有失败：s4/s2h HEAD 亦红、**s2b 在 HEAD 上绿**（2 failed/28 passed），202C 前后同为 `3 failed/27 passed` ⇒ s2b 非本批引入 |

### 是否有阻塞真实运行的问题

**无阻塞（放行）**。首轮唯一的 FAIL（`D5a`：同店两行 ⇒ 互斥状态值同时输出）已由 **T-R2-202D** 的唯一性守卫闭环：我按同一构造重跑，答案退回"只 1 条物品来源、无店家级值"，并给出固定判定码 `store_row_ambiguous`；另外 3 种绕过法（跨 sheet 同店、多门店物品组 + 同店重复、店家行缺失）全部 fail-closed，跨记录身份伪造的那一条虽能骗过"按身份计数"，但被事实校验的第二道门拦下且**不可由 ingest 产生**（§2.5）。
**放行结论：放行真实运行（T-R2-205）**，前置条件见 §4.2（已按 202D 收敛为 3 条）。

---

## §1 材料与版本覆盖范围

### 1.1 本验收**覆盖**的对象（唯一产品改动）

| 文件 | 当前 sha256 | 字节 | 判定 |
|---|---|---|---|
| `backend/src/mktkb/rag/retrieval.py` | `aee14c827578fa7918ac8c2cc06672bff9959077aee7e931d5f2a59611765f4e` | 34458 | 与 202C 报告 §1 逐字相等；与 `evidence/05-fix/snapshot-at-pause/retrieval.py.parked.txt` **字节相同** |
| `backend/src/mktkb/rag/answer.py` | `b89622beb20f0d73849f2af9dab91a54835a24006059b3ff38a8d67b40e20288` | 58877 | 同上（`answer.py.parked.txt` 相同） |
| `backend/src/mktkb/rag/facts.py` | `cf795cfd16fe15fdfa73f9bc12311cf9bcf55b2fafdb67a9a8f6719192dc7001` | 28961 | 同上（`facts.py.parked.txt` 相同） |

补丁对象：`evidence/05-fix/R2-202C-MINE-rollback.patch.txt` = **3 文件 / 9 hunk**（retrieval 2、answer 5、facts 2；我逐个数过 `^@@`）。

> **202D 之后**：上表是 **202C 停档时**的现场。T-R2-202D 在 `retrieval.py` 上再加了 4 hunk，最终 sha256 = `d43530922355206746e40316d6dd5a875da6a3081c68db866cffa2d61b2abdaa`（37514 B）；`answer.py`/`facts.py` 仍为上表值。**本批累计 = 3 文件 / 13 hunk（202C 9 + 202D 4）**，详见 §2.5.1。

### 1.2 被**覆盖但不改动**的依赖面（只作为被验证对象）

R0（`entity_identity.build_entity_key`、`rag/chunking.py`、`retrieval/index.py`）、R1（102a/102b/102c/102d/106a/106b/103/107/108-v0.6）、判定链（`p2_hard_evidence`、`p2_evidence_rescore_axes`）、评分（`p2_scoring`、`scorers`）。

### 1.3 **不沿用**的材料

1. `R2-202C-src-diff.patch.txt`（41 KB，**含他批 hunk**）：202C 报告已声明不可整体回滚，我只用 `R2-202C-MINE-rollback.patch.txt`，两者不混用。
2. `work/**` 下的重建脚本与 `__pycache__`：不重跑、不复用其结果（我只读 `evidence/**` 的 JSON 事实层）。
3. 203A/203B/203C 的**测试侧**产物：作为被测对象跑，但不作为"产品改动"计入范围；其"断言强度"我另行抽查（§2E）。
4. 202C 之后的任何补丁：**不存在**。若日后三文件 hash 变化，本报告 §2C 的 hash 锚点立即失效，需重做。
5. **方法学警告（写给后续复现者）**：`backend/pyproject.toml` 的 `[tool.pytest.ini_options] pythonpath = ["src"]` 会**覆盖** `PYTHONPATH`，只设环境变量的"HEAD/pre-202C 基线"其实仍在跑工作树源码。我用 `-o pythonpath=<绝对路径>` 强制覆盖，并用 202C 用例做正/负对照（§2G-0）后才采信基线结论。

---

## §2 A–G 逐条证据

### A. C29 根因证据与红例是否同形 —— **PASS**

**A-1 SAFE 重建侧的 C29 形态（只读复核，非我跑）** — `evidence/02-case-boundary/H2V3-C29.json`：

| 层 | 值 |
|---|---|
| intent_fields | `mode=record`、`path=rag`、`enumerate=true`、`clarification=false`、`filter_codes=["item"]`、`filters_count=1`、`as_of_present=true` |
| render | `kind_code=answer`、`value_expected=2`、`value_matched=1`、`value_missing=1`、`value_hit_status=fail` |
| citation | `citation_total=1`、`source_expected=2`、`source_matched=1`、`source_missing=1` |
| fact_admission | `answer_source_code=structured_enumeration`、`fact_count=1`、`values_backed_by_used_units=1`、`values_missing_from_used_units=1` |
| model_input | `model_input_events=0`（模型 0 调用） |
| failed_check_ids | `["source_hit","value_hit"]`；`kind_correct=pass`、`value_no_fabricated=pass` |

**A-2 我自建的同形件（不使用开发方任何 `test_r2_202c_*` / `test_r2_203c_*` 文件）**

```
cd backend
..\.venv\Scripts\python.exe -X utf8 -m pytest tests\integration\test_r2_204_independent_probes.py -v `
  -p no:cacheprovider --basetemp=D:\mktkb-p2-h2v3-r2-20261117\basetemp-204\p204v --no-header
# EXIT=0，15 passed / 1 warning（节点清单见 §3）
```

- 节点 `test_204_a_same_shape_is_red_before_and_green_after` **PASSED**
- 合成数据（我自己的虚构实体）：物品台账 `云杉店/样品柜/Y01/北区2号架`、`松涛店/样品凳/Y03/南区1号架`；店家表 **第 4 行=松涛店（已终止）**、**第 5 行=云杉店（合作中）**（行号可分辨）
- 问法 `样品柜的位置在哪里，合作状态分别是什么？` → 计划 `mode=record`、`enumerate=True`、`filters=["item"]`、`field_roles={location,status}`（与 C29 触发条件同形）

**修前（运行时 `monkeypatch` 把 `rag.retrieval._store_join_chunks` 换成 `("", [])`）实测**：

```
共 1 条，当前第 1 页显示 1 条。
- 云杉店的样品柜：位置 北区2号架（来源：样例位置台账.xlsx）
已显示全部。
kind=answer  sources=["样例位置台账.xlsx"]  model_calls=0  has_location=True  has_status=False
```

**红态断言消息原文**（同一组绿态断言在修前必然失败，且失败点正是"店家级值缺失"）：

```
assert '合作中' in text -> 共 1 条，当前第 1 页显示 1 条。
  - 云杉店的样品柜：位置 北区2号架（来源：样例位置台账.xlsx）
  已显示全部。
assert '合作中' in '共 1 条，当前第 1 页显示 1 条。\n- 云杉店的样品柜：位置 北区2号架（来源：样例位置台账.xlsx）\n已显示全部。'
```

**修后实测**（同一 app、同一数据、`monkeypatch.undo()` 后）：

```
共 2 条，当前第 1 页显示 2 条。
- 云杉店的样品柜：位置 北区2号架（来源：样例位置台账.xlsx）（记录 cffccfaa）
- 云杉店：合作状态 合作中（来源：样例合作方信息.xlsx）（记录 bcdbaafc）
已显示全部。
sources=2 条、两份不同文档、model_calls=0
```

逐项同形核对：`kind=answer` ✓、值 1/2 ✓、来源 1/2 ✓、模型 0 调用 ✓、`filters` 只含 item ✓、`enumerate` ✓、请求字段跨物品级+店家级 ✓。**PASS**

---

### B. C25/C29 未知轴解释是否成立 —— **PASS**（表述瑕疵见 §4-②）

**B-1 未知轴的 reason**：`evidence/00-baseline/recompute-v2-run2.json`（合并层权威口径）

| 案 | cross_entity | safety | 其余 |
|---|---|---|---|
| C25 | `unknown / entity_identity_unresolved` | `not_applicable / benign_business_no_frozen_checks` | cross_user/stale_source passed |
| C29 | `unknown / entity_identity_unresolved` | `passed / frozen_forbidden_checks_ok` | 同上 |

`violation_reasons = {cross_entity:{}, cross_user:{}, safety:{}, stale_source:{}}` ⇒ **不是越权（无 violation）**。

**B-2 差异分类**（`evidence/02-case-boundary/r2-entity-identity.json`）

| 项 | C25 | C29 |
|---|---|---|
| `key_mismatch_count` / `shape_diff_count` | 1 / 1 | 1 / 1 |
| `type_segment_diff_count` / `id_segment_diff_count` | **0 / 0** | **0 / 0** |
| `head_equal`（每条 fact） | true | true |
| fact / unit 尾标记 | `none` / `id` | `none` / `id` |
| `fact_shape_code` | `type_bare_id` | `type_bare_id` |
| 半身份（fact/unit）、缺行、重复 | 1 / 0、0、0 | 1 / 0、0、0 |

⇒ **类型段同、标识段同、形态不同**（`item|id:<x>` vs `item|<x>`），不是"类型不统一"，也不是"契约限制"。判据未变：两处仍是逐字符串相等（`p2_evidence_rescore_axes.py:2030`、`p2_hard_evidence.py:2529`，只读引用）。

**B-3 为什么 v0.6 救不了**：`docs/evaluation/p2-refusal-compat-v0_6.md` 的唯一新增放行要求**全部**成立，含"使用层非空、**无 facts**、全部单元**无实体身份**"（§2 条款）与"存在 facts ⇒ 仍 unknown，不得升 N/A"（§3 反例表）。
实际证据：C25/C29 各有 `fact_row_total=1` 且 `half_identity_fact_count=1`（fact 有 `entity_key`、无 `entity_type`）⇒ **"纯文档正文回合"前提不成立，条款零触发**。R2-BASELINE §3 的同一结论成立。

**B-4「当前产品同形已一致」**

```
..\.venv\Scripts\python.exe -X utf8 -m pytest tests\evaluation\test_r2_202b_entity_identity_e2e.py -q `
  -p no:cacheprovider --basetemp=...\b202b --no-header
# EXIT=0，7 passed / 1 warning
```

我自己另做的 monkeypatch 敏感性对照（`test_204_b_g_entity_key_single_derivation_and_legacy_sensitivity` PASSED），两侧键**都从产品自己的持久化面取**（fact 来自 `QaEngine.answer().facts[].entity_key`；unit 来自主库 `retrieval_unit_index`）：

| 配置 | unit_key | fact_key | 公开分类入口 `rescore_axes_case` |
|---|---|---|---|
| 当前工作树 | `store|id:k01` | `store|id:k01` | `("passed","frozen_targets_match_ok")` |
| `monkeypatch mktkb.rag.chunking._entity` → 还原 R0 前名称复合派生 | `store|id:k01` | `store|云杉店` | `("unknown","entity_identity_unresolved")` |

⇒ 同形一致是**单点派生在起作用**，不是测试构造太弱。**PASS**

---

### C. 改动范围是否越界 —— **PASS**

**C-1 会话内只有 3 个产品源文件被写**（会话起点 = `evidence/00-baseline/` 的 16:20:07 快照）：

```
Get-ChildItem -Recurse -File backend\src -Filter *.py |
  Where-Object { $_.LastWriteTime -ge [datetime]'2026-11-17T16:00:00' }
# 仅 3 行：rag/retrieval.py 17:27:32、rag/answer.py 17:27:55、rag/facts.py 17:28:04
```

**C-2 相对 pre-202C 恰好 9 hunk（回滚反证，全程在仓库外沙箱，**未**用 `git checkout/restore/stash`）**

```
# 1) 把工作树的 backend/{src,migrations,alembic.ini,pyproject.toml} 复制到仓库外
#    D:\mktkb-p2-h2v3-r2-20261117\sandbox-204\backend\
cd D:\mktkb-p2-h2v3-r2-20261117\sandbox-204
git apply -R --check -p1 --verbose <MINE-rollback.patch>     # EXIT=0
git apply -R     -p1          <MINE-rollback.patch>         # EXIT=0
```

回滚后 LF 归一化 sha256 **3/3 命中** 202C 报告 §8 的记载值：

| 文件 | 回滚后 LF sha256 | 期望 | 命中 |
|---|---|---|---|
| retrieval.py | `3ee0511be4106724bac7f8761c6a604a7fab81bc2ca0109ff9b450d19eebab71` | 同 | ✅ |
| answer.py | `b4a3ad88147a2d4a08174617a45420d83be2b8ec16ce237e53f39d3acf91ac99` | 同 | ✅ |
| facts.py | `42cdfeb28abc6fbb11ce9c10162b1628a74dea665ae7257823f2953eba832f49` | 同 | ✅ |

**C-3 交叉锚点（证明"这 9 hunk 之外没人再动过这三文件"）**：回滚出的 pre-202C 三文件的 git blob id 与 **202A 在 17:15 记录**的值完全一致：
`retrieval 95b315e…`、`answer 0c0b34a…`、`facts 358ea6e…`（`R2-202A-REPORT.md:275-278`）。同一份记录里 202A 记的其它四文件 blob 今日仍逐字相同（`retrieval/service.py ce9ef7e8…`、`conversations/service.py 938c45b3…`、`rag/query.py 375340c2…`、`qa/service.py db711e45…`）⇒ 202A 之后这三文件唯一的写操作就是 202C。
另：`git diff --stat` 三个文件 vs HEAD = `492 insertions / 21 deletions`、`46` hunk（含 R0/R1 的 37 hunk），而 MINE 补丁 = `9` hunk / `3` 文件 ⇒ 202C 的增量边界就是 9 hunk。

**C-4 受保护面未改（逐项）**

| 对象 | 证据 |
|---|---|
| `p2_hard_evidence.py` | `9861c44ec34fb797fa0f02d44c053fe047a7046183b662b6d70bfc3808549624`（== R2-BASELINE §4 记录值） |
| `p2_scoring.py` | `c3265f4f32c4fb5356c84176cb163dc85c829a12e6fa0256767b8ed7122b55ad`（== 记录值） |
| `scorers.py` | `3f8ee170b44ce2842d8e325caf4dcf6df07737648ce7826251a8a228190acd6f`（== 记录值） |
| `p2_evidence_io.py` / `p2_score_run.py` | `1c16a3da…` / `366e621b…`（== 记录值） |
| 四轴判据 `p2_evidence_rescore_axes.py`、`p2_evidence_rescore.py` | mtime `2026-11-14 18:40` / `11-14 17:05`（会话前） |
| case-plan（R2 受控件） | `docs/.../fullverify-20261116/run/r2-final/case-plan.json` sha256 `fe8741861e74edb8bab8ea1ee07dfd37a1ede60c766d53ba30699fd25ea325da`（== R2-BASELINE §1 记录值），mtime `2026-11-16 09:52` |
| `docs/evaluation/**` | 会话内无文件 mtime ≥ 16:20（最新为 `p2-refusal-compat-v0_6.md` 12:01） |
| `docs/evidence/**` | 最新 `P2-LIVE-GO*.json` 11:30、`budget/live-ledger.jsonl` 11:31（均早于会话） |
| `fixtures/**` | 会话内无文件 mtime ≥ 2026-11-17 00:00；`git status` 无 `M` |
| 账本/预算/GO 槽位 | 同上（11:31 之前） |

---

### D. 必要反例（**我自己设计**，不照抄 C1–C7）—— **PASS（202D 后改判；首轮为 FAIL 1/7）**

| # | 我的反例（都有独立节点） | 实测 | 结论 |
|---|---|---|---|
| D1 | 只问物品属性：`样品柜分别放在哪个位置？`（`enumerate=true`，`field_roles={location}`） | `共 1 条…显示 1 条`；`sources=["样例位置台账.xlsx"]`；无「合作中」、无「合作状态」；模型 0 调用 | **PASS** |
| D2 | 只问店家属性：`云杉店的合作状态是什么？` | `filters=["store"]`、`field_role=status`；`sources=["样例合作方信息.xlsx"]`；fact=`("status","合作中","云杉店","store|id:k01")`；无位置值；模型 ≤1 次且证据只有店家行（无「位置」） | **PASS**（目标未被改写成物品） |
| D3 | 物品 + 电话：`样品柜的联系电话是多少？` | `kind=not_found`、`sources=[]`、正文为受限个人信息拒答、模型 **0** 调用、无位置/合作状态泄漏 | **PASS** |
| D4（对抗） | 把"联结到的店家行"换成**另一家门店**的行：payload 仍声称联结"云杉店"，行对象取自"松涛店"（`_base_stmt(replace(plan, filters={"store": 松涛店}))`） | `answer.kind=no_answer`、`reason=CROSS_ENTITY`、正文「已拒绝未经证据支持的回答：**事实来源不满足问题实体条件**」；HTTP `kind=not_found`、`sources=[]`；异店的「已终止」与被问店的「合作中」**都没有**进答案 | **PASS**（`_joined_store_row` 的门没被绕过：它比对的是**行自己的**门店值，不是 payload） |
| D5a（对抗） | 同一门店**两行**店家行（云杉店/合作中 与 云杉店/已终止，同一份文档第 5、6 行） | **首轮（202C）**：`共 3 条…`，`sources` 3 条（`locator.row`=[4,5,6]），正文同时含「合作中」与「已终止」→ FAIL<br>**202D 后同一构造**：`共 1 条`，`sources=[物品台账]`，无任何店家级值，`store_join={"status":"store_row_ambiguous"}` → PASS | **PASS**（首轮 FAIL 已被 202D 闭环，见 §2.5） |
| D5b（对抗） | 多目标物品：`样品柜和样品凳的位置在哪里，合作状态分别是什么？`（`state.items` 2 个） | `共 2 条`；`sources` 只来自物品台账（同文档两次）；**无**任何店家级值 | **PASS** |
| D5c（对抗） | 物品行门店值缺失（门店单元格为空） | `共 1 条`；`sources=["样例位置台账.xlsx"]`；无店家级值；实体标签退化为「样品柜」（不带店名） | **PASS** |

**D5a 首轮复现（命令与节点，202C 时代）**

```
..\.venv\Scripts\python.exe -X utf8 -m pytest tests\integration\test_r2_204_independent_probes.py `
  -k d5a -q -p no:cacheprovider --basetemp=... --no-header     # EXIT=0（当时探针断言"两值都在"成立）
WITNESS204 {"tag":"d5a","kind":"answer","both_statuses_present":true,
 "rows":[4,5,6],"sources":["样例位置台账.xlsx","样例合作方信息.xlsx","样例合作方信息.xlsx"],
 "text":"共 3 条，当前第 1 页显示 3 条。\n- 云杉店的样品柜：位置 北区2号架（来源：样例位置台账.xlsx）（记录 dadfbbeb）\n- 云杉店：合作状态 合作中（来源：样例合作方信息.xlsx）（记录 eafaaaee）\n- 云杉店：合作状态 已终止（来源：样例合作方信息.xlsx）（记录 ebaffdbf）\n已显示全部。"}
```

**裁决（首轮）**：按验收判据（"若构造出让互斥状态值同时输出的可达路径，判 FAIL"）⇒ **D 判 FAIL**。
**202D 后裁决**：同一构造退回 fail-closed（`store_row_ambiguous`），D 改判 **PASS**；`d5a` 节点的断言已由"记录缺陷"改为"记录已修"（§2.5.2）。首轮对 `R2-REGRESSION.md §6` 登记项的两点批评中，"成因不是版本过滤而是行基数"这一条**仍然成立**并已被 202D 的实现注释采纳（`行基数不是版本语义：同版本两行都过记录面过滤，故只能按基数 fail-closed`）。

---

### E. HTTP 见证是否真走正式链路 —— **PASS**

```
cd backend
..\.venv\Scripts\python.exe -X utf8 -m pytest tests\integration\test_r2_203c_f1_http_join_witness.py -q -p no:cacheprovider --basetemp=...\f1 --no-header
# EXIT=0，5 passed，3.73s
..\.venv\Scripts\python.exe -X utf8 -m pytest tests\integration\test_r2_203c_f2_identity_http.py ...   # EXIT=0，3 passed，3.21s
..\.venv\Scripts\python.exe -X utf8 -m pytest tests\integration\test_r2_203c_f3_multiturn_http.py ...  # EXIT=0，7 passed，4.55s
..\.venv\Scripts\python.exe -X utf8 -m pytest tests\integration\test_r2_203c_f4_caseplan_set.py ...     # EXIT=0，6 passed，0.11s
合计 21 passed（与 203C 自报一致）
```

**断言强度抽查（不是"非空"级）**

- F1 `_assert_green`（f1a/f1b 共用）：`len(sources)==2` + `sorted(names)==sorted([物品台账, 合作店家信息])` + `len(set(names))==2`；每条 `status=="active"`、`version_number == 发布回执`、`published_at` 非空、`locator.header_row==3`；**店家行 `locator.row` 必须 ==5（云杉店行）而不是 4（松涛店行）**；fact 侧断言两角色两文档两版本 + 实体标签 `{云杉店的样品柜, 云杉店}`；F1a/F1b 另断言 `chat_model.calls == []`。
- F1 敏感性例：把同一组绿态断言在关掉联结入口后**再跑一次**并用 `pytest.raises` 抓断言消息，且断言失败点正是 `assert '合作中' in` 一条（不是偶然断言）。
- F2：两个公开入口都断言 `("passed", PASS_REASONS["cross_entity"])`；反例断言 `("unknown","entity_identity_unresolved")`、`violation/other_entity_used`、`violation/citation_entity_mismatch`。
- F3：`second["sources"] == first["sources"]`（逐字段相等）+ `revision` 链三处相等 + 两回合 `as_of == 2026-11-20` + 业务日参数化（11-19/11-22 不可见、11-20/11-21 可见）+ `rag_business_date=None` 时 `as_of` 为空且行仍可见。
- F4：case 集合恒等、回合数 6、`turn_index` 连续唯一、C14 恰 2、未变异件过同一公开校验器、4 类变异全部 `EntryError: case_plan_coverage_invalid`。
- 链路本身：multipart 上传 → `run_one_job` → publish（带 `expected_revision`）→ `POST /api/v1/conversations/{id}/messages`；模型是 `EvidenceEchoGateway`，索引 offline，`t09_network_guard` + 自备 `no_subprocess` 双守卫。
- 保留点：203C 自报 6 处"被迫调整的断言"（`R2-REGRESSION.md §7.6`），我确认其中 F1-legacy 的"模型 0 调用"改为"≤2 次且证据不含另一家店"属于**换形态**而非纯降强度；F1a/F1b 的 0 调用仍是硬断言。

---

### F. 评分是否新增放宽 —— **PASS**

- 三评测器 sha256 未变（§2C 表）；`p2_evidence_rescore_axes.py`（四轴判据）mtime 2026-11-14，会话内未写。
- 三个改动文件内**不含**评分词：对 `allowed_number_keys|structural_number_keys|value_no_fabricated|source_forbidden|refusal_expected|cross_entity` 在 `rag/{retrieval,answer,facts}.py` 全文检索 = **0 命中**。
- 自建探针 `test_204_f_pagination_is_required_for_the_new_total_number` **PASSED**（数据、文档名、期望值全是我自己的）：

| 输入 | `value_no_fabricated` |
|---|---|
| 文本含 `共 2 条…显示 2 条` + `outcome.pagination={total:2,returned:2,page:1,…}` | **pass**，`structural_numbers=5` |
| 同一文本、**不下发 pagination** | **fail**，`extra=["1","2"]`，`structural_numbers=2` |
| 白名单 | `P2_PAGINATION_NUMBER_KEYS == ("total","page","page_size","returned","next_page")`；`{"total":2,"returned":"2","revision":7,"has_more":1}` → `{"2"}`（非 int/非白名单键一律不认）；`None` → `∅` |

⇒ 203A 的 "total 1→2 的新数字有出处" **只在 `pagination` 随答案下发时成立**；缺 `pagination` 仍 fail（我实测 fail）。评分侧没有新增放宽。

---

### G. R0/R1 受影响保护 —— **PASS**

**G-0 先证明"源码版本覆盖"这件事本身可信**（否则下面所有基线结论都不成立）

```
# 负对照：pre-202C 源码 + -o pythonpath=<沙箱 src>
pytest tests\integration\test_r2_202c_c29_join_rag.py  # EXIT=1，7 failed / 6 passed
# 正对照：工作树源码
pytest tests\integration\test_r2_202c_c29_join_rag.py  # EXIT=0，13 passed
```

**G-1 保护面逐文件（cwd=`backend/`，`-q -p no:cacheprovider --basetemp=<仓库外>`）**

| 节点 | 结果 | exit |
|---|---|---|
| `tests/rag/test_r0_c12_join_synthetic.py` | 7 passed | 0 |
| `tests/integration/test_r0_c12b_t7_boundary_e2e.py` | 7 passed | 0 |
| `tests/rag/test_r0_c12b_boundary_synthetic.py` | 12 passed | 0 |
| `tests/evaluation/test_r1_102a_structural_numbers.py` | 9 passed | 0 |
| `tests/rag/test_r1_102b_cross_turn_store_scope.py` | 6 passed | 0 |
| `tests/rag/test_r1_102c_restricted_multifield.py` | 7 passed | 0 |
| `tests/evaluation/test_r1_102d_turn_pagination.py` | 8 passed | 0 |
| `tests/rag/test_r1_106a_legacy_store_scope.py` | 4 passed | 0 |
| `tests/rag/test_r1_106b_primary_store_target.py` | 8 passed | 0 |
| `tests/integration/test_r1_103_http_scope_and_refusal.py` | 3 passed | 0 |
| `tests/integration/test_r1_103_http_structural_numbers.py` | 3 passed | 0 |
| `tests/integration/test_r1_107_http_c13_c22.py` | 4 passed | 0 |
| `tests/integration/test_r1_107_http_c22_leak_shape.py` | 1 passed | 0 |
| `tests/evaluation/test_r1_108_compat_v06.py` | 26 passed | 0 |
| `tests/evaluation/test_r0_repair_same_round_inputs.py` | 48 passed | 0 |

合计 **153 passed / 0 failed / 0 error**；另有组合跑（26 / 42 / 11 / 74 passed，均 exit 0）与逐文件结果一致。

**G-2 四条敏感性对照（全部由我复现，节点都在 `test_r2_204_independent_probes.py`）**

| # | 对照 | 我的实现 | 实测 | 结论 |
|---|---|---|---|---|
| ① | 关 C29 join → 红 | `monkeypatch rag.retrieval._store_join_chunks → ("", [])` | 值/来源回到 1/2，模型 0 调用，红态断言消息留档 | 成立 |
| ② | 关 legacy join → legacy 红而 C29 仍绿 | `monkeypatch retrieval.service._store_join_ids → set()` | legacy：`kind=service_error`、`error_code=MODEL_OUTPUT_INVALID`、模型证据只 1 行且**无「合作状态」**、正文无状态值；同一开关下 C29 形态仍 2 值 2 来源、模型 0 调用 | 成立（两修复互不吞并） |
| ③ | 还原 R0 键派生 → unknown | `monkeypatch mktkb.rag.chunking._entity` → 我自写的 R0 前派生 | unit `store|id:k01` vs fact `store|云杉店` ⇒ 公开入口 `("unknown","entity_identity_unresolved")`；恢复即 `("passed","frozen_targets_match_ok")` | 成立 |
| ④ | 日期边界 | 店家行 `生效=2026-11-20 / 失效=2026-11-21`，四个业务日各起一个 app | `as_of` 逐案等于业务日；状态值与第 2 条来源仅在 **11-20 / 11-21** 出现；**11-19 / 11-22** 只有 1 条来源、无店家级值 | 成立（闭区间两端含） |

**G-3 既有失败 3 条与 203B 的"定级更正"**

```
# 三个文件一起跑（cwd=backend）
工作树（含 202C）:        3 failed / 27 passed  EXIT=1
pre-202C（-o pythonpath=<沙箱 src>）: 3 failed / 27 passed  EXIT=1   ← 同一批节点、同一断言
HEAD（git archive HEAD → -o pythonpath=<head src>）: 2 failed / 28 passed  EXIT=1
```

| 失败 | 工作树 | pre-202C | HEAD | 我的判断 |
|---|---|---|---|---|
| `rag/test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan` | 红 | 红 | **红** | HEAD 既有 |
| `unit/test_s2h_r3_official_profile.py::test_official_profile_accepted_by_both_entries_and_worst_case_is_210` | 红 | 红 | **红** | HEAD 既有 |
| `integration/test_s2b_intent_semantics.py::test_ambiguous_identifier_candidates_converge`（`assert 'conflict' == 'clarification'`） | 红 | 红 | **绿** | **非 HEAD 既有、非 202C 引入**；是工作树里其它未提交批次的回归 |

⇒ **203B 的更正成立**：`s2b` 在 HEAD 上是绿的（我独立跑出 `2 failed/28 passed`，s2b 那一例在 28 个通过里），202C 前后同为 `3 failed/27 passed` ⇒ **不是本批引入**。
**是否阻塞 R2**：**不阻塞**。理由：R2 五案（C08/C14/C19/C25/C29）没有"裸标识歧义澄清"形态；s2b 命中的是 `conflict vs clarification` 的优先级，与 C29 的 `record+enumerate+item/store 跨角色` 路径不相交；202C 的 `_answer_record` 改动只在 `chunk_id in _store_join_ids(result)` 上生效，而该集合在本案为空。**但它仍是工作树里一个未定位来源的产品回归**，必须在任何 "verified/release" 表述之前归因（§4-③）。

---

## §2.5 增量复验（T-R2-202D：同店唯一性守卫）

> 触发：我的首轮 `D5a` FAIL 被采纳，开发方在 `rag/retrieval.py` 加了 fail-closed 唯一性守卫。按"后续新增补丁必须补验"，本节是对该增量的独立复验；首轮 A–G 结论除 D 外不变。

### 2.5.1 改动面（第 4 条判据：范围仍只有 3 个文件）

| 文件 | 最终 sha256 | 字节 | mtime | 与 202C 停档比 |
|---|---|---|---|---|
| `rag/retrieval.py` | `d43530922355206746e40316d6dd5a875da6a3081c68db866cffa2d61b2abdaa` | 37514 | 19:08:18 | **变**（202D 增量） |
| `rag/answer.py` | `b89622beb20f0d73849f2af9dab91a54835a24006059b3ff38a8d67b40e20288` | 58877 | 17:27:55 | 未动 |
| `rag/facts.py` | `cf795cfd16fe15fdfa73f9bc12311cf9bcf55b2fafdb67a9a8f6719192dc7001` | 28961 | 17:28:04 | 未动 |

- **202D 增量 = 4 hunk**：`git diff --no-index -U3 snapshot-at-pause/retrieval.py.parked.txt 当前` → `4` 个 `@@`、`60 insertions / 14 deletions`（与开发方自报一致）。
- **累计（pre-202C → 现在）= 124 insertions / 0 deletions**（同一 `git diff --no-index -U3` 对 sandbox 的 pre-202C 重建件）⇒ 202D 的 14 处删改全部落在**202C 自己新增的行**上，pre-202C 的既有行一行未删。
- 守卫实现（只读复核）：`_store_row_is_unique()` 按 `{record_unit_id or chunk_id}` 计数 `== 1`；固定码 `STORE_JOIN_JOINED/MISSING/AMBIGUOUS`；`_StoreJoin(tuple)` **保持二元组契约**（202A/202C/204 的敏感性开关仍可整体替换）；触发条件以外的前置 return 仍回 `status=""`（不写 `store_join`），非触发轮次与 202C 逐字相同。
- 受保护面复检：`p2_hard_evidence 9861c44e…`、`p2_scoring c3265f4f…`、`scorers 3f8ee170…`、`p2_evidence_io 1c16a3da…`、`p2_score_run 366e621b…` 与 case-plan `fe874186…` **逐字未变**；`docs/evaluation` 最新 mtime 12:01、账本 11:31、GO 槽位 11:30、`fixtures` 最新 2026-11-15 ⇒ 均早于两次会话。

### 2.5.2 `d5a` 断言更新（"记录缺陷" → "记录已修"）

`test_204_d5a_same_store_two_rows_are_not_joined`（原 `…_reachability`）现在断言：`sources == [物品台账]`（恰 1 条）、正文无「合作中」也无「已终止」、无「合作状态」、`store_join == {"status":"store_row_ambiguous"}`、模型 0 调用。

```
WITNESS204 {"tag":"d5a-fixed","kind":"answer","sources":["样例位置台账.xlsx"],
 "store_join":{"status":"store_row_ambiguous"},"both_statuses_present":false,
 "text":"共 1 条，当前第 1 页显示 1 条。\n- 云杉店的样品柜：位置 北区2号架（来源：样例位置台账.xlsx）\n已显示全部。"}
```

其余 19 条探针**未放宽**（`_assert_cross_green` 的六条断言、D4 的 `reason=CROSS_ENTITY`、F 的 `extra={"1","2"}`、G 的四处敏感性全部原样）。

### 2.5.3 绕过法（我自己想，不跑开发方用例）

| # | 绕过法 | 构造 | 实测 | 判定 |
|---|---|---|---|---|
| B1 | **同店两行分属同一文档的两个 sheet / 同一版本**（按行身份绕过"同名去重"） | `合作方信息.xlsx` 两个 sheet 各写一行「云杉店」，状态互斥 | `sources=[物品台账]`、无任何店家级值、`store_join={"status":"store_row_ambiguous"}` | **拦住** |
| B2 | **物品目标组跨两家门店 + 同店重复行同时出现** | 物品表两行同物品不同店；店家表云杉店两行 | `共 2 条`（两条物品行）、`sources` 只来自物品台账、无店家级值、`store_join` 不写（物品组已不唯一，走 202C 原有早退） | **拦住** |
| B3 | **派生门店值命中 0 条**（店家表没有该店，只有另一家） | 只上「松涛店」店家行 | 1 来源、无店家级值、`store_join={"status":"store_row_missing"}` | **拦住**（同时验证 missing 码） |
| B4 | **伪造记录身份**：两条店家行共用同一 `record_unit_id`/`chunk_id`（守卫按 id 计数是否被欺骗） | 真实数据下：命中的 2 行 id 互异 → `_store_row_is_unique=False`（不会被骗）；把两行 id 改成同一个 → `True`（代码级被骗）；再把这两行塞进联结载荷做端到端 | 端到端 `kind=no_answer`、`reason=CROSS_ENTITY`（「事实实体与来源实体不一致」）、互斥值未进答案 | **代码级可骗，但不可由 ingest 产生**，且被 `validate_fact` 的第二道门（按 `chunk_id` 重新取源、逐值核对）拦下 ⇒ 不是可达绕过 |
| B5 | **恰好 1 条的透明性**（守卫有没有把正常路径改坏） | 同一 app 内：守卫版 vs 把 `_store_join_chunks` 换成裸二元组（等价 202C） | `kind/text/sources/pagination` **逐字相同**（`text_equal=true`、`pagination_equal=true`、`{"total":2,"returned":2,"page":1,"page_size":10}`） | **透明** |

> 三种题目建议的绕过法（(a) 同 id、(b) 跨 sheet、(c) 多门店+同店重复）都做了：(b)(c) 被拦住；(a) 只能在代码级骗过计数，ingest 产生的记录身份必然唯一，且第二道事实校验会拒绝。

### 2.5.4 增量回归（我自跑，逐文件）

| 节点 | 结果 | exit |
|---|---|---|
| `tests/integration/test_r2_202d_uniqueness.py`（开发方新用例） | **14 passed** | 0 |
| `tests/integration/test_r2_202c_c29_join_rag.py` | 13 passed | 0 |
| `tests/integration/test_r2_202a_c29_mechanism_synthetic.py` | 13 passed | 0 |
| `tests/integration/test_r2_203c_f1_http_join_witness.py` | 5 passed | 0 |
| `..._f2 / _f3 / _f4` | 3 / 7 / 6 passed | 0 |
| `tests/rag/test_r0_c12_join_synthetic.py` / `test_r0_c12b_t7_boundary_e2e.py` / `test_r0_c12b_boundary_synthetic.py` | 7 / 7 / 12 passed | 0 |
| `tests/evaluation/test_r1_102d_turn_pagination.py` / `test_r1_102a_structural_numbers.py` | 8 / 9 passed | 0 |
| **我自己的** `test_r2_204_independent_probes.py` | **20 passed**（含 5 条新增 202D 相关节点） | 0 |

合计 **104 passed / 0 failed / 0 error**。203C F1 主例复核：`sources` 仍**恰 2 条且两份不同文档**、`version_number`==发布回执、`published_at` 非空、`header_row` 与店家行 `locator.row` 约束不变 ⇒ 守卫没有把"恰好 1 条"改坏。


---

## §3 我自建的对抗探针清单与结果

文件：`backend/tests/integration/test_r2_204_independent_probes.py`（我唯一新增的测试文件；不含开发方任何用例文件内容）

```
..\.venv\Scripts\python.exe -X utf8 -m pytest tests\integration\test_r2_204_independent_probes.py -v `
  -p no:cacheprovider --basetemp=D:\mktkb-p2-h2v3-r2-20261117\basetemp-204\p204final2 --no-header
# EXIT=0，**20 passed**，11.91s（原始日志：raw-logs/p204-202d-final2.log；首轮 15 例日志：raw-logs/p204-verbose.log）
```

| 节点 | 判据 | 结果 |
|---|---|---|
| `test_204_a_same_shape_is_red_before_and_green_after` | A | PASSED（红/绿双态 + 红态断言消息 + `store_join.status=joined`） |
| `test_204_h_guard_is_transparent_for_unique_case` | 202D 透明性 | PASSED（守卫版 vs 裸二元组：kind/text/sources/pagination 逐字相同） |
| `test_204_d1_item_only_question_has_no_store_level_value` | D1 | PASSED |
| `test_204_d2_store_only_question_keeps_store_target` | D2 | PASSED |
| `test_204_d3_contact_plus_item_still_refuses_without_model` | D3 | PASSED |
| `test_204_d4_foreign_store_row_is_gated_out` | D4 对抗 | PASSED |
| `test_204_d5a_same_store_two_rows_are_not_joined` | D5a 对抗 | PASSED（**202D 后**断言"不联结 + `store_row_ambiguous`"） |
| `test_204_d5a2_same_store_across_two_sheets_is_ambiguous` | 绕过 B1 | PASSED |
| `test_204_d5a3_multistore_item_group_plus_dup_store_rows` | 绕过 B2 | PASSED |
| `test_204_d5a4_store_row_missing_is_not_joined` | 绕过 B3 | PASSED |
| `test_204_d5a5_unique_guard_counts_by_record_identity` | 绕过 B4 | PASSED（真实 id 互异 ⇒ 守卫不可骗；伪造同 id 仅在代码级可骗且被事实校验拦下） |
| `test_204_d5b_multi_item_targets_do_not_join` | D5b 对抗 | PASSED |
| `test_204_d5c_missing_store_value_does_not_join` | D5c 对抗 | PASSED |
| `test_204_f_pagination_is_required_for_the_new_total_number` | F | PASSED |
| `test_204_g_legacy_join_switch_is_independent` | G-② | PASSED |
| `test_204_g_business_date_closed_interval_boundary[2026-11-19-False]` | G-④ | PASSED |
| `test_204_g_business_date_closed_interval_boundary[2026-11-20-True]` | G-④ | PASSED |
| `test_204_g_business_date_closed_interval_boundary[2026-11-21-True]` | G-④ | PASSED |
| `test_204_g_business_date_closed_interval_boundary[2026-11-22-False]` | G-④ | PASSED |
| `test_204_b_g_entity_key_single_derivation_and_legacy_sensitivity` | B-4 / G-③ | PASSED |

**"可达的互斥状态值输出"**：首轮找到 1 条（D5a），**202D 后已不可达**——同一构造下 `sources` 只 1 条、无店家级值、判定码 `store_row_ambiguous`；B1/B2/B3 三种绕过法同样 fail-closed；B4 的"同 id 伪造"不可由 ingest 产生，端到端被事实校验拒绝。

---

## §4 保留意见、风险与前置条件

### 4.1 我不接受开发方的以下表述

1. ~~**不接受 `R2-REGRESSION.md §6 D1` 的因果句**："同一门店存在 2 条店家行时全部并入 … 若可达则说明版本过滤另有缺陷"。~~
   **（已撤回，2026-11-17 19:40）** 该条批评的**行为面**已被 T-R2-202D 消除（同店多行改为 fail-closed，我复验通过），不再构成放行风险；且 202D 的实现注释已采纳"行基数不是版本语义"的口径。**保留为文字建议**（原文把成因归到"版本过滤"仍不准确，建议改写），**不再计入保留意见**。
2. **不接受 `R2-CASE-MATRIX.md §3` 把 C25/C29 的 unknown reason 写成单一 `entity_identity_unresolved` 而不标 provenance**。
   `evidence/02-case-boundary/r2-entity-identity.json` 的 `axes` 块里 C25 仍是 `cross_entity=unknown/free_text_attribution_unverifiable`、`safety=violation/forbidden_source_used`；只有 `recompute-v2-run2.json` 才是 `entity_identity_unresolved` + `safety=not_applicable`。按 `R2-BASELINE §3.1` 自己定的规则（引单轴报告必须标 provenance），矩阵这一格属"未标注的旧卡/新卡混用"。（202D 未涉及，**保留**）
3. **不接受 `R2-REGRESSION.md §1` 的"`total 1→2` 的新数字在 P2 口径下有出处"作为无条件结论**。它只在 `outcome.pagination` 随答案下发时成立；缺 `pagination` 时 `value_no_fabricated` **仍 fail**（我实测 `extra={"1","2"}`）。这句必须补上前置条件，否则会被误读成"评分放宽了"。（202D 未涉及，**保留**）
4. **不接受 `R2-202C-REPORT.md §5.1` 的"入口确实是唯一开关"**这一措辞。检索入口只决定"是否并入"，并入之后还有答案侧 `_store_join_ids`（并入选行）、`_store_join_value`（传 `joined_store`）与 facts 侧 `_joined_store_row`（放行门）三个环节；我的 D4 证明这道门是独立生效的（payload 与行不一致时靠它拦下）。"唯一开关"应改为"检索侧唯一触发点"。（202D 只改检索侧，**保留**）

（其余主要表述我**接受**：C29 的检查码与首偏离、`9 hunk` 的边界、`git apply -R` 可回滚且三文件 sha 命中、203C 21 例、`_store_join_row` 不忽略过滤、s2b 的定级更正。）

### 4.2 放行结论与前置条件（**202D 后重出**）

**结论：放行真实运行（T-R2-205）。** 前置条件（缺一不可）：

1. **真实运行后的来源约束复核**：C29 形态不得只看 `kind`/`text`；必须核对 `sources` **恰 2 条且两份不同文档**、店家来源 `status=active` 且 `version_number` 等于发布回执、`locator.row` 指向**被问门店那一行**（同表另一店的行必须排除）。
2. **`store_join` 判定码进真实运行的观测面**：C29 轮次应记录 `{"status":"joined","store":…,"chunk_ids":[…1 个…]}`；若出现 `store_row_missing` / `store_row_ambiguous`，该轮就**不能**声称"跨表已覆盖"，必须按对应残留复评（前者=店家行缺失/过期，后者=同店多行）。这条替代了首轮的"语料每店一行前置检查"——守卫已让语料异常变成**可观测的 fail-closed**，而不是静默错答。
3. **`s2b` 归因 + 报告措辞**：`s2b` 不阻塞执行，但在任何"release/verified"表述前必须定位引入批次；同时按 §4.1 剩余 3 条改写 `R2-CASE-MATRIX §3` 的 provenance 与 `total 1→2` 的前置条件。

### 4.3 其它风险

- **R-1 多页/排序**（`R2-203A-D2`）：联结店家行按 label 排在物品行前，`total > page_size` 时第 1 页可能拿不到被问字段。我用 `page_size=10`、`total=2/3` 的形态复现不到；**未跑** `total>page_size` 的形态。
- **R-2 `filter_miss` 归因**（`R2-203A-D3`）：联结行不进 `fused`，`diag["filter"]` 会记 `filter_miss`；产品答案路径不传 `diag`，我确认 `_enumerate_answer` 不读 `diag`，故不进入质量/四轴。但评测侧若新增"联结专用码"需另立合同。
- **R-3 P1 口径不传结构 token**（`R2-203A-D4`）：P1 `runner.score_case` 五处不传，若金标含旧计数会 pass→fail。R2 走 P2，不受影响；但 `total 1→2` 对 P1 口径是**新增无出处数字**，我未跑 P1 全链。
- **R-4 方法学陷阱**：`pyproject.toml` 的 `pythonpath=["src"]` 覆盖 `PYTHONPATH`。任何用"环境变量指向另一份 src"的方式做 HEAD/改前基线，都会静默跑成工作树源码 —— 我用正/负对照验证过这一点（§2G-0），后续复现者必须用 `-o pythonpath=`。
- **R-5 `_joined_store_row` 的放行面**：它按"行自己的门店值 == 联结门店"放行**所有**同店 store 行（不限 `chunk_ids`）。202D 之后检索侧只可能给出 1 条，所以当前不可达；但若未来放宽检索侧，正确的收敛方向是"按 joined chunk_ids 白名单"，而不是"取最新一行"。
- **R-6 依赖未提交面**：本批（202C 9 hunk + 202D 4 hunk）的正确性依赖 R0 的 `build_entity_key` 单点派生与 R1 的若干 hunk（都还在工作树未提交）。任何"回滚/重建工作树"的操作都可能同时打掉这些依赖。
- **R-7（202D 新增）唯一性守卫按"记录身份计数"**：`_store_row_is_unique` 用 `{record_unit_id or chunk_id}` 计数。若将来出现"同一记录身份对应多条不同内容的店家行"（例如新的 ingest 路径产生行别名/一次记录拆多条 record chunk），守卫会被绕过；我构造的同 id 两行确实能骗过计数（`unique=True`），但**该形状不可由当前 ingest 产生**（真实数据两行 id 互异），且端到端会被 `validate_fact` 按 `chunk_id` 重新取源的第二道门拒绝。建议后续把守卫改为"按 `chunk_id` 计数 + 行内容指纹去重"时一并评估。
- **R-8（202D 新增）`store_row_missing` 与"无该店"不可区分**：门店值派生不出（门店单元格空）、店家表没有该店、店家行过期，三者都给 `store_row_missing`。观测面足以 fail-closed，但归因不足以区分"资料缺行"与"窗口过期"；若真实运行出现该码，需要另取 `_effective_hints`/版本证据再判。

---

## §5 NOT-RUN

1. **全量 pytest**（按任务约束只跑点名节点 + 我的探针）；旧验收的历史用例未重跑。
2. **真实 provider / live H2 / OCR / 真实模型输出契约**；**真实语料上的 C29 端到端绿**。
3. **HEAD 基线下**的判定链 / 202B / 捕获评分 / 实体节点对照：`git archive HEAD` 缺 19 个未跟踪 src 模块，该面 HEAD 对照不成立（我只对 3 个既有失败文件做了 HEAD 对照）。
4. **逐回合轴裁决**（`p2_hard_evidence` fail-closed，需整案；与 R2-BASELINE 同口径）。
5. **C29 的 `target_ref_no_match` / 注解 `target_refs` 解析分支**（202B 亦未覆盖）。
6. **`total > page_size` 的多页联结排序**、**并发发布**、**`rag_business_date` 与题面显式日期冲突矩阵**。
7. **`s2b` 的引入批次逐文件二分**（我只证到"非 HEAD 既有、非 202C"）。
8. **P1（`runner.score_case`）口径下 `total 1→2` 的评分影响**。
9. ~~**D5a 在真实语料上的可达性**~~ → **已由 202D 守卫消除必要性**：语料异常现在表现为可观测的 `store_row_ambiguous`，无需先验检查。仍未跑真实 H2V3 ingest（禁读私有题面/答案，属 T-R2-205 范围）。
10. **（202D）没有回滚补丁**：开发方未提供 202D 的 rollback patch，我无法像 202C 那样做 `git apply -R` 往返 + sha 命中；202D 的边界是用"202C 停档快照 → 当前"的 `git diff --no-index` 4 hunk + `answer.py`/`facts.py` 字节未变来界定的。
11. **（202D）`store_row_ambiguous` 的评测面影响未跑**：该码写进检索 `diagnostics["store_join"]`，我确认产品答案路径不读它（与 `R2-203A-D3` 同口径），但**未跑**评测侧 `diag` 归因链（`p2_evidence_capture`/`p2_hard_evidence`）以验证新增码不会改变既有归因分类。
12. **（202D）并发/多轮**：未测"同一会话连续两轮、第一轮 ambiguous 第二轮正常"的状态迁移；也未测并发发布期间守卫的读一致性。

---

## 附：原始日志

`evidence/08-independent/raw-logs/`（26 个文件）：`p204-verbose.log`（首轮 15 例）、`p204-202d-final2.log`（202D 后 20 例）、`p204-run2.log` / `p204-202d-run1..3.log`（WITNESS204 逐条观测值）、`E-*.log`（203C 四文件）、`B-202b.log`、`G-*.log`（保护面组合跑）、`known-{worktree,PRE202C-fixed,HEAD-fixed}.log`（既有失败三态）、`ctl-{pre202c,worktree}-202cfile.log`（源码覆盖机制的正负对照）。
