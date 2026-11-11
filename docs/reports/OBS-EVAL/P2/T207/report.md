# P2-T207 准备交付（report）

- 角色：T207 准备助手（全新上下文）。真实调用 **0**；未读 `.env`/H1/H2；未联网；未写真实 budget/GO/账本；
  未改代码/测试/冻结夹具；未 commit/push。分支 `codex/p2-e2e`，HEAD `9a740ce`（未变）。
- 现场（只读复核一致）：账本 `6b053520…`（1,050,298 B / 1095 行 / 547 reserved / 547 result），预算 `79b21700…`（limit 40 / P2-LIVE 20），
  历史前缀 `f4710b18…`；P2 阶段已占 `0.5713583`（ocr 0.5 + answer_retrieval 0.0713583），**余 19.4286417 元 / 453 请求**。

## 1 结论（一句话）

计划、导入配方、成本核算与候选 GO 的算术**全部可离线复算**（254 请求 / worst-case 8.127376 元 / 12 页 OCR 5.65），
但**整套矩阵今天还不能跑**：3 处必须由经理决定的前置（请求硬顶、GO 重签、用例与 H2 计划生成器），
外加 6 处**矩阵可执行性缺口**（F1/F2/F4/F5/F6/F7 中的 4 条 BLOCKER）。这不是额度问题，是接线与治理问题。

## 2 交付物

| 文件 | 说明 |
|---|---|
| `PM/T207-plan-v0_1.json` | 公开矩阵 `P2RunPlan`：233 项 / 55 个真实回合（`plan.turn_count=60` 还含 INGEST 与 4 个 OCR 文档码的 turn=1 伪回合）/ 12 页 OCR / **254 请求** / `max_requests=1000`；`plan_sha256=d788a83b3b27ff4e4aa43cb89b2230012d4f89eeecd232e2ac489e398cb3a947` |
| `PM/T207-plan-h2-v0_1.template.json` | H2 **模板**（不是 P2RunPlan）：36 回合 ×4 项 + 1 个 ingest 项；case_id 只能由封存进程生成 |
| `PM/T207-GO.CANDIDATE-DRAFT.json` | 公开矩阵候选 GO（DRAFT，`production_ready=false`）：绑 plan sha、账本前缀、13 天、中心 8.5/6.5/3/2、`max_requests=1000`、`max_request_cny=0.5` |
| `PM/T207-GO-h2.CANDIDATE-DRAFT.json` | H2 候选 GO（DRAFT；`plan_sha256` 为全零占位 ⇒ 授权链必然失败，只作形状/上限预审） |
| `PM/T207-import-recipe.md` + `.json` | 42 步导入配方（V03→D01→V04 同槽三版：历史/当前/未生效）、逐 step 状态断言、失败判定、chunk/批 清单、与 corpus V01–V08 的关系 |
| `PM/T207-cost-and-quota.md` | 逐 operation/中心/案例/页/批的请求与 worst-case；R1/R2/R3 拆分；中心重排证明；H2 可行域；拟提 `HARD_MAX_REQUESTS=1600` 的实算 |
| `PM/T207-fix-scope.md` | 供 T207-FIX 的最小修复清单（A–G 七组，逐项含现象/复现/根因行号/允许改文件/禁止项/验证/回归风险） |
| `PM/T207-runbook.md` | 执行手册：只读检查、签发、三次运行命令（与 `cli.py` 参数逐字对齐）、停止规则、产物核对、归因表、H2 注入与审计、部分重跑、回滚 |
| `evidence/` | `estimate.py`（chunk/批 + OCR 三档 + corpus 包络）、`build-plan.py`（确定性造计划/GO）、`validate-plan.py`（预检/授权/负例）、三份输出 JSON/TXT |

## 3 计划与成本要点

- 55 回合 = B0 40 + N8 + C6 + U01（任务书要求的「计划绑定的有限真实更新 smoke」）；每回合 4 次底层请求（query_embedding/rerank/query_expansion/answer）。
- 灌库 22 批 = 11（fixtures 非 OCR，实测）+ 11（12 页 OCR，按每页 ≤2,700 字上限：7+2+1+1）。
- 拆三次运行（同一计划、同一 GO）：R1 230 请求 / 7.994704 元；R2 19 / 0.545024；R3 6 / 0.04832 → 累计 **255 / 8.588048**。
- 中心必须重排：ocr 已占 0.5 + 本次 5.65 = **6.15 > 原 6.0** → `8.5/6.5/3/2 = 20`（`budget.json` **不用改**）。
- 余量对照：255 ≤ 453 ✓、8.588 ≤ 19.4286 ✓；但 R2/R3 的再次授权在 1000 硬顶下不可行（`plan.total_requests ≤ max_requests − 已用`）。

## 4 缺口（BLOCKER 单列）

| # | 缺口 | 级别 | 最小方案 |
|---|---|---|---|
| F1 | H2 逐 case 计划项 vs 隐藏 case_id（`p2_runner.py:1073-1083`、`p2_live.py:241-245`） | **BLOCKER** | 封存进程内生成计划（只落 `plan_sha256` 进仓库），新增 ~100 行生成器 |
| F2 | H2 语料包未声明（全仓只有任务书一句） | **BLOCKER（数据保管面）** | 保管方给 `corpus code 列表 + 是否含 OCR 页 + 导入顺序`（repo-safe） |
| F4 | U 行的 L/R 与 `execution_mode_mixed`（`p2_scoring.py:1178-1182`）；U07–U09 无 question、U10 需重复 id | **BLOCKER（口径）** | 逐题 `evidence_basis` + `allow_mixed_basis`（suite 内一致），U verdict 取既有 `test_t09_mutation.py` |
| F5 | run 产物 → 评分/门禁的驱动不存在（src 里只有定义、无调用者） | **BLOCKER** | 新增 `p2_score_run.py` + CLI `p2-score` |
| F3 | N8/C6 只有 `questions.json`，不是 CaseSpec | 高 | 只读转换器 → `CaseSpec`；C05/C06 用独立 run 的 ingest 计划表达 |
| F6 | gate 链**不能**产出 `release_ready` | 设计如此 | `gate_v0_3` unapproved → `gate_config_unapproved`（unknown）；放行权在 T209 |
| F7 | 多 run 共用一扇门：`gate_reserved` 累计 vs 本 run 期望 → `attempt_accounting_mismatch` | 高 | 每次 run 新开门 + 计划 `max_requests` 留重授权余量 |

## 5 请求硬顶（拟提）

`547(已用) + 255(公开) + 144(H2 回合) + ≤68(H2 灌库) + 160(T208 judge≈3 元) + 107(T900 independent≈2 元) = 1,281`，
+20% 余量 → **建议 1,600**（主人预授权 ≤2000 内）。配套：公开计划提顶后重发 `max_requests=1200`、H2 1100、judge 1200、independent 1400；
同步改 `live_authorization.py:94`（`test_p2_authorization.py:481` 的不变式）与契约 §1.3/§3 文本。**到值即停**。

## 6 风险 / 未做

1. **R1 今天只能授权一次**（计划 `max_requests=1000`）；R2/R3/H2 需提顶后重发计划+重签 GO（sha 会变）。
2. 固定路径 `P2-LIVE-GO.json` 仍在（绑 T206 pilot 计划 `02725aa7…`）：直接换计划会 `go_plan_sha256_mismatch` 拒；必须重签。
3. OCR 文本长度是**假设**（每页 ≤2,700 字；转录锚定只要 4 批）：超限在发送前 `attempt_quota_exhausted` 停（fail-closed，不超支），但会烧掉已付的 OCR 页费。
4. H2 若含 12 页 OCR：阶段会到 21.18 > 20 → 必须排除 OCR 页或提阶段额（需预算修订）。
5. 未做：真实调用/OCR/H2/Ragas/全仓测试；未跑 `p2-run`（含 dry-run）；未改任何产品代码；未评估质量。
6. `output_valid` 疑点：`build_chat_evidence` 未传该字段（默认 False，`settlement_policy.py:479/713`）→ 可能让 live chat 结算退回保守留账；
   已列入 fix-scope §C，需 T207-FIX 用离线用例确证。

## 7 复跑入口（零真实调用）

```powershell
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\estimate.py --corpus
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\build-plan.py
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\validate-plan.py
```

预期：`preflight_real_snapshot.ok=true`（`requests_remaining=453`）、`authorize_candidate.production_ready=false`、
10 条负例全部按稳定码拒绝、`read_only_proof.unchanged=true`、`go_path_exists_after=true`（未创建/未修改）。

## 8 T207-FIX-A 修订（2026-11-11）

- 计划按经理决定重发为 `max_requests=1200`，新 `plan_sha256=0b4e55a4cd3a46f968e89fe495ffca3c6931c8f49f1f258a3dd753f83e24a194`（233 项 / 254 请求不变）；
  候选 GO 同步改为 `max_requests=1200`（DRAFT 仍不可用）。
- 请求拆分改为 R1=242 / R2=15 / R3=6（累计 **263**，worst **8.145808**）；Q01 只在 R1；R2=U01+C05、R3=C06。
- **顺序改为 R3 → R2 → R1**：计划含 12 页 OCR（5.65），R1 跑完后 ocr 中心只剩 0.35，再授权必然
  `center_budget_insufficient:ocr`（请求窗口仍够）。反证见 `evidence/validate-plan-out.txt` 的 `reorder_control`。
- 已交付驱动/生成器：`--ingest-plan`（版本槽）、`cases/{R1,R2,R3}.jsonl`、`p2-h2-plan`、`p2-score`、`p2-matrix`、
  `p2-u-controls`、`tools/p2_live_execute.py`；详见 `docs/reports/OBS-EVAL/P2/T207-FIX-A/report.md`。

## 9 R4 定点重测准备（P2-T207-R4PREP，2026-11-11）

- 角色/边界：全新上下文的准备助手；**零真实调用**（ProductEvalAdapter Mock 路径）、零网络、零 commit；
  未改源码/测试/fixtures/账本/预算/GO 固定路径；未读 `.env`/H1/H2。
- **HEAD**：R4PREP 交付时为 **`489aadd`**（已含 FIX-CONFLICT-R1）。旧文写 `0260b7b` 是开工前的 HEAD，已过期。
  **后续已提交**：`24f9cde`（FIX-CONFLICT-R2：冲突回答 text 披露双方取值）、`1dca413`（FIX-LIVECAP：live 单请求上限）。
  本次文档收口（T207-R4PREP-R1）的基线 = **`1dca413`**。
- 现场（只读复核，前后 SHA 一致）：账本 `05b54d06…`（1,354,211 B / 1383 行 / **691 reserved / 691 result**）、
  预算 `79b21700…`；阶段已占 **6.5409604** 元、中心 `answer_retrieval 0.3909604 / ocr 6.15`。
  （以上是 **R4 前快照**；任何真实 run 都会推进账本与占用，执行前按 runbook §1.1/§1.4 重算。）

### 9.1 交付物

| 文件 | 说明 |
|---|---|
| `cases/R4.jsonl` | N08 → C05 → C06 三个 CaseSpec（**既有只读转换器** `p2_public_cases.load_acceptance_cases(ids=…)` 生成，字段逐项回溯冻结题集），sha256 `c04b67c6…`；`document-codes.json` **沿用**（V03/V04 是 D01 槽的版本、产品文档名仍是 `D01_物品位置表.xlsx`，无需新增映射） |
| `PM/T207-ingest-plan-R4.json` | `p2-ingest-plan/v0.1`，6 步**同一库**：V03 建槽 → D01 → V04（**不发布**）→ V01 → D02 → V02；sha256 `07c2694b…` |
| `PM/T207-plan-R4-v0_1.json` | `P2RunPlan`：13 项 / 3 回合 ×4 + 1 个 `index_embedding`(requests=B_r4) / **18 请求** / **无 OCR 项** / `max_requests=760` / 中心 8.5-6.5-3-2；`plan_sha256=00b9fdefd8cc8220178745f0806486eaf3a70818be4068dd0fd2307303b5d2b9` |
| `PM/T207-GO-R4.CANDIDATE-DRAFT.json` | DRAFT 候选（`document=P2-LIVE-GO` + authorization 里写死 NOT USABLE）：绑 plan_sha、账本历史前缀 `f4710b18…`、五操作（无 ocr）、`max_requests=760`、中心同值、13 天（`2026-11-11T12:30Z+08` → `2026-11-24T12:30Z+08`） |
| `evidence/build-r4.py` + `build-r4-out.txt` | 三段构造（inputs / plan / go），B 从实测状态文件读入，不估 |
| `evidence/r4-ingest-probe.py` + `r4-ingest-state.json` | 灌库终态 + B_r4 实测 + 三例两种运行形状的逐题观测与**冻结评分器**判定（评分结论为**修复前**读数，见 §9.3） |
| `evidence/validate-r4.py` + `validate-r4-out.txt` | 计划/候选 GO 的离线校验：预检、授权、12 条负例、只读证明 |
| `evidence/r4-dryrun-out.json` | `p2-run` **dry_run**（Mock、零发送）把同一计划/case/灌库跑通：3/3 例执行、`requests_sent=0`、`production_ready=false`、灌库 revision 1→2→(V04 不发布不加 revision)→3→4→5 |

### 9.2 关键读数

- **灌库终态（实测）**：4 份资料；D01 槽 3 版（v1=V03 `superseded`、v2=D01 `published`+**active**、
  v3=V04 `review_required`+未发布）；V01 / D02 / V02 各 v1 `published` 且 active（D02 与 V02 是两份独立资料）；
  `product_revision=5`；索引 4 份 / 23 单元 / 15 chunk。九条断言全 hold（`state_checks.all_hold=true`）。
- **逐 step 预期状态（顺序即语义；实测回执见 `r4-ingest-state.json` 的 `receipts`/`documents`）**：
  `p2-ingest-plan/v0.1` 的 source 只接受 `path/name/document_ref/expected_active_version_id/publish`
  （`product_adapter.py:381-425` 未知字段一律拒），所以**断言不能写进计划文件**，只能落在证据里：

  | # | 上传 | 名/引用 | publish | 预期（→ 实测） |
  |---|---|---|---|---|
  | 1 | V03 历史V1 | `name=D01_物品位置表.xlsx`（建槽） | 是 | 新资料 v1 published+active（9 单元） |
  | 2 | D01 | `document_ref=D01_物品位置表.xlsx` → v2 | 是 | v1→superseded，v2 published+**active**（9 单元） |
  | 3 | V04 新版V3 | `document_ref` → v3 | **否** | v3 `review_required`、`published_at=null`、**不 active**；active 仍是 v2 |
  | 4 | V01 临时位置通知 | 独立资料 | 是 | 新资料 v1 published+active（5 单元）→ 与 D01 槽**双有效**（C05 的冲突来源） |
  | 5 | D02 合作店家信息 | 独立资料 | 是 | 新资料 v1 published+active（4 单元） |
  | 6 | V02 联系方式变更通知 | 独立资料 | 是 | 新资料 v1 published+active（5 单元）→ 与 D02 **双有效**（C06 的冲突来源） |

- **B_r4 = 6 批**（产品 chunker + `embedding_batch_size=5` 口径，离线实测；上界口径 9）。
  推导：逐次 `embed()` 的待嵌入文本数 = 9 / 1 / 1 /（V04 不发布，不同步）/ 4 / 1 ⇒ `ceil` 求和 = **6**。
  方法学自证：同一测法对 R2 计划给 **4**、R3 计划给 **2**，与 live 账本这两个 run 的 `ingest-index-embedding`
  预留数**逐值相等** ⇒ 6 可信。与 R2/R3 的异同：同（版本槽 3 步 + 不发布语义）；异（R4 把 R2 的 4 步与
  R3 的 2 步**合并成一库**，所以 B_r4 = 4 + 2，一次灌库同时满足 C05 与 C06 两个冲突）。
  取舍（如实）：计划写**实测值 6**而不是上界 9 —— 多出 1 个 POST 就会在发送前 `attempt_quota_exhausted`
  （零花费，但整轮 run 作废）；即"精确但无安全余量"。
- **计划算术**：18 请求 / worst-case **0.144960** 元 / `reserve_peak=0.018688`（≤ `max_request_cny=0.5`）/
  成功估价 0.0297 元 / `page_count=0`。请求窗口 `18 ≤ 760 − 691 = 69` ✓；预检 `ok=true`
  （`stage_remaining=13.4590396`、`requests_remaining=69`、`center_remaining.answer_retrieval=8.1090396`）。
- **候选 GO 授权链**：`authorize_p2` 通过且 `production_ready=false`（GO 来自内存，非固定路径）；
  12 条负例全部按稳定码拒（覆盖 11 个稳定码，见下）：`go_operation_unauthorized` / `go_max_requests_below_plan` /
  `go_plan_sha256_mismatch` / `go_plan_id_mismatch` / `go_cost_center_below_plan` /
  `go_max_request_cny_below_plan` / `go_expired` / `request_budget_insufficient` /
  `center_budget_exceeded` / `request_cap_over_hard_limit` / `plan_requests_over_cap`）。
  - **12 条负例 = 11 个稳定码**：`go_max_requests_below_plan` 出现两次（打 600 与打 10，同一谓词）。
  - **case 名 ≠ 稳定码**：`requests_over_remaining` 命中的码是 `request_budget_insufficient`；
    `center_below_plan_need` 实际在**计划构造期**就以 `center_budget_exceeded` 拒，**没有**覆盖 preflight 的
    中心窗口码 `center_budget_insufficient:<center>`。R4PREP 独立验收另补 `preflight_center_window_insufficient`
    与 GO 账本绑定 `go_ledger_binding_mismatch` 两条谓词，均通过（`T207-R4PREP/review.md` §4）。
  - **forbidden 两条是"不可命中"**：`C05.forbidden_sources=[V03]`、`C06.forbidden_sources=[V06]`，而
    `cases/document-codes.json` 只按**产品文档名**映射（不含版本号）：V03 以 `name=D01_物品位置表.xlsx`
    入槽、产品侧文档名仍是 D01；V06 不在 R4 灌库包里。⇒ 这两条 `source_forbidden` 判 pass 只说明"没有误报"，
    **不证明检查有效**（R2/C05、R3/C06 同形，属既有口径，不是 R4 引入）。
- **只读证明**：账本/预算 SHA 与字节数前后逐值相同；固定路径 `P2-LIVE-GO.json` 未被创建/修改。

- **驱动接受性（dry_run 实测）**：`p2-run`（Mock，零发送，产物写仓库外）跑同一计划/case/灌库 →
  `status=succeeded`、`cases 3/3 executed`、`requests.real_requests=0`、`gate.real_sends_allowed=false`、
  `production_ready=false`、`plan_sha256` 与文件逐值相同。⇒ 文件本身能被真实驱动接受。
  （旧文写"挡住 R4 的不是接线"，**不成立**：当时确有接线阻断 F-1；F-1 已由 FIX-LIVECAP 修掉，
  见 §9.5。证据：`evidence/r4-dryrun-out.json`。）

### 9.3 结论（R4PREP-R1 更正经：历史读数 + 修复后已可达）

**历史读数（HEAD `489aadd`，未含 FIX-CONFLICT-R2）：当时不可达** —— 不是召回形状问题，是**观测口径**问题：

- 三例在**同一 KB** 里都能被正确识别：N08 `not_found`（含"范围外/无法"，0 次模型调用）；
  C05 `conflict` + 来源 D01/V01；C06 `conflict` + 来源 D02/V02；三者均 0 次模型调用（门控只拒第 2 次 query embedding）。
- 但 C05/C06 的**冲突值只在 API 的 `conflicts` 负载里**，消息 `text` 是
  「资料中对位置/电话记录了多个有效值，请以下列来源为准核对…」；而冻结评分器的 `value_hit` 只读 `outcome.text`
  （`scorers.py:632`；adapter 只取 `payload["text"]`，`product_adapter.py:2156`（`489aadd` 时为 2137））。
- 实测（两种形状都 fail）：`scoring_gated` = N08 `pass` / C05 `fail` / C06 `fail`，失败项都是 `value_hit`
  （`kind_correct`、`source_hit`、`source_forbidden`、`value_no_fabricated` 全 pass）；`scoring_ungated` 同结论
  ⇒ 与"单次召回形状"无关，改门控也不会让它过。当时的逐题读数见 §9.1 的 `r4-ingest-state.json`（**修复前读数**，不要当现状引用）。

**FIX-CONFLICT-R2（`24f9cde`，产品侧 1 处文案）落地后：已闭环、目标可达（Mock 证据）**。冲突轮文本改为通用披露
「字段：[值1、值2]」（值本就来自 `conflicts`；仍 0 次模型调用，`conflicts`/`sources` 结构不变）。
冻结 CaseSpec 下 **N08 `pass` / C05 `pass` / C06 `pass`**（`value_hit fail → pass`），
54 例差分只剩 {C05,C06} 的文本与 strict 判定；独立验收判**接收（阻断 0）**
（`T207-FIX-CONFLICT-R2/report.md` §4、`review.md` §0/§2.3）。

⇒ **R4 计划 / cases / 灌库计划 / 候选 GO 全部不变、无需改动**：`plan_sha256` 是计划内容哈希，文案改动不改请求形状
（冲突轮 0 次 chat、1 次 rerank、1 次 query_embedding），GO 绑的 `plan_id/plan_sha256/operations/cost_centers` 都不变。
裁定见 §9.5（F-3）。

**仍未覆盖（如实）**：修复后可达性的直接证据**只有 Mock**；live 上还从未观测到 `conflict`
（R2/R3 两次 live 的 `kind_correct` 都是 `expected=conflict, actual=answer`，且早于 `0260b7b` 与 R2 的文案修复）。
⇒ live 首次验证即 R4 本身，仍存在"产品仍回 `answer`"的可能；出现即按 runbook §4/§6 停并归因。

### 9.4 复跑入口（零真实调用）

```powershell
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\build-r4.py --step inputs
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\r4-ingest-probe.py --out docs\reports\OBS-EVAL\P2\T207\evidence\r4-ingest-state.json
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\build-r4.py --step plan
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\build-r4.py --step go
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\validate-r4.py

# 驱动接受性（Mock、零发送；--out 必须写仓库外，跑完即删）
.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-run ^
  --plan "docs\reports\OBS-EVAL\P2\T207\PM\T207-plan-R4-v0_1.json" ^
  --out "<仓库外目录>\R4-dryrun" ^
  --cases "docs\reports\OBS-EVAL\P2\T207\cases\R4.jsonl" ^
  --ingest-plan "docs\reports\OBS-EVAL\P2\T207\PM\T207-ingest-plan-R4.json" ^
  --run-id p2-t207-r4-dryrun-01 ^
  --dataset-version p2-t207-r4-20261111-v0.1 --label-version p2-t207-labels-20261111-v0.1
```

预期：`batches_B=6`（`crosscheck_r2_r3.matches_live` 全 true）、`state_checks.all_hold=true`、
`preflight_real_snapshot.ok=true`、`authorize_candidate.production_ready=false`、12 条负例（11 个稳定码）全拒、
`read_only_proof.unchanged=true`。

### 9.5 R4PREP 验收项闭环摘要（T207-R4PREP-R1 文档收口）

| 验收项 | 原判定 | 现状 | 依据 |
|---|---|---|---|
| F-1 live 发不出 embedding POST（无 OCR 计划） | BLOCKER | **已闭环**（产品侧修） | `T207-FIX-LIVECAP`（`1dca413`）+ 其 `review.md`「接收（阻断 0）」 |
| F-2 §9.3「目标不可达」过期 | FAIL | **已闭环**（§9.3 改写为历史读数 + 修复后可达） | `T207-FIX-CONFLICT-R2`（`24f9cde`）+ 其 `report.md` §4 / `review.md` §2.3 |
| F-3 runbook §9 与 §9.3 重签口径冲突 | FAIL | **已裁定并写死** | 经理裁定（下条）+ runbook §9「重签口径」 |
| F-4 HEAD 写错 | FAIL | **已闭环** | §9 首部（HEAD 更正）：交付时 `489aadd`、代码基线 `1dca413`；其后为文档/执行产物提交（不改代码） |
| F-5 §9.2「不是接线」不成立 | FAIL | **已闭环** | §9.2 改口径；F-1 已修 |
| F-6 口径小项（12 负例/forbidden/6 vs 9/case 名） | 建议 | **已补** | §9.2 三条子项 + B_r4 取舍 |

- **F-3 经理裁定（写死，runbook §9 同文）**：**只改产品输出文本、不改计划内容时，`plan_sha` 不变，R4 不重签计划**；
  GO 仍按流程签发（GO 绑定 `plan_sha`）。判据是「计划项 / 请求形状 / 操作集合 / 证据链有没有变」，没变就不算
  pipeline 变更；改到这些才回到"新计划 + 新 GO"。FIX-CONFLICT-R2 与 FIX-LIVECAP 都属前者：R4 计划
  `plan_sha256=00b9fdef…`（13 项 / 18 请求 / `max_requests=760`）、`cases/R4.jsonl`、灌库计划、候选 GO 逐字未变。
- **前置（执行侧，已写进 runbook §3.2/§9）**：R4/H2 都是 `page_count=0` 计划 ⇒ live effective 单请求上限 = 0.04096，
  **GO 的 `max_request_cny` 必须 ≥ 0.04096**（候选 0.5 满足）；不足则装配期 `live_request_ceiling_insufficient`
  fail-closed（零发送/零预留/零降级/无产物）。
- **归因（F-12）**：`PM/T207-PM-decisions-01.md` 在经理侧已追加 **§11/§12**（执行阶段与 R4/H2 执行前决定），
  属**经理侧写入**、不是 R4PREP/R2 收口包的交付面；工作区 git 会把该 tracked 文件显示为已改，别误记成本包改动。
- 本收口包：只改文档、**零真实调用、零网络、零 commit**；未重跑计划校验（`P2RunPlan` 内容未变），
  只读引用既有证据（`T207-R4PREP/review.md`、R2/LIVECAP 报告与验收）。
