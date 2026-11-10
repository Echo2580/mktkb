# P2 真实准入 readiness（T206 准备 · 零真实调用）

- 角色：T206 准备助手（全新上下文）。只做**准入前文档 / 计划 / 候选 GO / runbook**；
  真实调用 **0**；未读 `.env` / H1 / H2；未联网；未写真实 budget / GO / 账本；未 commit。
- 现场：分支 `codex/p2-e2e` @ HEAD `61a9a8f`（工作区只有经理协调文档 `_index.md` 修改与
  `.claude/handoffs/**` 未跟踪项；P2 代码零改动）。
- **一句话结论**：钱与请求的算术、计划/GO 绑定、预检与授权负例**全部可离线证明**（见 §12），
  5 题 pilot 的 worst-case 是 **0.826784 元 / 55 次请求**（≤2 元、串行、重试 0）；
  但**当前代码没有真实 live 执行入口**（§9 G1–G6），pilot 在补齐这些缺口前**不可执行**。
  这不是金额/额度问题，而是接线问题；补齐方案需经理决定范围，本包不代做。

## 1 现场（本次只读实测）

| 项 | 值 | 来源 |
|---|---|---|
| 分支 / HEAD | `codex/p2-e2e` / `61a9a8f` | `git rev-parse` |
| 共享账本 | 958,277 B，SHA-256 `1f46d1b9e846528d5a1635db5175a997eab9da075d61a90a8cbf803f3fde7390` | 只读副本 + 项目 `read_ledger_snapshot()`（指向临时副本，未碰仓库文件） |
| 历史前缀 SHA | `f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014` | `historical_prefix_sha256()` |
| 共享预算 | 1,444 B，SHA-256 `084ba9acb4ee90379fd51fab8878f6dd4bab1bd481bff2a14c83057ffbc1cc58` | 同上 |
| 总上限 / 已占 | 20.00 元 / 15.070944499999985 元（历史 0.03 + S2-DEV 15.4 + P1-RETRIEVAL 3.0 …） | `BudgetLedger.summary()` |
| 请求 | reservation 505 / result 505；硬顶 `HARD_MAX_REQUESTS=1000`，余 495 | 同上 |
| P2 阶段 | **不存在**（stages：S1-DEV 0 / S1-IA 0 / S2-DEV 15.4 / P1-RETRIEVAL 3.0 / later_shared_reserve 1.57） | `budget.json` |
| P2 已占 | 0.0；`p2_center_accounted_cny` = `{}` | 同上 |
| 正式 GO | `docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json` **不存在** | `P2_GO_PATH` 实测 |

> 本次未调用 `read_ledger_snapshot()` 于仓库真实路径（它会建瞬时 `.lock`）；改为把两份文件**复制**到
> `%TEMP%/p2-t206-prep` 后指向副本重算。副本字节与真实文件同哈希，故数字等价；仓库文件零写入。

## 2 前置证据清单（T201–T205 + R2 + T206-PRE + R1，均已接收）

| 包 | 结论 | commit | 证据入口 | 本包复跑 |
|---|---|---|---|---|
| T201 计划/预检/授权门 | 独立 PASS | `3afe8c3` | `docs/reports/OBS-EVAL/P2/T201/{report,review}.md`、`evidence/verify/probe_t201.py` | 否 |
| T202 H2 封存与加载器 | 独立 PASS | `97fba10` | `T202/**`、`docs/evaluation/p2-dataset-v0_1.md` | 否 |
| T203 产品端到端运行器 | PASS 8/8 + R1 7/7 | `897a751`+`eed3355` | `T203/{report,review,review-R1}.md` | 否 |
| T204 OCR/缓存/页级回执 | 独立 PASS 8/8 | `7cbabef` | `T204/{report,review}.md`、`docs/evaluation/p2-ocr-contract-v0_1.md` | 否 |
| T205 评分/8 硬门禁 | 有条件接收（6/7，2b 缺项并入 R2） | `d850b49` | `T205/{report,review}.md` | 否 |
| R2 遗留加固 | 复验 PASS 12/12 | `a8f2a6b` | `T205/report.md` §R2、任务书 §10 | 否 |
| T206-PRE 绑定/证据/失败产物 | 独立 PASS | `1e422e9` | `T206-PRE/{report,review-T206-PRE}.md`、`docs/evaluation/p2-live-binding-v0_1.md` | 否 |
| R1 收尾（config_hash / retrieved / 措辞） | 复验 PASS | `61a9a8f` | `T206-PRE/review-R1.md` | 否 |

**未复跑的理由**：任务书 §3.9 —— 文档准备不跑产品测试；开发/验收包各自跑定向清单。
本包只跑**纯契约**离线校验（不建产品应用、不发 HTTP、不触账本），见 §12。

## 3 预算 / 请求 / GO 前置（拟签发值）

### 3.1 资金算术（与 T201 候选一致，中心改用经理已采纳基线）

    limit_cny                 20.00 -> 40.00（候选修订，T201 遗留③：Σstages+history 必须 == limit）
    历史保守占用               0.03（原样保留，不挪用旧余额）
    原阶段：S1-DEV 0 + S1-IA 0 + S2-DEV 15.4 + P1-RETRIEVAL 3.0 + later_shared_reserve 1.57
    新增阶段：P2-LIVE 20.0
    校验：0 + 0 + 15.4 + 3.0 + 1.57 + 20.0 = 39.97；39.97 + 0.03 = 40.00  ✓

- 成本中心（经理 2026-11-10 决定）：`answer_retrieval 9 / ocr 6 / judge 3 / independent 2`（合计 20）。
- 历史剩余 4.9290555 元**不计入** P2；P2 只能花自己那 20 元。

### 3.2 pilot 占用（详见 `PM/p2-pilot-plan-v0_1.json`）

| 指标 | 值 |
|---|---|
| worst-case（Σ 上界×请求） | **0.826784 元**（≤2 元） |
| 串行单次峰值预留 | 0.5 元（D09 一页 OCR），非 0.018688 |
| 成功估价 | 0.5648 元（OCR 固定价 0.5 占大头；仅供分列，不参与准入） |
| 计划请求总数 | **55**（index_embedding 30 + query_embedding 6 + rerank 6 + query_expansion 6 + answer 6 + ocr 1） |
| `plan.max_requests` | **560 = 505（历史）+ 55**（累计口径，未重置、未提高 1000 硬顶） |
| 中心需要 vs 额度 | answer_retrieval 0.326784/9；ocr 0.5/6；judge 0/3；independent 0/2 |
| 条目 | 26 项；`plan.case_count`=6（5 题 + 1 个 `INGEST` 聚合项） |

### 3.3 GO 前置（签发时必须同时成立）

1. `budget.json` 落盘修订（limit 40.00 + `P2-LIVE=20.0`），且算术校验通过（§3.1）。
2. 正式 GO 写到固定路径 `docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json`，
   `document=P2-LIVE-GO`、`stage=P2-LIVE`、nonce ≥16、`issued_utc ≤ now < expires_utc`、
   `expires-issued ≤ 14 天`、`scope.plan_sha256` = 计划摘要、`budget_ledger_sha256` = §1 历史前缀。
3. 运行进程内设置 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=40.0`（**只设本次进程环境**，不改 `.env`/全局）；
   未设置 → `env_total_limit_missing`（GO/预算来自固定路径时是硬拒绝）。
4. 真实调用前重算账本/预算 SHA；与 §1 不一致即停（历史前缀变化说明账本被改写）。

## 4 供应商 / 模型 / 价格上界来源（全部为冻结常量，计划只能引用）

| kind | provider / host / region | model | 冻结 caps | 单价下限 | 单次上界 |
|---|---|---|---|---|---|
| chat | deepseek / api.deepseek.com / global | `deepseek-flash` | prompt 6144 + completion 800 | 输入 2 元/M、输出 8 元/M | (6144×2 + 800×8)/1e6 = **0.018688** |
| embedding | bailian / dashscope.aliyuncs.com / cn-beijing | `text-embedding-v4` | 4096 token | 0.5 元/M | 4096×0.5/1e6 = **0.002048** |
| rerank | bailian / dashscope.aliyuncs.com / cn-beijing | `gte-rerank-v2` | 6000 token | 0.8 元/M | 6000×0.8/1e6 = **0.0048** |
| ocr | tencent / ocr.tencentcloudapi.com / ap-guangzhou | `GeneralAccurateOCR` / `RecognizeTableAccurateOCR` | 1 页/次 | 固定价 | **0.5 / 0.15**（每页一次调用） |

来源：`p2_contracts.py` 的 `P2_PRICE_PROVIDER_BINDINGS` 与 `rag/settlement_policy.py` 的
`CHAT_*_CAP/…_PRICE_FLOOR`（T201 已核：官方按量最高档）。写小单价 / 漏 token 上界 / 写 0 价
都在构造期被拒（`price_below_floor`/`cap_not_frozen`/`price_missing`），所以「猜低上界」换不到准入。

## 5 fail-closed 点（pilot 依赖的全部硬门）

- **预检** `preflight_p2`：`budget_total_mismatch`、`stage_allocation_missing`、
  `stage_allocation_below_plan`、`stage_budget_insufficient`、`total_budget_insufficient`、
  `request_budget_insufficient`、`center_budget_insufficient:<center>`、`center_accounting_inconsistent`。
- **授权** `authorize_p2`：旧 GO（`legacy_go_document`）、schema/stage、nonce、时间窗、
  `go_plan_id/sha256` 绑定、操作与中心 ⊆ GO、阶段额度、`go_max_requests`(>1000 拒)、
  `max_request_cny ≥ 峰值`、账本前缀绑定、`env_total_limit_missing/mismatch`、固定路径/软链。
- **发送前两段门**：`P2Gate.begin`（锁内预留前）+ `confirm_before_send`（预留后收发前）；
  失败一律 HTTP=0；已发生的预留写成 `status=failed`、`error_code=P2_PRE_SEND_REFUSED:<code>`、
  按预留额保守占用，不回 0、不释放。
- **runner 停止码**：`production_not_ready`、`live_requires_real_gate`、`holdout_requires_purge`、
  `plan_item_missing`、`pre_send_refused`、`turn_timeout`(60s)、`product_service_error`（此后不再发）、
  `no_case_executed`（空跑不算成功）。
- **身份/证据**：trace 六字段（run_id/dataset_version/manifest_sha256/pipeline_version/
  index_revision/config_hash）缺一项整体不绑 → `trace_integrity=version_binding` fail；
  `citation_evidence.complete=False` 或引用不在本轮候选 → `citation_not_in_evidence`；
  scorecard 缺 `config_hash` → `config_hash_unbound`（R1 起双侧各判）。
- **产物**：网络分解对不上 → `provider_network_detail_mismatch`，仍写 4+ 件产物后抛出
  （`status=aborted`、`providers=null`、`real_sends_allowed=false`）。

## 6 R1 残余（pilot 驱动必须遵守）

1. **gate 不能识别伪造 retrieved**：把 citations 抄进 retrieved 也会 pass（`copy_citations_passes_gate_trust_boundary`）。
   → pilot 驱动**不得**把引用当 retrieved，**不得**给 `score_public_case(evidence=...)/
   normalize_product_outcome` 传人工候选；一切走适配器实测。
2. **rag 候选是召回并集**（exact/lexical/vector/fused），可宽于 `fused[:top_k]` 返回证据；
   pilot 若出现 `citation_not_in_evidence`，按「重放口径不覆盖该轮上下文」记录，
   不得改成「缺候选也算通过」。

## 7 N5：OCR 重试成本（GO 预检必须计入或缩页集）

- T204 实测：B0 D07–D10 共 12 次调用，**无重试** = 11×0.5 + 1×0.15 = **5.65 元**（中心 6.0 够）。
- **任一页重试**：首轮 4 次尝试 + 重试轮 5 次新调用 = **9 次 / 4.5 元**，仍只覆盖部分页；
  全量重跑一次就会突破 6 元中心。
- 本 pilot 只 OCR **1 页**（D09，text 模式 0.5 元），且**自动重试 0**：页失败即停、不补跑，
  因此 0.5 元是硬上界；pilot 的结论不推广到「12 页可重试」。

## 8 H2 标准（pilot 不涉及）

- 已批准目标：**≥24/30 通过，且安全/跨用户/跨实体/失效来源硬失败 = 0**；分层 10/5/5/5/5；
  `turn_stats.total_turns=36`。T206 准入时绑定，**不重复询问、不改低**。
- `gate_v0_3` 仍是 `unapproved`：任何放行/发布都必须等 T209 主人批准。pilot 只跑公开冻结集合，
  **不读 H2 题干/答案**，也不产生 H2 分数。

## 9 阻断缺口：pilot 当前**不可执行**（G1–G6）

| # | 缺口 | 证据 | 影响 |
|---|---|---|---|
| G1 | 适配器恒为 Mock（`is_mock=True`，`rag_provider_mode="offline"`，embedding/rerank 用离线替身，OCR 是 `_NoOcrGateway`） | `backend/src/mktkb/evaluation/product_adapter.py:803-806, 829, 863-864, 869` | runner 只会判成 `dry_run`，真实链路无法成立 |
| G2 | 没有 live 驱动/CLI：`p2-run` 只走 `build_dry_run_authorization` + `MockChatBackend` | `backend/src/mktkb/evaluation/cli.py:530-636`；`P2Gate.open`/`authorize_p2` 在 `backend/src` 无生产调用点（仅测试/探针） | 无入口按 GO 发请求 |
| G3 | OCR 传输层写死 Mock（`MockOcrTransport` + mock 凭据） | `backend/src/mktkb/evaluation/p2_ingestion.py:1173-1180` | 真实 OCR（pilot 的 Q37 必需）无法执行 |
| G4 | 无真实 `UsageEvidence`：chat/embedding/rerank 的 `settle_success` 必须要 evidence，而 `ProductTurn` 不含 token usage | `p2_authorization.py:1136-1146`；`product_adapter.py:645-676` | 首个成功 chat 轮就会 `evidence_required`→`gate_error` 停下（fail-closed，但 pilot 跑不完） |
| G5 | 成本归属未定：RAG provider 的 `budget` 钩子可接共享账本，但适配器未接；若接了不带 `cost_center` 会让阶段占用无法归属 | `rag/providers.py:528-534`；`p2_authorization.py:382-387` | 接了→`center_accounting_inconsistent` 拒绝；不接→真实花费不入账 |
| G6 | 请求累计口径只数账本 reservation，而 runner 只为 `answer` 逐轮 `begin`（embedding/rerank/expansion 只在计划里声明） | `p2_runner.py:271-284, 991-1002`；`p2_authorization.py:620-642` | 「每次真实底层尝试计数」在 pilot 上只能靠实测计数旁证，账本计数会偏少 |

最小关闭方向（**需经理定范围，本包不实现**）：一个只读驱动 `tools/p2_t206_pilot.py`
（或等价脚本）负责——用固定 GO/预算 + `read_ledger_snapshot()` 构造 `P2Gate`；构建 live
适配器（真实 provider + `p2_ingestion` 的真实传输与 `OcrCostCenterBudgetLedger`）；
把 provider 实测 usage 汇总成 `UsageEvidence`（G4）；明确非 answer 操作的预留/归属（G5/G6）；
所有发送仍走 `run_p2`（默认重试 0、60s 单轮上限）。缺口清单未关闭前，runbook §4 标 BLOCKED。

## 10 未覆盖 / NOT-RUN

- 真实模型/OCR/embedding/rerank：**0 次**（本次只做文档与纯契约校验）。
- H2 端到端、Ragas、Langfuse、浏览器链路：NOT-RUN（分属 T207/T208/T211/T900）。
- 未跑全仓测试；未复跑 T201–T205 套件（理由见 §2）。
- 未核供应商实账（`provider_billed_cny=null`）：本文件全部金额是**保守占用口径**，不是账单。

## 11 风险与回滚

| 风险 | 处置 |
|---|---|
| 候选 GO 与正式 GO 的**字段集完全相同**（schema 无 DRAFT 标记），复制到固定路径即会被当真实授权 | runbook §2：候选文件只读、禁止拷贝到 `P2_GO_PATH`；正式 GO 必须经理落盘并复核 SHA |
| 预算修订后忘记同步 `MKTKB_PROJECT_TOTAL_LIMIT_CNY` | 不设置 → `env_total_limit_missing` 直接拒绝（不会放行） |
| pilot 中途失败被误当「可重跑」 | 重跑=新计划+新 GO（plan_sha 绑定），且计入同一 20 元/同一累计请求 |
| 账本被外部改写 | 每步重算 SHA；前缀不符 → `go_ledger_binding_mismatch` / `ledger_prefix_mismatch` |
| 回滚 | 本包零写入真实资金面；若 pilot 已跑，回滚 = 停止后续发送 + 保留 `out_dir` + **不编辑账本**（历史结果不可改），失败金额如实留在账上 |

## 12 本包产物与离线校验（可复跑）

产物（均在 `docs/reports/OBS-EVAL/P2/T206/`）：

| 文件 | 状态 |
|---|---|
| `PM/P2-LIVE-readiness.md` | 本文件 |
| `PM/p2-pilot-plan-v0_1.json` | DRAFT 计划候选（`p2-run-plan/v0.1`，`plan_sha256=d2baaa9c…73c2`） |
| `PM/P2-LIVE-GO.CANDIDATE-DRAFT.json` | **DRAFT 候选 GO，不可用**（`production_ready=false`，`P2_GO_PATH` 不存在） |
| `PM/runbook.md` | 执行/停止/核对/回滚 |
| `report.md` | 5 题依据、成本/请求、对照与风险 |

纯契约校验（零真实调用；脚本在 `%TEMP%/p2-t206-prep/`，不在仓库）：

1. `P2RunPlan.from_dict(计划)` 通过；`worst_case=0.826784`、`reserve_peak=0.5`、`total_requests=55`。
2. 预检 vs **现状预算**（limit 20、无 P2 阶段）→ 拒绝：`budget_total_mismatch`,
   `stage_allocation_missing`, `stage_budget_insufficient`（证明未修订前发不出请求）。
3. 预检 vs **候选预算**（40 / P2-LIVE 20）→ `ok=true`，`stage_remaining=20`、`total_remaining=24.9290555`、
   `requests_remaining=55`、`center_remaining` 9/6/3/2。
4. `authorize_p2`（内存 GO+预算+快照）→ 授权成立但 `production_ready=false`，`go_sha256=4d8abdd8…`。
5. 负例全部按预期拒绝：`go_expired`、`go_not_yet_valid`、`go_operation_unauthorized`（删 OCR）、
   `go_max_request_cny_below_plan`（0.1）、`go_max_requests_below_plan`（100）、
   `go_max_requests_over_hard_cap`（1200）、`budget_stage_missing`、`budget_total_mismatch`（limit 20）、
   `go_plan_sha256_mismatch`、`legacy_go_document`、`go_plan_id_mismatch`。
6. 5 题行 `CaseSpec`+`validate_case` 全部通过；`case_questions` 合计 **6 轮**；
   pilot cases 字节（5 行原样拼接）4,712 B、SHA-256 `a3878212fa1c114eb5a8c280bcf01c74d0131744c6aa568a2edfd36302652c79`。
