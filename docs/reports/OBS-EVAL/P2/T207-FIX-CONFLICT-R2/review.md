# P2-T207-FIX-CONFLICT-R2 独立验收（冲突回答 text 披露取值）

- 验收对象：工作区未提交改动 `backend/src/mktkb/conversations/service.py`、`backend/src/mktkb/copy.py`、新增 `backend/tests/integration/test_t207_fix_conflict_r2.py`、`docs/reports/OBS-EVAL/P2/T207-FIX-CONFLICT-R2/`。
- 现场：分支 `codex/p2-e2e`，HEAD `489aadd`（验收前后一致，无新 commit）；Python 3.12.7（`.venv`）；**零真实调用、零出站**（Mock/offline 替身 + 独立 socket 闸门实测）。
- 方法：脚本对 HEAD 版本与工作区版本各跑一遍（`--src` 指向 HEAD 源码副本），同一冻结题集、同一装配、同一评分器；差分由验收侧脚本自行计算，不采信开发侧结论。
- 本文件与 `evidence/verify/` 是本次验收唯一写入；未改产品/测试/夹具/评分器/账本/预算/GO。

## 0 结论

**接收（阻断 0）。** 6/6 判定 PASS；附带条件是**提交白名单**（环境事件见 §1，白名单见 §6）。

| # | 判定项 | 结论 | 关键读数 |
|---|---|---|---|
| 1 | 范围/零出站/无 commit | PASS | 本包只改产品两文件（+37/−5）+ 1 个新测试 + 报告目录；`evaluation/**`（本包零改动；并行包另计，见 §1）、`fixtures/**`、评分器/计划/门槛/账本/预算/GO 均无改动；无 skip/xfail；HEAD 未变；出站 0 |
| 2 | 通用渲染（非硬编码） | PASS | 只用 `ConflictView.field/entries`；空白折叠/去重/8 条上限+「等」行为由实现+探针+测试证明；非冲突文案 52 例逐字不变 |
| 3 | 冻结评分 C05/C06 fail→pass、N08 不变 | PASS | C05/C06：`value_hit fail→pass`（其余 check 保持），status `fail→pass`；N08 文本与 checks 逐字不变；conflicts/sources 结构不变；每轮模型调用 0 |
| 4 | 54 例差分仅 {C05,C06} | PASS | 变更集合 = C05/C06 的 `text`、`strict_status`、`strict_problems`；其余 52 例 kind/text/sources/conflicts/candidates/status/strict/problems 全同 |
| 5 | 回归零失败 | PASS | 138 + 27 + 8 + 41 +（附加 10）= 224 passed，0 failed/error |
| 6 | 限制与风险结论 | PASS（如实披露，见 §2.6） | 8 条披露上限与「候选窗口外取值」均不阻断 R4 三例；残余风险已列 |

## 1 验收现场与对照装配

- 开工时（05:4x）`git diff --name-only` 只有 `service.py`/`copy.py` 两个产品文件；另有 3 个 `T207/PM/*.md` 与 `T207/report.md`（mtime 05:21–05:24，早于本包代码 05:35）和 `.claude/handoffs/_index.md`（mtime 11-10 17:43Z），内容均为 R4 计划/预算/R4PREP/协调区说明，**不属本包**。`evaluation/**` 当时是干净的。
- before 源 = HEAD `489aadd` 的 `backend/src` 副本，仅用 `git show` 还原 `service.py`/`copy.py` 两个文件（其余与 HEAD 逐字一致）；after 源 = 工作区 `backend/src`。两侧都能被证明加载正确版本（`variant_probe`：before 输出「资料中对X记录了多个有效值…」，after 输出「资料中存在多个有效值：X。…」）。
- **环境事件（重要）**：验收进行中（05:56Z 起）并行包 `P2-T207-FIX-LIVECAP`（其 dev 任务书 05:51Z 生成，明确允许改 `evaluation/{product_adapter.py,p2_live.py}`）开始写工作区：`evaluation/p2_live.py`（+123 行 `RequestCeiling/provider_single_request_bounds`，05:56:23Z 出现瞬时 4 字节后 05:56:54Z 稳定）、`evaluation/product_adapter.py`（+25 行 live 单请求上限推导，05:57:10Z）、`backend/tests/evaluation/test_p2_live_request_ceiling.py` 与仓库根 `.p2cap_probe*.py`。
- 证据时点：本包四份核心证据分别写于 05:46:19Z / 05:46:55Z / 05:48:50Z / 05:49:06Z，汇总 05:56:10Z，**全部早于 LIVECAP 的首个写入（05:56:23Z）**；相关回归套件走 Mock、不经过 live 装配。因此本次结论不受并行改动影响；但这些文件现在留在工作区，**提交本包时必须排除**（见 §6）。

## 2 逐条判定与证据

### 2.1 判定 1：范围 / 零真实出站 / 无 commit —— PASS

| 检查 | 结果 | 证据 |
|---|---|---|
| 只改产品两文件 + 新增 1 测试 + 报告目录 | 是 | 开工时 `git diff --stat`：`service.py +30/−2`、`copy.py +7/−3`（=+37/−5）；未跟踪只有 `test_t207_fix_conflict_r2.py` 与 `T207-FIX-CONFLICT-R2/` |
| 未改 `evaluation/**`、冻结题集/fixtures、评分器/计划/契约/门槛 | 是（本包） | 开工时 `git diff --name-only` 无 `backend/src/mktkb/evaluation`、无 `fixtures`、无 `backend/tests`（除新增）；05:56Z 起 LIVECAP 才把 `evaluation/*` 写进工作区（见 §1） |
| 未改账本/预算/GO | 是 | `git status --porcelain -- docs/evidence` 为空；`P2-LIVE-GO.json` 未修改；PM 下的 R4 计划/GO 草稿均为 **R4PREP 的未跟踪新增**（非本包） |
| 无 skip/xfail | 是 | 新测试与改动的 grep 均为空；3/3 用例实际执行 |
| 无 commit | 是 | HEAD 仍 `489aadd`，`git diff --cached` 为空 |
| 零真实出站 | 是 | R4 装配：`provider_calls/network_stats` `outbound_attempts=0`、`rag_provider_posts=0`、`post_counters={attempts:{},outcomes:{}}`；54 例装配：独立 socket 闸门 `external_attempts=[]`（前后两次）；新测试在独立 socket 闸门下 `external_attempts=[]` |
| 模型调用数不变 | 是 | C05/C06/N08 每轮 `model_calls_this_turn=0`（前后一致） |

### 2.2 判定 2：通用渲染（非硬编码）—— PASS

实现：`service.py:766-792` 新增 `MAX_DISCLOSED_CONFLICT_VALUES=8` 与 `_conflict_values_text(conflicts)`；`service.py:2355-2370` 冲突分支改为 `copy_module.legacy_conflict_text(_conflict_values_text(conflicts))`（空冲突仍在 `:2357` 转 clarification，不会产生空取值文案）；`copy.py:778-787` 新文案。

| 检查 | 结果 | 证据 |
|---|---|---|
| 字段名/取值只来自冲突视图 | 是 | 函数体只遍历 `conflict.field` 与 `conflict.entries[].value`，无题面/实体/文档名参数 |
| 无 C05/C06 特判 | 是 | 改动区不含 `C05/C06`、`V01/D01`、取值常量；grep 到的 `B区1号货架第二层`/`城东店` 只出现在 HEAD 既有注释里（`service.py:936/1136/1278/1373/1434`，diff 未触及） |
| 空白折叠 + 同值去重 | 是 | 探针：`("A  区","A 区"," A\t区 ")` → `位置：[A 区]`（`nonhardcoding-probe.out.txt`） |
| 每字段 ≤8 条、超出写「等」 | 是 | 探针：8 条无「等」；9/12 条 → 前 8 条 + ` 等]`；测试 `test_t207_fix_conflict_r2.py:182-199` |
| 多字段渲染 | 是 | `位置：[甲、乙]；电话：[1、2]` |
| 脱敏面 | 是 | 文本只含字段名与原值，不含 `source_id`/文档名/UUID（见 `independent-after.json` 的 C05/C06 text） |
| 非冲突分支逐字不变 | 是 | 代码 diff 仅冲突分支；54 例中 52 例 `text` 与 HEAD 逐字相同（含 N08、C01–C04、Q01–Q40） |

### 2.3 判定 3：冻结评分 C05/C06 fail→pass、N08 不变 —— PASS

用**冻结公开题集** `fixtures/acceptance/questions.json`（`load_acceptance_cases()`，C05 期望 `conflict` + 两值 + 来源 D01/V01、禁用 V03；C06 同形）走 `score_public_case`；R4 灌库终态（V03→D01→V04 不发布→V01→D02→V02）按 live 形状（每轮 1 次 query embedding，超出即拒）提问。

| 例 | status 前→后 | value_hit 前→后 | source_hit | kind_correct | value_no_fabricated | source_forbidden | 模型调用 |
|---|---|---|---|---|---|---|---|
| N08 | pass → pass | skipped → skipped（should_refuse） | skipped | pass | skipped | skipped | 0 |
| C05 | **fail → pass** | **fail → pass** | pass（保持） | pass（保持） | pass（保持） | pass（保持） | 0 |
| C06 | **fail → pass** | **fail → pass** | pass（保持） | pass（保持） | pass（保持） | pass（保持） | 0 |

- 机制核对：`value_hit` 只读 `outcome.text`（`scorers.py:632-649`）；`score_public_case` 把产品行归一后调 `score_case`（`p2_scoring.py:758,870-900`）。修复前 `text` 只写字段名，故必 fail；修复后文本含两值 → pass。
- 负载不变：C05/C06 `conflicts` 的 field/取值/顺序/条目数逐字一致（C05 `位置` 两值、C06 `电话` 两值）；`sources` 的文档名/版本/状态/locator 逐字一致（C05 = D01 v2 + V01 v1；C06 = D02 v1 + V02 v1）。`source_id` 是逐库 UUID，跨独立实例天然不同，只能做结构比较（本验收按结构比较）。
- 文本前后：
  - C05 前 `资料中对位置记录了多个有效值，请以下列来源为准核对。系统不会按上传时间自动裁决；…` → 后 `资料中存在多个有效值：位置：[B区1号货架第二层、D区暂存柜]。请以下列来源为准核对。…`
  - C06 前同形（电话）→ 后 `资料中存在多个有效值：电话：[010-00000001、010-00000099]。…`
  - N08 前后文本逐字相同（照片类拒答文案未受影响）。

### 2.4 判定 4：54 例差分仅 {C05,C06} —— PASS

Q01–Q40 / N01–N08 / C01–C06，B0 装配（C05/C06 各自恢复快照后发布 V01/V02），前后各 54 例：

- 变更集合 = **{C05, C06}**：`text`、`strict_status`（fail→pass）、`strict_problems`（由「缺少内容」清空）。
- 其余 **52 例**：kind/text/sources/conflicts/candidates/status/strict_status/problems 全部逐字一致。
- 口径总量：status 54 pass（前后同）；strict 50 pass → 52 pass（C01/C02 的既有 any-of 缺口前后一致，不属本包）。
- 开发侧 `impact-54-before-after.json` 与本次独立结果可互证：after 文本 54/54、before 文本 54/54 完全一致，status/strict 无分歧。开发侧只记到 `text/strict_status`，本次更细地记到 `strict_problems`（同一因果，不是额外变更）。

### 2.5 判定 5：回归 —— PASS

| 套件 | 结果 |
|---|---|
| `test_t207_fix_conflict.py` / `_r1` / `_r2` + `test_chat` + `test_conversations` + `test_p1_t106_copy` + `test_p2_public_controls` + `test_t09_d2_text_facts` | **138 passed**（54.8s） |
| `test_t09_mutation` + `test_t09_b0_baseline` + `test_p0_acceptance` | **27 passed**（34.3s） |
| `test_p2_public_cases` | **8 passed**（0.14s） |
| RAG/observability 冲突路径（`observability/test_paths_e2e`+`test_rag_spans`+`rag/test_phrasings_and_conflict`） | **41 passed**（10.6s） |
| 附加（同路径回归）`rag/test_r1_regressions` | **10 passed**（并入上一行 51 passed 跑法） |

全部 exit 0，无 failed/error/skip；未观察到既有 s2h 漂移（本次未跑全量，按要求只跑相关套件）。以上复跑均在 05:56:10Z 前完成（早于 LIVECAP 首次写入 05:56:23Z），且这些套件走 Mock、不导入 live 装配。

### 2.6 判定 6：限制与风险 —— PASS（如实披露）

1. **每字段 ≤8 条披露**：第 9+ 条不进 text，只写「等」。对 R4 三例无影响（C05/C06 各 2 值）；若未来出现「期望值恰在第 9+ 条」的冲突题，`value_hit` 仍会 fail（与改动前同）。冻结公开集只有 C05/C06 两条冲突题，无现存受影响用例。残余风险：H2 holdout 的冲突题若期望值超过 8 条会复现该 fail——需要在 H2 侧知悉，不是本包可消除的。
2. **冲突取值仍不受候选窗口约束**（经理已就 MEDIUM-2 决策）：修复只把既有 `conflicts.entries` 写进 text，不新增取值来源；因此文本可能包含候选窗口外的「同实体可见正文」值。对 R4：`citation_required` 只判 `kind=answer`（`gate.py:1658-1659` 对非 answer 结局直接跳过），conflict 不触发 gate；两来源仍是 D01/V01、D02/V02，`source_forbidden` 仍 pass。残余风险：H2 聚合/审计需要知道「conflict 文本不是候选窗口子集」。
3. **`value_forbidden` 面**：渲染会披露该字段全部（≤8）取值；若某题把冲突值之一列为 forbidden，会因此触发 `value_forbidden` fail。冻结 C05/C06 均无 `forbidden_values`，不存在该冲突；H2 holdout 未知，属口径观察项。
4. **覆盖范围**：本次未跑全量（按任务书只跑相关套件）；R4 为 Mock + 每轮 1 次 query embedding 的离线形状，不是真实调用。
5. **测试卫生（非阻断）**：新测试未像 `_r1` 那样挂 `t09_network_guard`；本次用外部 socket 闸门独立证明零出站。建议后续给该文件补 `pytestmark = pytest.mark.usefixtures("t09_network_guard")`。
6. **测试局部适配（非阻断）**：C05 单测把测试内历史版文档名 `V03_*` 显式映射到 `D01` 槽（`test_t207_fix_conflict_r2.py:153-157`），这是测试装配的命名事实，不是产品特判；R4 真实态（活跃文档名为 `D01_*`）由本次 R4 装配独立覆盖且 pass。

## 3 与开发交付的对照

| 开发声明 | 独立复核 |
|---|---|
| C05/C06 fail→pass（value_hit 转 pass，source_hit/kind_correct 保持 pass） | 一致（§2.3，独立重跑） |
| N08 逐字不变 | 一致（文本 sha256 与 checks 全同） |
| 54 例差分仅 {C05,C06} | 一致（52 例逐字同；C05/C06 text/strict 变） |
| conflicts/sources 不变、模型调用 0 | 一致（结构比较；0 调用） |
| 零出站 | 一致（provider 计数 0 + post_counters 空 + socket 闸门 0） |
| 回归 138/27/8/41 | 一致（另加 10 例同路径回归） |
| 产品 +37/−5、evidence 3 个 | 一致 |
| 开发侧 `evidence/verify.py` | 未直接重跑；其输出可由本次独立脚本逐值复核（before/after 文本 54/54 一致、评分 check 全同、变更集合相同），实现不同但结论重合 |

## 4 复现命令（仓库根，零真实调用）

```powershell
# 1) 冻结评分（after / before；before 源为 HEAD 副本，仅还原 service.py/copy.py）
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207-FIX-CONFLICT-R2\evidence\verify\independent_cases.py --src=backend/src --out=...\independent-after.json
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207-FIX-CONFLICT-R2\evidence\verify\independent_cases.py --src=<HEAD副本>\backend\src --out=...\independent-before.json
# 2) 54 例差分
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207-FIX-CONFLICT-R2\evidence\verify\independent_impact.py --src=backend/src --out=...\impact-after.json
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207-FIX-CONFLICT-R2\evidence\verify\independent_impact.py --src=<HEAD副本>\backend\src --out=...\impact-before.json
# 3) 回归（见 §2.5 的套件列表；均 -q -p no:cacheprovider）
```

> 复现 before 侧时，HEAD 副本还需包含 `fixtures/acceptance`、`backend/migrations`、`backend/alembic.ini`（`load_acceptance_cases` 与 alembic 需要），这些均为仓库内未修改文件。

## 5 证据文件（本验收自产，均在 `evidence/verify/`）

| 文件 | 大小 | sha256 前 16 |
|---|---|---|
| `independent-before.json` | 20,968 | `b0831afdc95fadf0` |
| `independent-after.json` | 20,890 | `2c547545e3778f16` |
| `impact-before.json` | 125,255 | `d084e7157ca1e45f` |
| `impact-after.json` | 125,071 | `ef5433f557581b7f` |
| `summary.json`（结构化对照汇总） | 10,901 | `01abb4c826b3f3bb` |
| `independent_cases.py` / `independent_impact.py` | 9,655 / 8,130 | `a5de2b1d246fa664` / `3bf8c08ccc563797` |
| `nonhardcoding_probe.py` / `nonhardcoding-probe.out.txt` | 1,801 / 958 | `f8db5f70c16af2d9` / `710011f741f04a47` |

## 6 最终建议

- **接收**（阻断 0）。本次未发现需要返工的功能/范围/证据问题。
- **提交白名单（必须）**：`backend/src/mktkb/conversations/service.py`、`backend/src/mktkb/copy.py`、`backend/tests/integration/test_t207_fix_conflict_r2.py`、`docs/reports/OBS-EVAL/P2/T207-FIX-CONFLICT-R2/**`。
- **不得随本包提交（并行包 FIX-LIVECAP 的现场）**：`backend/src/mktkb/evaluation/p2_live.py`（+123 行）、`backend/src/mktkb/evaluation/product_adapter.py`（+25 行）、`backend/tests/evaluation/test_p2_live_request_ceiling.py`、仓库根 `.p2cap_probe.py`/`.p2cap_probe2.py`。R4PREP 的 PM 文档与 R4 计划/GO 草稿同样不属本包。
- **建议（非阻断，按优先级）**：
  1. R4 真实执行时，把「C05/C06 的消息 text 同时包含两个原值」作为一条显式观察断言（本包已把该行为写成确定性文案，live 应复现；但 live 跑一次的价值在于确认冲突路径仍取到两值）。
  2. 新测试补挂 `t09_network_guard`（与 `_r1` 对齐），让「零出站」成为该文件的机器断言。
  3. 若 H2 holdout 含「期望值 >8 条」或「冲突值之一被列为 forbidden」的题，预先确认口径（见 §2.6-1/3）。
- 按令**不 commit**；本验收只写 `review.md` 与 `evidence/verify/`。
