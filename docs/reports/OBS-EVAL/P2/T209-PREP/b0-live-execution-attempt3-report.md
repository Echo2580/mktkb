# T209 正式 B0 attempt3 · 真实运行执行回执

2026-11-20，Asia/Shanghai。执行角色：真实运行执行 AI（本轮执行 + 签发 GO + 收尾；独立复核、基线接收与 P2 发布另行授权）。
工作树 `D:\GPT项目\市场部AI知识库`，分支 `codex/p2-e2e`，基准 HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`（执行前后一致，未提交、未改跟踪内容）。

**执行状态：`COMPLETE`** — 唯一一次真实运行退出 **0**，40/40 题，112 次出站，无 stop_code。
**准入状态：`PASS`** — 只读 `p2-admit` 退出 **0**，八项硬门禁按适用性全部成立，`trace_integrity=pass`（attempt2 的阻断已消除）。
**质量（单列）：38/40 通过，精确 24/24，OCR 执行 8/8（7 通过）。**
**发布状态：仍 `blocked_pending_n_c_u_h2_evidence`（`p2_release_allowed=false`）**，属另行审批，本轮未触碰。

## 1. 摘要

| 项 | 值 |
| --- | --- |
| 运行 ID / 计划 ID | `p2-t209-b0-20261120-02` / `P2-T209-B0-20261120-02-DRAFT` |
| 计划规范 / 文件 SHA-256 | `38d8c7f228de339255ea0f8cd6638ce6762374ab276c43d1993607131a194931` / `720417ba2e10b3e01f3718a3713db4d22713c2d3943b11cabcc9078e49ceca02` |
| 源码绑定 / 门槛加载摘要 | `28aae43c4696db2bfdfd440bf974cdec5392c8c732314366a91407fb1f5ee8e7` / `7fa6f47a445f9643eb7f2e5ae78a72411007da38a56fca1082657870b2eab094` |
| 本轮 GO 文件 / 规范 SHA-256 | `909c1b2e6b5a862d6642288b89c36120807446ba0a7c35c65ada3614b5774007` / `426c82281fe5412d47e7eb1a72ff900b60552633ec277a959a4cbc5afc25fa71` |
| GO 生效 / 到期（UTC） | `2026-11-20T11:26:46+00:00` / `2026-11-20T14:26:46+00:00`（nonce 32 字符，值未打印） |
| 固定槽恢复后摘要 | `43e0f6229efeae77334e821b91548b7024a1aefdf5824a9586f4c8d12330aaad`（逐字节等于签发前原件） |
| 执行开始 / 结束（UTC） | `2026-11-20T11:26:46.8827767Z` / `2026-11-20T11:31:46.6295198Z`（**299.75 s**） |
| 执行退出码 | **0**（`status=succeeded`，`stop_code=null`） |
| 准入退出码 | **0**（`mktkb.p2.b0.admission.v0.1`，无 hard_failure / 无 unknown） |
| 实发 / 预留 / 结算 | 112 次出站 / 112 笔预留 / 112 笔结算（待结算 **0**） |
| 费用（保守＝供应商口径） | **5.7200466 元** ≤ 上限 7.464016 元；单请求峰值预留 0.500000 元 = 上限 0.50 元 |

## 2. 调额前检查（全部一致，0 处漂移）

- 分支/HEAD 与任务书一致；**9 项独立验收冻结件**与**33 项保护件**逐项摘要相同（`precheck/precheck_inputs.json`）。
- 计划双摘要、`build_b0_plan_binding` 原位重算、`pipeline_source_sha256=28aae43c…`、`corpus_sha256=9ea5a422…` 全部相等。
- `validate_b0_live_inputs` 通过：40 题（其中 8 道 OCR）、12 份入库来源、正式门槛 `7fa6f47a…`；候选目录 `var/eval/runs/p2-t209-b0-20261120-02` **事先不存在**。
- 该 run ID 在共享账本中的事件 **0 条**；账本 2,567 笔预留 / 2,567 笔结算 / 待结算 0；无 `.lock`。
- 与经理快照逐项相同：账本 `9a17f417…`、预算 `79b21700…`、旧 GO 槽 `43e0f622…`、历史前缀 `f4710b18…`、项目占用 `31.4446671`、P2 占用 `16.3737226`。

## 3. 同环境预检（签发新 GO 之前，与真实运行同一份进程环境）

- 隔离注入：先清空继承的 8 个供应商键与 1 个总限额键，再从工作区 `.env` 同源注入 7 个白名单变量；
  仅把有效 `MKTKB_MODEL_NAME` 锁定为 `deepseek-flash`，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=40.0`。值不打印、不落盘。
- 原生进程入口 `load_live_env()` 输出与期望逐值相等（退出码 **0**）：

```json
{"chat_model": "deepseek-flash", "chat_host": "api.deepseek.com",
 "embedding_host": "dashscope.aliyuncs.com",
 "ocr_region": "ap-guangzhou", "ocr_enabled": true}
```

## 4. 三项授权动作

### 4.1 获批调额（只改 `stages` 三项）

- 备份原字节：`budget/budget.before-amendment.json`，`79b21700…`（1738 B，逐字节相同）。
- 隔离位置验证候选：`_check_budget_payload` 返回 24.0、`preflight_p2.ok=true`、`center_remaining: ocr 5.70 ≥ 5.65`；
  同一计划用**未调额**预算仍然拒绝（`stage_allocation_below_plan`、`stage_budget_insufficient`），作为对照。
- 原子替换后读回：顶层仅 `stages` 变化，且仅三项变化 —— `P2-LIVE 20→24`、`P1-RETRIEVAL 3→0.5`、`later_shared_reserve 1.57→0.07`；
  各阶段合计 `39.97` ＋ 历史 `0.03` = **40.00**；`limit_cny`、历史占用与其余字段原样。
- 预算文件摘要：`79b21700…` → **`8f1b061b2c7845bb19be3ce7b839aa0d707384933a6974c86ce93b5210cf0ec0`**（变更时刻 `2026-11-20T11:26:44.393917+00:00`，规范摘要 `b2cff8a0…`）。
- 重取真实账本快照：`preflight_p2` **通过**；P2 阶段剩余 7.6262774、项目剩余 8.5553329、四中心剩余均 ≥ 本轮需求、待结算 0；账本与历史前缀未动。

### 4.2 本轮专属 GO

- 固定槽原字节先存档（`go/P2-LIVE-GO.before-t209-b0-attempt3-20261120T112646Z.archived.json`，`43e0f622…`，1306 B）；
  另有 11:24:33Z 一次干跑存档，内容逐字节相同。
- 候选先在隔离位置过完全部结构/范围/时间检查（`authorization` 196 字符 ≤ 200，nonce 32 字符）；
  `document=P2-LIVE-GO`、`schema_version=p2-live-go/v0.1`、`stage=P2-LIVE`；
  `budget_ledger_path` 固定共享账本、`budget_ledger_sha256=f4710b18…`、`budget_total_limit_cny=40`；
  `scope.stage_limits_cny={"P2-LIVE":24}`、`max_requests="unlimited"`、`max_request_cny=0.50`、
  四中心 `6.35 / 17.50 / 0.10 / 0.05`、六种计划操作。
- 原子写入固定槽后**从固定文件重读**并 `authorize_p2`：`production_ready=true`、plan/scope 一一匹配、
  阶段额度 24、阶段剩余 7.6262774、账本绑定历史前缀。
- 运行件内的 `gate.json.authorization` 记录了同一 GO 规范摘要 `426c8228…`、nonce 长度 32、生效/到期与四中心额度。

### 4.3 唯一一次真实运行

- 从仓库根目录、使用第 3 节同一进程环境，按任务书命令调用一次
  `p2-run --mode live --visibility public --run-id p2-t209-b0-20261120-02 …`；`p2_run_invocations=1`。
- 退出码 **0**，299.75 s，`status=succeeded`、`stop_code=null`、`production_ready=true`、`real_sends_allowed=true`。
- 运行门 8 项检查全 ok（`plan_identity / stage / not_expired / not_before_issue / operations / request_cap / production_ready / live_gate`），
  `artifact_validation.ok=true`，引用证据 `complete=true`（40 回合、49 条引用全部 verified）。
- 未重试、未并发、未续跑、未补题、未追加额度；`mock_intercepted=0`。

## 5. 执行实测

| 项 | 实测 |
| --- | --- |
| 题量 | 计划 40 / 执行 40 / 错误 0 / 未执行 0 / 跳过 0 |
| 回合 | 40 / 40，`with_product_result=40` |
| 分支 | `legacy` 16、`legacy_with_rag_candidates` 24（与 attempt2 相同） |
| 出站 | **112** = chat 40 ＋ embedding 36（query 24 ＋ index 12）＋ rerank 24 ＋ OCR 12 |
| 尝试回执 | 144 条（reserve+settle 成对）；`by_operation`：answer 40、index_embedding 12、query_embedding 24、rerank 24、ocr 12 |
| 模型/供应商 | `deepseek-flash`(deepseek)、`text-embedding-v4`/`gte-rerank-v2`(bailian)、`GeneralAccurateOCR`/`RecognizeTableAccurateOCR`(tencent) |
| 延迟 | min 522 ms / 中位 5018.5 ms / max 11720 ms / 合计 155.9 s |
| 失败轮 | 0（首个失败码 `null`，最后成功轮 `2026-11-20T11:31:46.309888Z`） |
| HTTP | 全部 200 |
| Token | 逐轮 usage 已入账本；run 级 `token_usage_json` 为空，不按 0 记 |

## 6. 账务与对账（逐笔）

| 项 | 运行前 | 运行后 | 增量 |
| --- | --- | --- | --- |
| 账本文件 SHA-256 | `9a17f417…` | `088dec5f9967ded2452b32e08ea0618277d7a7ce0fd806d6a3b5b03cb0473d44` | 追加事件 |
| 历史前缀 SHA-256 | `f4710b18…` | `f4710b18…` | **未变** |
| 预算文件 SHA-256 | `79b21700…` | `8f1b061b…` | 仅本轮获批调额 |
| 预留 / 结算 | 2,567 / 2,567 | 2,679 / 2,679 | **+112 / +112** |
| 待结算 | 0 | **0** | 0 |
| 项目占用（元） | 31.4446671 | 37.1647137 | +5.7200466 |
| P2 阶段占用（元） | 16.3737226 | 22.0937692 | **+5.7200466** |
| answer_retrieval | 4.5167346 | 4.5867812 | +0.0700466 |
| ocr | 11.8 | 17.45 | **+5.65** |
| judge | 0.056988 | 0.056988 | 0 |
| independent | 0 | 0 | 0 |

逐笔事件（本 run，224 条）：`reservations=112`、`results=112`、`unsettled=[]`、`status` 全 `succeeded`；
`reserved_cny=6.586448`、`conservative_charge_cny=5.7200466`；`plans_seen` 仅本轮计划，`stage_limits_seen=[24.0]`。

逐操作（预留 → 结算）：

| 操作 | 次数 | 预留（元） | 实结（元） |
| --- | --- | --- | --- |
| answer | 40 | 0.747520 | 0.062646 |
| index_embedding | 12 | 0.024576 | 0.0013595 |
| query_embedding | 24 | 0.049152 | 0.0000635 |
| rerank | 24 | 0.115200 | 0.0059776 |
| ocr | 12 | 5.650000 | 5.650000 |

### OCR 三种口径（分别报告）

| 口径 | 值 |
| --- | --- |
| 保守占用（账本） | **5.65 元**（12 次调用；预留峰值 0.50 元/次） |
| 基于用量的估算（`estimated_list_price_cny`） | **5.65 元**（12 次全部按批上限估） |
| 供应商实际账单 | **未知**（`provider_billed_cny=null`，未取得账单） |
| `run_result.by_center_cny.ocr` | `0.0`（逐请求实计口径；与账本保守口径不同，不做换算） |

## 7. 质量（38/40）

| 失败题 | 层 | 失败检查 | 证据 |
| --- | --- | --- | --- |
| Q25 | text | `value_hit` | 期望 3 个值，缺 `["领取时登记数量"]` |
| Q33 | ocr | `source_hit` | 期望 1 个来源，缺 index 0 |

- 其余 38 题全通过；精确题 24/24；OCR 8 题全部执行、7 通过（Q33 在此列）；无 `value_no_fabricated` 失败。
- **与 attempt2 的失败题、失败检查、分支分布完全一致**：本轮修复只改变 trace 版本绑定口径，未改变质量结果。

## 8. 准入（只读 `p2-admit`，与执行退出码分列）

```text
& .\.venv\Scripts\python.exe -B -X utf8 tools\rag_eval.py baseline p2-admit \
  --run 'var/eval/runs/p2-t209-b0-20261120-02/p2-run' \
  --gate-config 'docs/evaluation/gate_v0_3_approved.json'
admission exit = 0
```

| 项 | 值 |
| --- | --- |
| 执行 / 计分 | 40 / 40 |
| 通过 / 失败 / 错误 / 未执行 / 跳过 | 38 / 2 / 0 / 0 / 0 |
| 精确题 | 24 / 24 |
| OCR | 计划 8 / 执行 8 / 通过 7 |
| `min_sample` / `scored_count` | 32 / 40 |
| `real_calls` | 112 |
| 八项硬门禁 | `exact_value_contract=pass`、`citation_required=pass`、**`trace_integrity=pass`**，其余 5 项 `not_applicable` |
| `hard_failures` / `unknowns` | `[]` / `[]`，门禁 `exit_code=0` |
| 绑定 | `pipeline_version=d3ca88d2c515+28aae43c…`、`corpus_sha256=9ea5a422…`、`gate_config_hash=7fa6f47a…`、`go_sha256=426c8228…`、`ledger_sha256=f4710b18…` |
| 发布闸 | `p2_release_allowed=false`、`p2_release_status=blocked_pending_n_c_u_h2_evidence`（N/C/U/H2 证据 `unknown`） |
| 计算基线号（仅计算，未接收） | `baseline_id=7981d4afc2d1`、`evidence_sha256=2226fa20…` |

**attempt2 阻断根因已消除**：40 条 trace 的 `index_revision` **全部为 12**，与 `run_manifest.binding.index_revision=12`、
`manifest.index_revision=12` 逐条相等；`binding.complete=true`、`trace_identity_bound=true`、`missing=[]`。

## 9. GO 封存与固定槽恢复

- 封存本轮 GO 原字节：`go/P2-LIVE-GO.t209-b0-p2-t209-b0-20261120-02.attempt3.sealed.json`
  （`909c1b2e…`，1384 B，canonical `426c8228…`），与候选载荷规范摘要相同。
- 恢复前复核绑定：`plan_id`、`plan_sha256`、`stage_limits_cny={"P2-LIVE":24}`、nonce 32 均属本轮。
- 按签发前副本原子恢复固定槽：现摘要 **`43e0f6229efeae77334e821b91548b7024a1aefdf5824a9586f4c8d12330aaad`**，
  `readback_document=P2-LIVE-GO`、`readback_scope_plan_id=P2-H2V3-20261115-r3-post_v05_without_v01`，无临时文件残留。
- 预算**保持本轮获批额度**（24 / 0.5 / 0.07），未清账、未回拨；账本追加事件原样保留。

## 10. 原始运行件与 trace 归档

原始 run 目录：`var/eval/runs/p2-t209-b0-20261120-02/p2-run`；归档副本：`var/eval/t209-prep/b0-live-20261120-attempt3/run-artifacts/`（逐份逐字节相同）。

| 工件 | 字节 | SHA-256 |
| --- | --- | --- |
| `run_manifest.json` | 244863 | `30b0c6ef62379b2a651341859b8f348367ba1c038ff97b80281df9aa0f70044b` |
| `summary.json` | 206237 | `feb6fd150189a3944e3c6286495fd11e6ff51fe29be5f81977fcf726d2f6a949` |
| `dataset.jsonl` | 28943 | `264ce1f019e5ac9be0265676e9b9cd1aa6ce1598e3e87a0bc7d8b73f3f0dcee1` |
| `cases.jsonl` | 190485 | `165e31d640c5072a49248bb39bb862242349e22c1e4c52e26fdbc77a1553892f` |
| `requests.jsonl` | 52265 | `415c657698456605b0875a7e1a2c2697cdc4fca4635dd626ee15af30fe99d12e` |
| `gate.json` | 103968 | `b64c7709fb384a65f84427da4ac25d2086155e1a5cd65e7ab02f8b2ed213cd39` |
| `run_result.json` | 978 | `4c6e71ea729f1a1c7e8f0adddb019ecd3f09030104b26385b80c0d24dc90357f` |
| `data/observability/qa-traces.sqlite3` | 229376 | `cd46785bd2b1b271332c56068c682e9230d6fba4add83ce70575ae6374fdac08` |

Trace 归档校验：

- 主库旁文件：`-wal` 0 B（已 checkpoint，主库自包含）、`-shm` 32768 B，均已随 `trace-native/` 一并保全并核对摘要。
- 另用 SQLite backup API 从**只读源**导出独立副本 `qa-traces.standalone.sqlite3`（`cfc96bc9…`），不依赖任何旁文件。
- 独立只读连接查询 `traces` 表：3 张表（`schema_meta`/`spans`/`traces`）、**40 行**、`legacy 16 / legacy_with_rag_candidates 24`、
  `index_revision` 全 12、`status` 全 `ok`，`trace_ids` 聚合摘要 `e3e01630…` 与源库一致。
- 产品实际 trace 版本 `mktkb.trace.v0.1`；`content_mode=hash`；纯 legacy 与使用 RAG 的两条路径均纳入对照，数量与 `summary.branches` 一致。

## 11. 偏差与自证（详见 `logs/deviations.md`）

1. **11:25:32Z 入口编码导致启动即止**：`.ps1` 以 UTF-8 无 BOM 保存、由 PowerShell 5.1 以 ANSI 解码，预检调用输出被判空。
   该次**未执行预检、未改预算、未动 GO 槽、未调用 p2-run**（0 请求 0 预留 0 元，入口自身前后摘要完全相同）。
   处置：改为 UTF-8 BOM + 空值安全拼接，并以 `-PreflightOnly` 演练通过后重跑。
2. **11:31:48Z 首次封存判定失败**：归属比较用文件字节，候选文件 CRLF 与固定槽 LF 不一致，导致误判“非本轮占用”、未恢复。
   期间槽仍持有**本轮** GO（运行已结束、无新增发送）。处置：改用规范载荷摘要判定 + 恢复前绑定复核，
   11:32:17Z 重跑封存并成功恢复 `43e0f622…`；同时把候选文件写入改为 LF。
3. 重定向日志由 UTF-16LE 归一为 UTF-8（内容未改）。
4. 全程只发出**一次** `p2-run`；未重试/续跑/补题/扩额；未改生产源码、仓内测试或 Git 跟踪内容；未打印任何凭据或 nonce 值。

## 12. 结果与后续（交回经理）

- 执行 `COMPLETE`：40/40、112 次出站、5.7200466 元（≤ 7.464016）、112/112 结算、零悬账、零重试。
- 准入 `PASS`：38/40 ≥ 36、精确 24/24、OCR 执行 8/8、八项硬门禁按适用性成立、`trace_integrity` 由 fail 转 **pass**。
- 费用与额度现状：P2 阶段占用 22.0937692 / 24（剩 **1.9062308**）、项目占用 37.1647137 / 40（剩 **2.8352863**）、
  OCR 中心剩 **0.05**。因此同一计划**已不能再跑一次真实运行**（`preflight_p2` 现报 `stage_budget_insufficient`、
  `total_budget_insufficient`、`center_budget_insufficient:answer_retrieval`、`center_budget_insufficient:ocr`）。
- 待经理决定：独立复核安排；正式基线接收（`p2-approve`，本轮未执行，`baseline_id` 仅为计算值）；
  P2 发布（仍 `blocked_pending_n_c_u_h2_evidence`）；H2 与 T900 沿用各自审批流程。
- 需要新一轮真实运行或调额时，请按原流程另行授权；本轮不自行扩额。

## 13. 证据路径

`var/eval/t209-prep/b0-live-20261120-attempt3/`（仓库内，git 忽略；全部 UTF-8）：

| 路径 | 内容 |
| --- | --- |
| `run-once-attempt3.ps1` | 单进程入口：清同名键 → 同源注入 → 环境预检 → 调额 → 签发 GO → 唯一一次 `p2-run` → `finally` 封存/恢复（含兜底恢复） |
| `amend_budget.py` / `mint_go.py` / `seal_go.py` / `reconcile_and_archive.py` / `diagnose_admission.py` | 调额、签发、封存、对账归档、只读诊断 |
| `precheck/precheck_inputs.py` / `precheck_inputs.json` | 调额前检查（分支/HEAD、9+33 冻结件、计划双摘要、正式输入、账本/预算/GO 快照、preflight） |
| `precheck/rehearse_mint.py` | GO 合同排练（`_check_go_payload` 全套检查，未写槽） |
| `budget/budget.before-amendment.json` / `budget/amend-budget.json` | 调额前原字节（`79b21700…`）与调额证据 |
| `go/P2-LIVE-GO.before-*.archived.json` | 签发前旧槽原字节（两份，均 `43e0f622…`） |
| `go/P2-LIVE-GO.candidate-*.json` | 候选 GO（干跑 + 正式） |
| `go/P2-LIVE-GO.t209-b0-p2-t209-b0-20261120-02.attempt3.sealed.json` | 本轮 GO 封存原件（`909c1b2e…`） |
| `logs/env-preflight.txt` | 同环境预检输出 |
| `logs/amend-budget.txt` / `logs/mint-go.txt` | 调额（含隔离验证、读回差异、preflight）与签发/读回授权 |
| `logs/p2-run.stdout-stderr.txt` / `logs/attempt3-run.meta.json` | 真实运行输出；起止时间、耗时、退出码、前后摘要、close_check |
| `logs/seal-go.retry.stdout.txt` / `logs/seal-go.json` | 封存、恢复、逐笔对账、逐操作与工件摘要 |
| `logs/reconcile.json` / `logs/reconcile.stdout.txt` | §5 对账、OCR 三口径、版本绑定、trace 归档校验 |
| `logs/p2-admit.stdout-stderr.txt` | 只读准入原始输出（退出 0） |
| `logs/diagnose-admission.json` | 复算评分、逐题状态、八项硬门禁 |
| `logs/deviations.md` | §11 偏差自证 |
| `run-artifacts/` | 七份原始工件 + `qa-traces.sqlite3` + `trace-native/`（含旁文件）+ `qa-traces.standalone.sqlite3` |
