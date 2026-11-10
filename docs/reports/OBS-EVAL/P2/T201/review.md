# P2-T201 独立验收（review）

- 对象：T201 请求计划 / 资金 / 授权门 + Mock 证据。开发自述 `docs/reports/OBS-EVAL/P2/T201/report.md`（只当线索）。
- 现场：分支 `codex/p2-e2e`，HEAD `59107fc1c2de58ed83cee62bee39f3fde28995f1`，0 提交；我未 commit/push。
- 我的实测入口：`evidence/verify/` 4 个（`probe_t201.py`、`probe-output.txt`、`pytest-verify.log`、`verify-hashes.txt`）。
- **结论：T201 通过，建议经理接收**（附 6 条非阻断建议、2 项 NOT-RUN）。不代表 P2 整体通过，也不代表候选可作授权。

## 逐条判定

| # | 验收项 | 判定 | 我的实测与证据 |
|---|---|---|---|
| 1 | 候选与授权边界：总额 20→40、P2-LIVE=20、历史 15.0709445 与 505/505 保留、四中心合计=阶段额度、标 DRAFT、无可用授权、production_ready=False、固定 P2 GO 未创建 | **PASS** | 探针 `candidate_*` 6 项：`0+0+15.4+3.0+1.57+20.0=39.97`，+历史 0.03=40.00；旧阶段逐值未变；中心 12/3/3/2 合计 20，无一中心等于 20；`authorize` 得到 `production_ready=False`、`stage_remaining=20`、`total_remaining=24.9290555`（阶段硬顶先于总额生效，旧剩余 4.9290555 不能当 P2 的钱）；`PM/P2-LIVE-GO.json` 不存在（`load_go_payload`→`path_missing`） |
| 2 | 拒绝链：旧 P1 GO/错 stage/未授权 operation 或 center/预算不足/超累计请求/同 nonce 改 plan/账本前缀变化/过期/缺身份/路径替换或软链 → 发送前拒绝、HTTP=0、reserve=0 | **PASS** | 探针：预检 8 类稳定原因码逐一对齐；GO 侧 21 组拒绝（含**真实** `PM/S2-LIVE-GO.json`→`legacy_go_document`）；budget/env 6 组；`go_plan_sha256_mismatch`（同 nonce 换计划）、`go_ledger_binding_mismatch`（改历史行）、`path_not_fixed`、`snapshot_ledger_path_not_fixed`。全部断言 `reserved` 行不变、假发送 0 |
| 3 | reserve 后发送前失效：保守留账、保留 request/plan/cost_center、不谎称 0 | **PASS** | 探针 `gate_reserve_then_invalidate_is_conservative`：result `status=failed`、`error_code=P2_PRE_SEND_REFUSED:authorization_expired`、`conservative_charge_cny=0.018688`（= 预留额），reservation 行保留 `cost_center=answer_retrieval` 与 `metadata.plan_id/plan_sha256`；`stage_accounted=0.018688` 未被清零；`result()` `requests_sent=0`、`settled_cny=0.018688`。另测 `plan_sha256_changed`/`ledger_prefix_mismatch`/`operation_unauthorized` 三种发送前失效，同样保守 |
| 4 | 数值与运行时门控：bool 当 int、NaN/Inf/负数、缺单价/token 上界、单笔/中心/阶段/总额超限、跨 kind 累计、串行、自动重试 0、不能换模型或中心绕过 | **PASS** | 探针 18 组 plan 构造期拒绝（bool/NaN/Inf/负价/0 价/缺 cap/缺输出价/cap 写小/错 stage/中心合计不符/**四中心各 20**/1500 请求/估价越界/OCR 页号）；运行时：`request_inflight`、`gate_stopped`（失败后零重试）、`request_limit`（999 条跨 chat/embedding/ocr 混排后到 1000 拒绝）、`center_budget_exceeded`、`stage_budget_exceeded`、`center_accounting_inconsistent`；`begin()` 仅接受 `item_id`（无模型/中心参数），换中心/换模型在计划构造期即 `cost_center_mismatch`/`price_model_invalid`；P2 模块无 retry/backoff/sleep 标记 |
| 5 | 不回退旧行为：P1 retrieval-only/零 chat、旧授权负例、无生产依赖/业务 API/schema 变化、旧 GO 不能拿 P2 权限 | **PASS** | 受影响旧用例（12 文件 + P1 `test_live_runner.py`）**187 passed**；`live.LIVE_SCOPE=="retrieval_only"`、`ALLOWED_SERVICES==("rag","chat")`，`load_live_authorization(stage="P2-LIVE")`→`LiveGateError`，`refresh_request_limits` 仍走 `load_live_authorization`；git diff 仅 `live_authorization.py`（新增拒绝，未放松）与 `rag/budget.py`（可选参数/附加字段），无 pyproject/requirements、无 schema/migration、无 API 响应模型改动；`answer.py` 的 `diagnostics.budget` 未进 API 层，新增键仅附加 |
| 6 | 真实请求=0 与完整性：复算账本/budget 起止 hash 与行数、文件 hash 与 report/verify.json 一致、无新 reserve、无固定 P2 GO、无 .lock 残留 | **PASS** | 账本 `1f46d1b9…fde7390` 前后一致、1011 非空行、505 reserved / 505 result；我用"逐 reservation 取 result.conservative_charge_cny"独立复算 = 15.070944499999985（+历史 0.03），历史前缀 `f4710b18…a014`；budget `084ba9ac…cc58`、limit 20、无 P2 阶段；12 个文件 hash 与 `verify.json` **12/12 OK**；`docs/evidence` 下无 `P2-LIVE-GO*`；budget 目录仅 2 个文件（无 .lock） |
| 7 | §6.2 接口确已冻结、可供下一包调用 | **PASS** | `P2RunPlan/P2PreflightResult/P2Authorization/P2RunResult` + `P2RequestItem/P2PriceProfile/P2LedgerSnapshot`；`preflight_p2(plan, snapshot)`、`authorize_p2(plan, *, go_payload, budget_payload, ledger_snapshot, now)`、`P2Gate.open/begin/confirm_before_send/settle_success/settle_failure/result`；5 个 schema_version 与契约文档 §3–§7 一致；调用约定（T203/T204/T205/T208）已写入契约 §9 |
| 8 | 路径与 symlink | **NOT-RUN**（仅代码审读） | 本机 `os.symlink` 被拒（WinError 1314，无权限）→ 无法实测 `path_symlink` 分支；路径替换已实测 `path_not_fixed`。判据代码 `p2_authorization.py:227-242` 先判 `is_symlink()` 再比 `resolve()` |
| 9 | 浏览器 / 真实 provider / 全仓 backend/tests | **NOT-RUN**（本包范围外） | 本包零真实调用、未跑全仓；这三项属 T900/T206 |

## 非阻断建议（可复现，但均需越界条件；不改变上面的 PASS）

1. **内存 GO 仍能往固定账本写预留**（探针 `in_memory_go_can_still_reserve_on_fixed_ledger`）：`production_ready=False` 但 `begin()` 成功落 reserved。契约 §2 要求 runner 硬断言 `production_ready`——**请把它写成 T203 的验收条件**（或在 `begin` 加同等护栏）。
2. **中心标签未注册时门控只校验合计**：复现——门控打开后追加一行 `reserve=2.6, cost_center="bogus_center"`，ocr 中心仍显示有余量，再放行 0.5，实际 ocr 归属达 3.1 > 3.0。需要直接写账本权限（同权限者可伪造 result，故超本包威胁模型）。修复目标：`_assert_center_accounting` 增加 `set(centers) ⊆ COST_CENTERS`，与"阶段占用必须可完整归属"一致。
3. **共享预算的总额算术未校验**：`_check_budget_payload` 只比 `limit_cny`、阶段分配与历史，不校验 `Σstages + history == limit`。候选文件本身正确（我已复算），但正式预算落盘前建议补该校验。
4. `P2Gate.open` 用私有属性把门控回调注入 `BudgetLedger`（`budget.py:245` 已有同名构造器参数）——建议改构造期注入，去掉反向依赖。
5. `gate.result()` 在零请求时返回 `status="succeeded"`（`stop_code=None`）；T203/T205 需显式区分"没跑"与"跑成功"。
6. 报告 §6 措辞：`usable_authorization/production_ready` 不是 GO 文件字段（严格 schema 不允许），它们是授权结果的属性——文档表述可再精确一点。

## 待确认（不影响本包判定，交经理）

- 候选中心仍是 §4.1 的 12/3/3/2，而 T204 的 12 页 OCR 需 6.00 元；`.claude/handoffs/_index.md` 已记经理决定改为 9/6/3/2。**需在 T206 正式 GO/预算落盘时同步**，候选文件与契约 §1 示例届时一并更新。
- `MAX_GO_REQUESTS` 本包正确保持 1000（`HARD_MAX_REQUESTS`）；§12 的"T206 提至 ≤2000"未落地，属预期。

## 复现命令

```
.\.venv\Scripts\python.exe -B docs/reports/OBS-EVAL/P2/T201/evidence/verify/probe_t201.py   # 31 checks, exit 0
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_p2_authorization.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t201-verify   # 69 passed
# 另 12 个受影响旧文件 + test_live_runner.py：187 passed（见 pytest-verify.log）
```

## 边界声明

- 我只写了 `docs/reports/OBS-EVAL/P2/T201/review.md` 与 `evidence/verify/`；未改源码/测试/开发报告/candidates/管理文档，未碰 `docs/面试/`、`.env`、H2/Holdout、真实预算-GO-账本，未安装依赖、未 commit/push。
- 探针全程禁用 socket（`connect/connect_ex/create_connection/getaddrinfo`），所有 P2 场景在系统临时目录副本中跑，真实账本/budget 只读且前后 hash 一致。
