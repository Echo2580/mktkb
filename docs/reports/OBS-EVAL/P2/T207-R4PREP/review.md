# P2-T207-R4PREP 独立验收（review）

- 角色：R4PREP 独立验收助手（全新上下文）。**零真实调用**（Mock 产品路径 + 真实 provider 的离网 MockTransport）、零网络、零 commit；
  未读 `.env`/H1/H2；未改源码/测试/冻结夹具/账本/预算/GO 固定路径；只写本目录（`review.md`、`evidence/verify/`）。
- 现场：分支 `codex/p2-e2e`，HEAD `489aadd`（复核期间未变，无新 commit、无 staged 改动）。
- 只读事实（复核前后逐值一致）：账本 `05b54d06…`（1,354,211 B / 1383 行 / 691 reserved / 691 result）、
  预算 `79b21700…`、固定路径 GO `3ed427f4…`（H2 GO，未被创建/修改）。

## 0 判定摘要

| # | 检查项 | 判定 | 一句话 |
|---|---|---|---|
| 1 | 范围（只写文档/案件/计划/证据；零真实；无 commit） | **PASS** | 本包 13:20–13:26 只写 T207 文档与 R4 产物；`backend/*` 改动属并行包 FIX-CONFLICT-R2（13:35/13:36） |
| 2 | 计划契约逐值（sha/13 项/18 请求/无 OCR/中心/窗口） | **PASS** | 我从零重建同一计划并复算，全部逐值一致（含 691/69/709/6.6859204/0.018688） |
| 3 | cases 与冻结题集、ingest 6 步、Mock 灌库终态、B_r4=6 | **PASS** | 三行逐字段等于冻结题集；终态 4 资料/3 版/rev 5/4-23-15；B=6（R2=4、R3=2 与 live 账本逐值相等） |
| 4 | GO 候选（payload/授权链/12 负例/固定 GO 未动） | **PASS** | 12 条负例按预期稳定码拒；我另补 2 条谓词也按码拒；固定 GO 前后 sha 相同且对 R4 必然 `go_plan_id_mismatch` |
| 5 | dry-run（零发送、plan_sha、无账本写入） | **PASS** | `requests_sent=0`、`planned=18`、3/3 执行、账本 sha 不变、产物在仓库外且已删 |
| 6 | 目标可达性口径（§9.3 结论、修复后计划/GO/case 是否可用） | **FAIL** | 结论已过期（并行包修复后 C05/C06 已 pass）；且**计划在 live 下发不出任何 embedding POST**，索引会退化为"无向量"（见 F-1） |
| 7 | 文档一致性（cost §8 / runbook / report §9） | **FAIL** | 数字全对，但 §9.2「不是接线」不成立、HEAD 写错、runbook §9 与 report §9.3 相互矛盾 |

**总判定：返工（不可签 R4 GO）。** 计划/案件/灌库/GO 的**算术与形状**都成立，但 (a) 计划在当前产品接线下**发不出任何 embedding POST**
（灌库降级为"向量层不可用"，查询 embedding 全拒），(b) 报告的核心结论「目标不可达」已被并行包的产品文案修复推翻，
(c) 两处文档口径需统一。修完 (a) 与 (b)(c) 后即可签。

## 1 逐条判定

### 1 范围 — PASS

- 本包写入窗口 13:20:20–13:26（见 `evidence/verify/package-hashes-before.json` 与 mtime 清单）：
  `report.md §9`、`PM/T207-cost-and-quota.md §8`、`PM/T207-runbook.md §3.2/§9`、`PM/{plan,ingest-plan,GO-R4.CANDIDATE}`、
  `cases/R4.jsonl`、`evidence/{build-r4.py,r4-ingest-probe.py,validate-r4.py,*r4*}.`
- 工作区里 `backend/src/mktkb/conversations/service.py`(+32)、`copy.py`(+10)、`backend/tests/integration/test_t207_fix_conflict_r2.py`
  的改动 mtime = **13:35:40 / 13:35:52 / 13:36:04**，晚于本包窗口 ⇒ 属并行包 **FIX-CONFLICT-R2**，不是 R4PREP 越界（diff 留证：
  `evidence/verify/parallel-R2-service.diff.txt`、`parallel-R2-copy.diff.txt`）。
- 今日 `fixtures/` 无任何改动；`backend/tests/` 今日改动均早于 13:00 或属 R2。
- 零真实调用：账本 sha/字节/行数前后一致；`post_counters()` 在全部复跑中保持空；dry-run 的 `outbound_attempts=0`、`rag_provider_posts=0`。
- 无 commit（`git log` 顶仍是 `489aadd`，`git diff --cached` 为空）。

### 2 计划契约逐值 — PASS

我自己用契约常量从零重建同一份计划（不复用 `build-r4.py`），结果 `my_construction_equals_file = true`、
`plan_sha256 = 00b9fdefd8cc8220178745f0806486eaf3a70818be4068dd0fd2307303b5d2b9`（与文件、与 GO 绑定值三方一致）。
逐值复算（`evidence/verify/v2_plan.py` / `.out.json`）：

| 项 | 我的复算 | 报告值 | 判定 |
|---|---|---|---|
| 文件 sha256 | `d68db207…` | 同 | ✓ |
| items / requests / turns / cases / page_count | 13 / 18 / 4 / 4 / 0 | 同 | ✓ |
| worst-case（Decimal 自算） | 0.144960 | 0.144960 | ✓ |
| reserve_peak | 0.018688 | 0.018688 | ✓ |
| 成功估价 | 0.0297 | 0.0297 | ✓ |
| 单次上界（emb 4096×0.5 / rerank 6000×0.8 / chat 6144×2+800×8） | 0.002048 / 0.004800 / 0.018688 | 同 | ✓ |
| 中心额度 8.5-6.5-3-2（合计 20） | 20.000 | 20.00 | ✓ |
| 请求窗口 | 18 ≤ 760−691 = 69 | 同 | ✓ |
| 阶段占用 | 6.5409604 + 0.144960 = 6.6859204 ≤ 20 | 同 | ✓ |
| 累计请求 | 691 + 18 = 709 ≤ 1600 | 同 | ✓ |
| 项目总占用 | 21.6119049 + 0.144960 = 21.7568649 ≤ 40 | 同 | ✓ |
| 中心（answer_retrieval / ocr） | 0.3909604+0.144960=0.5359204 ≤ 8.5；6.15+0 ≤ 6.5 | 同 | ✓ |
| 真实固定路径 `preflight_p2` | `ok=true`，`stage_remaining=13.4590396`、`requests_remaining=69` | 同 | ✓ |

账本事实**我另写解析器**从 JSONL 复算（含 `historical_import=0.03`、非版本化 `max(charge,reserve)`、版本化用存档金额），
与 `read_ledger_snapshot()` 逐值相等：reservation 691 / result 691 / accounted 21.6119049 / P2 阶段 6.5409604 /
中心 `answer_retrieval 0.3909604`、`ocr 6.15`；R1/R2/R3 分 run 金额 5.947332 / 0.0207119 / 0.0015582 与 cost §8.1 完全一致。

### 3 cases / ingest / 灌库终态 / B_r4 — PASS

- `cases/R4.jsonl`：sha `c04b67c6…` ✓；三行 N08→C05→C06 ✓；**我自己写的转换器**（从 `fixtures/acceptance/questions.json` 逐字段映射）
  与文件逐字段相等（`diff={}`，无多余字段），既有只读转换器 `load_acceptance_cases(ids=…)` 也逐行复原；`label_version=acceptance-B0-69bd0f8680c8`
  可回溯到题集 sha 前 12 位。`N08` 的 `expected_values` 被置空 + `should_refuse=true` + 可接受措辞进 notes，与模块头声明的口径一致（更松而非更严）。
- `PM/T207-ingest-plan-R4.json`：`p2-ingest-plan/v0.1`、6 源、顺序=V03 建槽→D01→V04(不发布)→V01→D02→V02（与 §9.2 表逐项相等）；
  未知字段/嵌套断言均被拒（`ingest plan.sources[0] 含未知字段 ['assert_active_version']`）⇒ "断言只能落在证据里"成立。
  schema 本身**不校验顺序**（重排仍能解析），顺序语义靠文档与证据锁定 —— 与报告表述一致。
- Mock 灌库终态（我自己的脚本，走产品上传/解析/发布 + 真实 SQL 读数）：4 份资料；
  `D01` 槽 v1 `superseded`（9 单元）/ v2 `published`+`active`（9）/ v3 `review_required` 无 `published_at`（未 active）；
  V01/D02/V02 各 v1 `published`+`active`（5/4/5）；`product_revision=5`；索引 4 份 / 23 单元 / 15 chunk。九条断言 `all_hold=true`。
- **B_r4=6 独立复算**：包装 `RagIndex._embed_chunks` 取**产品自己的** `embedding_stats` 增量得每次待嵌入文本数
  `9/1/1/4/1`（`provider_calls=5`、`cache_misses=16`），`Σceil(n/5)=6`；上界口径 `Σceil(单元/5)=9`。
  再用**真实 `BailianEmbeddingProvider`**（httpx.MockTransport，零出网）喂同样的文本数：`post_attempts=6` ⇒ "批=POST 数"成立
  （`rag/providers.py:292-295` 按 `embedding_batch_size=5` 拆包；`product_adapter.py:1088` 固定 5）。
- **方法学自证**：同一测法对 R2/R3 灌库计划得 **4 / 2**；账本里这两个 run 的 `ingest-index-embedding` 预留数（我自己数）也是 **4 / 2**
  ⇒ `ceil/5` 口径与 live 实测逐值相等，6 可信。R4 = R2 的 4 步 + R3 的 2 步合并成一库，B=4+2=6 的说法成立。
- 三例 live 形状（每轮 1 次 query embedding）：N08 `not_found`（0 次模型调用）、C05 `conflict`+来源 D01/V01、C06 `conflict`+来源 D02/V02；
  冲突轮 0 次 chat 调用、1 次 rerank、1 次 query_embedding（第 2 次 embedding 在门控处被拒）⇒ 与计划 1/1/1/1 的上界相符。

### 4 GO 候选与负例 — PASS

- payload 12 项自查全通过：`document=P2-LIVE-GO`、authorization 含 "DRAFT"/"NOT USABLE"、绑 `plan_id`/`plan_sha256`、
  账本 `f4710b18…`（= 当前历史前缀）、五操作无 ocr、`max_requests=760`、`max_request_cny=0.5`、中心 8.5/6.5/3/2、`P2-LIVE=20`、
  40 元上限、13 天（12:30Z+08 → 11-24 12:30Z+08）。
- `authorize_p2`（内存 GO + 真实快照包成 in-memory）通过：`production_ready=false`、`requests_remaining=69`、
  `stage_remaining=13.4590396`、`center_remaining.answer_retrieval=8.1090396`。
- **12 条负例**（我按语义自己造，不复用开发方代码）全部按预期稳定码拒：
  `go_operation_unauthorized`、`go_max_requests_below_plan`×2、`go_plan_sha256_mismatch`、`go_plan_id_mismatch`、
  `go_cost_center_below_plan`、`go_max_request_cny_below_plan`、`go_expired`、`request_budget_insufficient`、
  `request_cap_over_hard_limit`、`plan_requests_over_cap`、`center_budget_exceeded`。
  另补 2 条开发方未覆盖的谓词也通过：preflight 的中心窗口 `center_budget_insufficient:answer_retrieval`、GO 账本绑定 `go_ledger_binding_mismatch`。
- **固定路径 GO 未被动**：`3ed427f4…`（H2 GO）复核前后逐字节相同；且无论以内存 payload 还是以固定路径传入，
  对 R4 计划都是 `go_plan_id_mismatch`（不可能误用这张旧 GO 跑 R4）。

### 5 dry-run — PASS

我重跑 `p2-run`（Mock，`--out` 在仓库外）：`status=succeeded`、`requests_planned=18`、**`requests_sent=0`**、
`cases 3/3 executed`、`requests.real_requests=0`、`network.outbound_attempts=0`、`rag_provider_posts=0`、
`production_ready=false`、`plan_sha256` 与文件逐值相同；灌库回执 revision 1→2→2→3→4→5（V04 不发布不加 revision）。
跑前跑后账本 sha 不变；产物目录在 `%TEMP%` 下、跑完已删。仓库内无 `undefined` 目录、无临时 `temp` 残留
（根目录那个空的 `%SystemDrive%` 目录创建于 00:19，早于本包窗口，非本包产物）。

### 6 目标可达性口径 — FAIL（结论过期 + 计划不可执行）

**(a) 「冲突轮 text 不含值 ⇒ 冻结 value_hit 必 fail」在 HEAD 489aadd 上成立**：`scorers.py:632` 只取 `outcome.text`，
`product_adapter.py` 只把 `payload["text"]` 交给评分；HEAD 的 `conversations/service.py:2338` 用
`copy_module.legacy_conflict_text(fields_text)`，文本里只有字段名，值只在 `conflicts` 负载里（我的 raw 抓取与开发方一致）。

**(b) 但该结论在当前工作区已不成立**：并行包 FIX-CONFLICT-R2 于 13:35 把冲突文本改成渲染 `字段：[值1、值2]`
（`evidence/verify/parallel-R2-service.diff.txt`）。我用**冻结评分器**重跑同一份 case/灌库计划：
N08 `pass` / C05 `pass` / C06 `pass`（`value_hit` 由 fail 变 pass），且**请求形状不变**：0 次 chat、每冲突轮 1 次 rerank + 1 次 query_embedding。
我又用**开发方自己的 probe** 在同一工作区复跑，得到的结构量与他们 13:24 的文件逐值相同，只有 scoring 与冲突文本不同
（`evidence/verify/dev-vs-repro-state.json`：`structural_identical=true`、`scoring_differs=true`）。
⇒ `report.md §9.3`「目标不可达」是 **HEAD 489aadd + 未合入 R2 修复**时的读数，现在必须改写为"历史读数 + 修复后已可达"，否则会误导决策。

**但"修复后=C05/C06 必过"仍只在 Mock 里被证明**：两次 live 运行（R3 11:11:28+08、R2 11:12:11+08）的
`kind_correct` 都是 `expected=conflict, actual=answer`（`scoring/R2`、`scoring/R3`），而它们早于
FIX-CONFLICT-R1 `0260b7b`（13:11）与 R2 的文案修复（13:35）。**live 上还从未观测到 conflict**；
Mock 能触发靠的是离线 hash 向量 + 门控抛 `RuntimeError`，与 live 的真实 embedding/门控异常类型不同。
⇒ 建议 §9.3 增加一句："修复后可达性的直接证据仍只有 Mock；live 首次验证即 R4 本身，存在 still-answer 的可能"。

**(c) 修复后计划/GO/case 能否直接复用**：技术上**可以**——`plan_sha256` 是计划内容哈希（文案改动不影响），GO 绑的是
`plan_id/plan_sha256/operations/cost_centers`（都不变），case 期望值不变，请求形状不变（我这轮实测印证）。
**但**：(i) 另有 F-1 的接线阻断，与本修复无关；(ii) `runbook.md:355` 写"因产品/口径改动而重跑 = 新计划 + 新 GO"，
与 `report.md §9.3`"不改计划"直接冲突，必须由经理裁定并写死口径（我建议：**文案-only 改动不算 pipeline 变更**，
因为 plan/请求形状/证据链未变；但需在 runbook 里明确写出这条例外，否则 §9 与 §355 会继续互相打脸）；
(iii) R2 的改动**还没提交**，R4 真实运行前必须先落盘/锁定版本，否则 run 产物无法回溯到代码版本。

### 7 文档一致性 — FAIL

数字侧**全部对得上**（我逐条对过 cost §8.1/§8.2/§8.3、runbook §3.2、report §9.2 的每个数），但有三处不实/不一致：

1. `report.md §9.2` 的「挡住 R4 的是 §9.3 的口径，**不是接线**」**不成立**（F-1）。
2. `report.md §9.0` 写「HEAD `0260b7b`」，但证据写入时 HEAD 已是 `489aadd`（13:23:08 提交，证据 13:23:46–13:24:26 落盘）；
   应写 `489aadd`（或注明"开工时 HEAD"）。
3. `runbook.md:355` 与 `report.md §9.3` 的"是否要重签计划/GO"互相矛盾（见 6(c)）。

## 2 复跑命令与产物（全部零真实调用）

```powershell
$v='docs\reports\OBS-EVAL\P2\T207-R4PREP\evidence\verify'
.venv\Scripts\python.exe -B -X utf8 "$v\v1_cases.py"        --out "$v\v1_cases.out.json"
.venv\Scripts\python.exe -B -X utf8 "$v\v2_plan.py"         --out "$v\v2_plan.out.json"
.venv\Scripts\python.exe -B -X utf8 "$v\v3a_embed_ceiling.py" --out "$v\v3a_embed_ceiling.out.json"
.venv\Scripts\python.exe -B -X utf8 "$v\v3b_ingest.py"      --out "$v\v3b_ingest.out.json"
.venv\Scripts\python.exe -B -X utf8 "$v\v4_go_negatives.py" --out "$v\v4_go_negatives.out.json"
.venv\Scripts\python.exe -B -X utf8 "$v\v5_ingest_schema.py" --out "$v\v5_ingest_schema.out.json"

# 开发方脚本复跑（确定性；产物仍写回原文件，前后 sha 不变）
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\build-r4.py --step inputs|plan|go
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\r4-ingest-probe.py --out "$v\repro-r4-ingest-state.json"
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\validate-r4.py

# 驱动 dry-run（Mock、零发送；--out 在仓库外）
.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-run --plan ... --out "$env:TEMP\p2-r4prep-verify-dryrun" ...
```

| 证据 | 内容 |
|---|---|
| `v1_cases.out.json` | 三行 vs 冻结题集逐字段（我自己的映射器 + 既有转换器双路）；sha/顺序/label_version |
| `v2_plan.out.json` | 从零重建计划 + Decimal 复算 + 账本 JSONL 自解析 vs `read_ledger_snapshot` + preflight 窗口 |
| `v3a_embed_ceiling.out.json` | **F-1 的决定性证据**：0.018688 → 0 POST + `EmbeddingUnavailable`；0.5 → 6 POST |
| `v3b_ingest.out.json` | 灌库终态、文本数 9/1/1/4/1、B=6、R2/R3=4/2 vs 账本、三例打分与 raw conflicts |
| `v4_go_negatives.out.json` | GO payload 12 项、授权链、12 负例 + 我补 2 条、固定 GO 前后 sha |
| `v5_ingest_schema.out.json` | ingest 计划 6 源顺序、未知字段拒绝、顺序不被 schema 校验 |
| `v6_ceiling_impact.out.json` | 把"单请求上限拒绝 embedding"注入产品路径：灌库降级（`embedding_error`）、三例仍出正确 kind |
| `dev-vs-repro-state.json` | 开发方 13:24 读数 vs 当前工作区复跑：结构量逐值相同，仅 scoring/文本不同 |
| `package-hashes-before/after.json` | 15 个包内文件 + 账本/预算/固定 GO 的 sha256 与字节：**前后全部一致** |
| `parallel-R2-*.diff.txt` | 并行包改动原文（证明 backend 改动不属于本包） |

## 3 发现（按严重度）

### F-1 **BLOCKER：R4 计划在 live 下发不出任何 embedding POST（索引降级为"无向量"）**

- 接线：`product_adapter.py:1074`（在 `_start_live` 内）`max_request_cny = float(wiring.plan.reserve_peak_cny)`
  → `product_adapter.py:1091` 传给 `RagConfig`。R4 计划无 OCR ⇒ `reserve_peak=0.018688`。
- 供应商侧：`rag/providers.py:316-321` 每次 POST 前算 `reserve_cny = 81,920 tokens × 0.5/1e6 = **0.04096**`，
  只要 `> config.max_request_cny` 就 `EmbeddingUnavailable("单次 embedding 预留超过单请求上限")`，**不发送**。
  0.04096 > 0.018688 ⇒ 每一次 embed 都被拒（文档 11 次 + 查询 4 次）。
- 因果闭链：`p2_contracts` 把 embedding 的 `total_tokens_cap` **冻结为 4096**（`cap_not_frozen`），计划侧无法把峰值抬到 0.04096；
  不含 OCR 的计划里最大单次上界是 chat 的 0.018688 ⇒ **任何 `page_count=0` 的计划在当前接线下都发不出 embedding**（H2 计划按 cost §5 也是 `page_count=0`）。
  R1/R2/R3 之所以正常，是因为那张计划含 12 页 OCR（峰值 0.5）。
- 复现 A（供应商边界）：`evidence/verify/v3a_embed_ceiling.out.json` —— **真实 `BailianEmbeddingProvider`** + `httpx.MockTransport`（零出网）：
  `max_request_cny=0.018688`（= 计划 `reserve_peak`）→ `post_attempts=0` + `EmbeddingUnavailable`；
  `max_request_cny=0.5`（R1–R3 计划的峰值）→ 同样 5 次 embed 正常拆成 `post_attempts=6`。
- 复现 B（产品层后果，`v6_ceiling_impact.out.json`）：把同样这条异常注入 Mock 产品路径后，灌库**不会硬失败**：
  `degraded=["embedding_error"]`、`error_code=EMBEDDING_UNAVAILABLE`、`error="向量层暂不可用，记录型/精确层仍可用"`，
  4 份资料/23 单元/15 chunk 仍在但**没有向量**；三例仍能出正确 kind（N08 not_found、C05/C06 conflict），
  且文本已含冲突值（按冻结评分器应三项全 pass，与 `v3b` 在正常管线下的结论一致）。
- 为什么不会硬停：拒绝发生在 `_embed_batch` 内、从未产生 POST，所以计划的 `index_embedding=6` 一次也没被用掉，
  也不会触发 `attempt_quota_exhausted`；错误被 `add_document`/`qa/service.py:345-348` 吞成 degraded。
- 影响（比"硬失败"更危险）：签 R4 GO 后**不会立刻报错**，而是产出一份"看起来通过、其实向量层全灭"的证据——
  与 R4 想证明的"真实 pipeline 下三例通过"不符（召回层根本没参与）。另外 `report.md §9.2` 的"驱动接受性"只覆盖 dry-run
  （Mock/offline 路径，看不见这条 ceiling）。
- 建议（本轮唯一可行路径，需另立改动）：把 `_start_live` 的 `max_request_cny` 改成
  `max(plan.reserve_peak_cny, provider 单次预留)`（或直接用 GO 的 `scope.max_request_cny=0.5`），并补一条**离线**回归：
  "无 OCR 计划 + live 装配 → embedding POST 能发出"。计划侧绕不过去（cap 冻结）。

### F-2 **结论过期：§9.3「目标不可达」已被并行包修复推翻**

见 §6(b)。结构性证据不变、只有评分与文本变化，已用开发方 probe 复跑与我的独立脚本双向确认。
建议 §9.3 改成两段：①「HEAD 489aadd 的历史读数：C05/C06 `value_hit fail`（两种形状）」；②「FIX-CONFLICT-R2 落地后：
三例 pass（本 review 复跑），计划/GO/case 无需重签，只剩 F-1 的接线阻断」。并把 `r4-ingest-state.json` 标注为"修复前读数"。

### F-3 **文档冲突：runbook §9 与 report §9.3 对"要不要重签"给相反结论**

`runbook.md:355`「因产品/口径改动而重跑 = 新计划 + 新 GO」 vs `report.md §9.3`「不需要改计划」。二者必须统一
（技术事实站在 report 这边：plan_sha 是内容哈希，GO 绑的字段都不变）。

### F-4 **文档小错：HEAD 写 `0260b7b`，实际为 `489aadd`**

证据落盘时（13:23:46–13:24:26）HEAD 已是 `489aadd`（13:23:08 提交）。

### F-5 **§9.2「不是接线」的表述不成立**（= F-1 的文档面）。

### F-6 口径小项（不阻塞，建议在 §9 补一句）

- 「12 条负例」实际覆盖 **11 个稳定码**（`go_max_requests_below_plan` 出现两次，分别打 600 与 10，同一谓词）；
  名为 `center_below_plan_need` 的那条其实在**计划构造期**就 `center_budget_exceeded`，没有覆盖 preflight 的中心窗口
  （我用 `preflight_center_window_insufficient` 补测，通过）。
- `forbidden_sources` 里的 `V03`/`V06` 在 `document-codes.json` 中没有对应文档名（映射只按产品文档名、版本号不进映射）
  ⇒ `source_forbidden` 对这两个代号是"**不可命中**"，`pass` 不等于"检查有效"。R2(C05)/R3(C06) 同形，属既有口径，非本包引入。
- 计划把 `index_embedding` 写成 **6**（实测值）而非上界 **9**：多出 1 个 POST 就会在第 7 批发前
  `attempt_quota_exhausted`（零花费但整轮作废）。作为"精确"是优点，作为"安全余量"是缺点，建议在 §9.2 明写这个取舍。

## 4 限制与未覆盖

- 按任务书**不做真实调用**：F-1 是"代码路径断言 + 真实 provider 的离网 MockTransport 复现"，不是端到端 live run；
  签 GO 前建议补 F-1 建议的离线回归，或由经理接受"先小步试跑 1 次 ingest"的风险（失败也零花费）。
- 未跑全仓/全量测试：并行包正在改产品代码（13:35 落地），测试结果会被污染，且任务书未要求。
- 未读 `.env`/H1/H2，未评估答案质量；未验证 H2 计划（只按 cost §5 的 `page_count=0` 推断它同样触发 F-1）。
- F-1 的影响面用"注入同样的 `EmbeddingUnavailable`"来推断（`v6`），不是真实 live run；真实运行时
  `GatedEmbeddingProvider`/`GateAttemptLedger` 的拒绝会以 `BudgetLedgerInvalid` 形态进入同一 `add_document` 捕获点，
  但"降级而非硬停"这一点建议在修 F-1 时顺手用一条离线用例钉住。
- `docs/evidence/` 被 `.gitignore` 忽略，固定 GO/账本/预算的"未动"只能靠 sha+字节数证明（已前后各取一次）。
- 复核期间工作区状态发生变化（并行包 13:35 落地）。我的结构证据在其之后采集，并用 `dev-vs-repro-state.json` 显式对齐了这一点。

## 5 返工清单（最小）

1. **[必做]** 解决 F-1：产品侧放宽 `_start_live` 的 `max_request_cny`（或改用 GO 的 0.5），并加离线回归；
   否则 R4 会在"向量层全灭"的降级管线上跑出**看似通过**的证据（H2 同理）。
2. **[必做]** 改写 `report.md §9.3`：标注"HEAD 历史读数" + "R2 修复后三例 pass（本 review 复跑）"，并同步更新
   `runbook.md §3.2/§9` 的"R4 前置"段；统一"文案-only 改动是否重签"的口径（建议：不重签）。
3. **[必做]** 更正 `report.md §9.0` 的 HEAD 值；把 R2 的产品改动**先提交**（当前是工作区未提交），R4 才能可回溯地跑。
4. **[建议]** §9 补三处口径：F-6（负例覆盖、forbidden 不可命中、`index_embedding=6` 的取舍）与
   "live 尚未观测到 conflict"（R2/R3 的 `actual=answer` 属修复前读数）。

## 6 最终建议

**返工（不接受当前状态）**，但在完成第 5 节 1–3 项后可以**直接接收并签发 R4 GO**：
计划/案件/灌库/GO 的算术与形状已经逐值复核通过，B_r4=6 的方法学有 live 账本背书，
真正挡住 R4 的只剩"一个产品接线常数"和"两段过期文档"。
