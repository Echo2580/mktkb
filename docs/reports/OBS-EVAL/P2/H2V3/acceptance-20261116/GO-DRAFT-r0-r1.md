# H2 受控诊断新 GO —— 待确认草案（r0 / r1）

- 版本：draft-20261116-02（2026-11-16 更新：范围与代签归属已获主人批准）
- 出具：独立验收负责人（依据主人“编写新 GO”的授权出具草案）
- **状态：未签发、未生效、不可放置于固定槽位、不得执行。**
  - ✅ 范围已批准、代签归属已批准 → 见 `OWNER-APPROVAL-20261116.md`（2026-11-16）。
  - ⛔ 本草案**仍未绑定任何新计划**（新 `plan_id` / `plan_sha256` 尚未由保管角色生成）；在计划回执到达前不得签发。
  - `issued_by` 按授权记为 `PM (lead) — delegated by owner 2026-11-16 (scope: r0+r1 diagnostic)`；`nonce`、`issued_utc`、`expires_utc` 仍待签发时填写。
  - 草案只写在本目录，**未**写入 `docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json`，未归档/覆盖任何旧 GO。
- 判定依据：`ACCEPTANCE-REPORT.md`、`CONTROLLED-DIAG-PROPOSAL.md`、`PM-DIAG-REVIEW.md`，以及我直接读取的 `backend/src/mktkb/evaluation/p2_authorization.py` 与 `tools/p2_h2_v3_controlled_execute.py`。

---

## 1. 为什么现在只能出草案

| 前置 | 现状 | 缺什么 |
|---|---|---|
| 主人确认诊断范围 | ✅ **已批准（2026-11-16）** | — |
| 新私有计划 | **不存在** | 保管角色用当前工作树执行 `plan-private`，产出新四场景计划集与 r0/r1 绑定（请求单见 `CUSTODY-PLAN-REQUEST-20261116.md`） |
| 计划安全摘要 | **未知** | 新 `plan_id`、`plan_sha256`、`code_version`、`total_requests`、`stage_limit_cny`、成本中心分配 |
| 签发人 | ✅ **已批准代签**：`PM (lead) — delegated by owner 2026-11-16` | 仍须等计划回执后才可落笔 |
| 固定槽位 | 当前是 **r3 计划**（`P2-H2V3-20261115-r3-post_v05_without_v01`） | 换入前须按既有命名归档现槽位件，不得直接覆盖 |

> 只生成四份计划 ≠ 授权四次执行；r1 的 pending 文件 ≠ r1 已在实际固定槽位获授权。

---

## 2. 当前代码 schema 事实（我逐条核过）

来源：`p2_authorization.py`（`_GO_KEYS`/`_GO_SCOPE_KEYS`/`_check_go_payload`/`P2Gate._assert_authorization_live`）、`tools/p2_h2_v3_controlled_execute.py`。

- 顶层字段**必须恰好**是：`document`、`schema_version`、`stage`、`authorization`、`issued_by`、`nonce`、`issued_utc`、`expires_utc`、`budget_ledger_path`、`budget_ledger_sha256`、`budget_total_limit_cny`、`scope`。**多一个字段即 `field_unknown` 拒绝**（因此不存在也不得发明 `max_new_requests`、`max_new_cny` 等）。
- `scope` 必须恰好是：`plan_id`、`plan_sha256`、`operations`、`cost_centers_cny`、`stage_limits_cny`、`max_requests`、`max_request_cny`。
- `document` 必须是 `P2-LIVE-GO`；`schema_version` 必须是 `p2-live-go/v0.1`；`stage` 必须等于计划 stage `P2-LIVE`。
- `nonce` 字符串 ≥16 字符、不得含空白；`issued_utc`/`expires_utc` 必须带时区且 `expires > issued`，执行时 `issued ≤ now < expires`。
- `budget_total_limit_cny` 必须等于计划的项目总上限（当前 40）。
- `budget_ledger_path` 必须解析到固定共享账本 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl`。
- `budget_ledger_sha256` 只接受两种值：①当前账本整文件 SHA，②账本**不可变历史前缀** SHA（开头连续 `historical_import` 行）。**实际必须用 ②**：一旦本次运行追加记录，①立即失效，会在中途被 `ledger_prefix_mismatch` 拒。
  - 我实测：前缀 SHA = `f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014`（可用）；整文件 SHA 现值 = `e007fee3…`（签发后一追加即失效）。
- `operations` 必须是已注册操作的非空数组，且必须覆盖计划的全部操作；本诊断只允许：`answer`、`index_embedding`、`query_embedding`、`query_expansion`、`rerank`（不含 OCR/judge/independent）。
- `cost_centers_cny` 必须**恰好含四个中心**且每个为正、且不低于计划分配：`answer_retrieval=8.5`、`ocr=6.5`、`judge=3.0`、`independent=2.0`。
- `stage_limits_cny` 必须含 `P2-LIVE` 且 ≥ 计划阶段额度（当前 20）。
- `max_requests` 必须：整数、≤ `HARD_MAX_REQUESTS=1500`、≥ `plan.total_requests`、且 **≥ `plan.max_requests`**。
- `max_request_cny` 必须 ≥ 计划单次峰值预留（当前画像 0.018688），实际授权值 0.5。
- **关键推论**：`plan-private` 强制 `--max-requests == 1500`，计划里 `max_requests` 即 1500；GO 又必须 ≥ 计划 `max_requests`、≤1500 → **GO 的 `max_requests` 只能是 1500**。因此**无法**用 GO 表达“累计新增 ≤115”的独立子预算；机器硬闸仍是累计 1500。这一点与 `CONTROLLED-DIAG-PROPOSAL.md` 一致。

---

## 3. 草案字段（r0）

| 字段 | 草案值 | 说明 |
|---|---|---|
| `document` | `"P2-LIVE-GO"` | 固定 |
| `schema_version` | `"p2-live-go/v0.1"` | 固定 |
| `stage` | `"P2-LIVE"` | 固定 |
| `authorization` | `<待主人/经理拟定>`（示例：`Owner YYYY-MM-DD approval: H2 v3 diagnostic r0 only (base_b0); 40 CNY total; 1500 cumulative; 0.5/request; 5 ops only; zero retry`） | 文本，不得写成已批准除非确已批准 |
| `issued_by` | `<待签发人填写>` | 不得由验收角色代填为“Owner” |
| `nonce` | `<签发时随机 32 hex>` | 不得预设/复用旧 nonce |
| `issued_utc` | `<签发时刻 ISO8601 带时区>` | |
| `expires_utc` | `<签发时刻 + 有效期，建议不晚于 2026-11-30T23:59:59+08:00>` | 必须晚于 issued，且覆盖本次诊断窗口 |
| `budget_ledger_path` | `"docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"` | 固定 |
| `budget_ledger_sha256` | `"f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014"` | **历史前缀**；若签发时代码/账本规则变化须重算 |
| `budget_total_limit_cny` | `40.0` | 必须等于计划项目总上限 |
| `scope.plan_id` | `<新 r0 plan_id>` | 由 `plan-private` 生成 |
| `scope.plan_sha256` | `<新 r0 plan_sha256>` | 必须与计划重算一致 |
| `scope.operations` | `["answer","index_embedding","query_embedding","query_expansion","rerank"]` | 不含 OCR/judge/independent |
| `scope.cost_centers_cny` | `{"answer_retrieval":8.5,"ocr":6.5,"judge":3.0,"independent":2.0}` | 若新计划分配更高，只能上调 |
| `scope.stage_limits_cny` | `{"P2-LIVE":20.0}` | ≥ 计划阶段额度 |
| `scope.max_requests` | `1500` | schema 决定的唯一可行值 |
| `scope.max_request_cny` | `0.5` | ≥ 计划峰值预留 |

**r1 草案**：除以下三项外同上——`scope.plan_id`/`scope.plan_sha256` 换成新 r1 计划；`nonce` 重新生成；`authorization` 改述为 r1（`base_b0_plus_v01`）。r1 的 GO 先以 `P2-LIVE-GO.v3-r1.pending.json` 形式存在，**执行前**须按既有流程把其换入固定槽位（并归档原槽位件）。

---

## 4. 范围与预算（待主人确认的具体内容）

| 项 | 值 | 备注 |
|---|---|---|
| 场景 | r0 `base_b0` + r1 `base_b0_plus_v01`，各**至多一次** | 入口无按题/按回合选择；四案只是诊断关注面 |
| 题/回合 | 20 题 / 24 回合 | r0 12/14，r1 8/10 |
| 计划请求上界 | r0 65、r1 50，合计 **115** | 计划项上界，非独立机器硬闸；实际下界可为 0（预检/首错拒绝） |
| 累计请求 | 当前 1273，花满后 **1388/1500**，余 **112** | 不足以再跑历史约 126 请求的一轮全量 |
| 费用计划上界 | r0 0.637568、r1 0.462720，合计 **1.100288 元** | 按现行代码画像静态上界，非供应商报价 |
| 单请求峰值 | **0.018688 元** | < 0.5 单笔上限 |
| 预算边界 | 项目 40、阶段 20、单请求 0.5 | 不改 `budget.json` 与成本中心分配 |
| 成本中心余量 | `answer_retrieval` 6.8243499；`ocr` 0.35；`judge` 3.0；`independent` 2.0 | 我按账本独立重算；两 run 只需 `answer_retrieval` |
| 操作 | 仅 `index_embedding`、`query_embedding`、`rerank`、`query_expansion`、`answer` | 不 OCR、不 judge、不 independent |
| 停止 | 任何异常**首错停**，不自动重试；不执行 r2/r3 | |

---

## 5. 签发前置条件（缺一不可）

1. ✅ **主人已书面确认第 4 节范围**（2026-11-16，见 `OWNER-APPROVAL-20261116.md`）。
2. 保管角色用**当前未提交工作树**执行：
   `plan-private --root <仓外受控根> --key-file <保管侧 key> --out-dir <仓外新目录> --created-utc <有效时刻> --max-requests 1500`
   并确认计划绑定：当前工作树代码摘要（非仅 HEAD）、数据/场景、run/date、`index_revision=pending_post_ingest`、index 批次 9/10/13/15。
3. 保管角色回传**最小安全元数据**（见 §6），我或经理据此填写 `plan_id`/`plan_sha256`/`total_requests`/成本中心/阶段额度。
4. 签发人填写 `authorization`/`issued_by`/`nonce`/`issued_utc`/`expires_utc`，生成两份 GO。
5. 放置：r0 GO → 固定槽位（先按既有命名归档当前 r3 GO）；r1 GO → `P2-LIVE-GO.v3-r1.pending.json`。
6. 逐 run 预检 `check-only`（r0：`--run-index 0`；r1：先 `--run-index 1` 检查 pending，执行前仍须换槽），确认代码/计划/GO/账本/预算/成本中心/有效期一致后才可发送；任何不一致**不执行**。
7. r0 完成后**重读账本**、重新核算 r1 的 `worst_case_cny` 与中心余量、重新核验 r1 GO；不通过则不执行 r1。

> 上述任一步骤未完成，本草案保持“草案”状态。代签人**只能在** `OWNER-APPROVAL-20261116.md` 所述范围与归属内落笔；**不得**预填 nonce 或猜填 `plan_id`/`plan_sha256`，**不得**在计划回执到达前放槽位。

---

## 6. 需要保管角色回传的最小安全元数据（不猜填）

| 字段 | 用途 |
|---|---|
| 新 `plan_id`（r0、r1） | GO `scope.plan_id` |
| 新 `plan_sha256`（r0、r1） | GO `scope.plan_sha256` |
| `total_requests`（每 run） | 校验 GO `max_requests` 下限 |
| `stage_limit_cny`、`cost_centers_cny`（每 run） | 校验 GO 成本中心/阶段额度下限 |
| `project_total_limit_cny` | 校验 40 |
| `code_version` 摘要 + 生成时刻 | 证明计划绑定当前工作树 |
| `ingest_plan_sha256`、各场景 index 批数 | 证明 9/10/13/15 绑定 |
| run/business_date（r0 2026-10-15、r1 2026-07-15） | 证明 run/date 一致 |
| 计划生成时的账本前缀 SHA | 校核 `budget_ledger_sha256` 仍为历史前缀 |

以上只含哈希/标识/金额，不含题面、答案、实体值、key。

---

## 7. 明确不能声称的内容

- 不能声称“已签发/已生效”——本草案未绑定计划、未放槽位（范围虽已批准，签发仍待计划）。
- 不能声称“已授权执行真实请求”或“可以立刻开跑”——仍缺新计划、GO 与预检。
- 不能声称“新增请求硬闸 115”或“新增费用硬闸 1.100288”——机器硬闸只有累计 1500 与 40/20/0.5。
- 不能声称“两 run 可得出新 30 题成绩”或“可与旧 r2/r3 拼分”。
- 不能声称“诊断通过 = T207 通过 / 硬失败清零 / P2 完成”。
- 不能声称“历史官方组合卡已恢复”。

---

## 8. 草案模板文件

- `GO-DRAFT-r0.template.json`、`GO-DRAFT-r1.template.json`：与 schema 同形，占位符故意非法（`PENDING-…`），**不可**直接安装；仅用于签发时逐字段替换。
- 校验方式：签发后以 `check-only` 触发 `_check_go_payload`；任何 `field_unknown`/`go_plan_sha256_mismatch`/`ledger_prefix_mismatch` 均须按首错停处理，不得放宽。
