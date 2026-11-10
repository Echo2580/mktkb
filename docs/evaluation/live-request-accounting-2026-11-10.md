# Live 请求计数口径说明（2026-11-10，P1-F）

> 目的：解释 review §7 #56 的「GO 计划 7/4 vs T111 实际 17/10、T112 39/31」口径差。
> 结论：**不是 GO 违规，也不是「声明未执行」的运行期约束**——这是两类不同语义的计数：
> `scope.bindings.rag.embedding_requests/rerank_requests` 是 **J2 受控计划值**（不约束 P1 live
> 检索路线），P1 路线的运行上限是 `scope.max_requests`（累计 1000）+ 阶段额度 3.0 元。
> 本文件只做口径说明；不修改、不重签任何 GO/预算/账本/历史证据，也不改代码语义。

## 1. 五类计数口径

| # | 口径 | 定义 | P1 live 检索路线的实际取值 | 执行/证据 |
| --- | --- | --- | --- | --- |
| 1 | **计划值** | 预算方案里「准备花多少次请求/多少钱」的**计划**，不是实测，也不是上限 | GO bindings 的 12 个 J2 计划字段：embedding 7 / rerank 4 / OCR text 1 / OCR table 1（另 chat 2 在旧 GO 里），合计 15 次，plan stage=S2-DEV | `docs/evidence/LOCAL-R1-20261101/PM/S2-LIVE-GO.json:21-33`；`backend/src/mktkb/controlled_execution.py:140-157,285-317,379-444` |
| 2 | **运行上限** | 授权允许的真实请求/金额硬顶，超限必须**在发请求前**拒绝 | `scope.max_requests=1000`（累计，跨 kind/stage/run）；`scope.max_request_cny=0.05`；阶段 3.0 元；总上限 20 元 | GO `:14-18`；`live_authorization.py:539-547,614-625`；`rag/budget.py:555-569`；`refresh_request_limits` `live_authorization.py:720,741-747` |
| 3 | **实际请求** | 真正发生的供应商 HTTP 尝试次数；每次尝试=1 条 `reserved` 账本事件（零重试） | T111 两次运行各 27（17 embedding+10 rerank）；T112 70（39+31）；P1-RETRIEVAL 累计 124 = 27+27+70 | 计数在 POST 前：`rag/providers.py:329-350`（reserve→复核→`_record_post_attempt`→post）；账本事实 `rag/budget.py:431`；run summary `runner.py:1179-1181` |
| 4 | **预留** | 每个请求在发送前按「可证明最坏上界」冻结的金额 | embedding 0.04096 元（81,920 token×价）/ rerank 0.024 元；写入 `reserved` 事件 | `evaluation/live.py:295-305`；`rag/budget.py:580-602`；未结算时按预留计占用 `budget.py:396-400` |
| 5 | **结算** | 请求结束后写入 `result` 事件的实际/保守扣费；全项目 `provider_billed_cny` 仍为 null | legacy 口径 `max(预留, 声明 charge)`；versioned（`usage-conservative-v1`）独立重放 usage 后重算 | `rag/budget.py:390-400,436-479`；run 前后差 `runner.py:1102,1179,1201-1203` |

要点：**计划值 ≠ 运行上限 ≠ 实际请求**。P1 live 的审计基线是口径 2/3/4/5（累计 505/1000、
阶段 0.0143149/3.0、总 accounted 15.0709445/20、绝对差 0.0143149 元），不是计划值 7/4。

## 2. GO 字段逐项语义（是否约束 P1 live 检索路线）

| GO 字段 | 语义 | 约束 P1 live？ | 执行点（文件:行） |
| --- | --- | --- | --- |
| document/stage/authorization/issued_by/nonce/issued_utc/expires_utc | GO 身份与有效期 | 是（构造期） | `live_authorization.py:499-520` |
| budget_ledger_sha256 | 绑定共享账本不可变历史前缀 | 是 | `live_authorization.py:524-526,408-421` |
| scope.services=["rag"] | 允许服务 | 是 | `live_authorization.py:531-538` |
| scope.stage_limits_cny.P1-RETRIEVAL=3.0 | 阶段额度（与环境请求值、预算分配取最小） | 是 | `live_authorization.py:539-543,614-619,717-719` |
| **scope.max_requests=1000** | **累计请求硬顶（跨 kind/stage/run）** | **是** | `live_authorization.py:544-546,617,720`；`rag/budget.py:555-558` |
| scope.max_request_cny=0.05 | 单请求上界（绑定请求预留上界） | 是 | `live_authorization.py:547,620-625,723-727`；`rag/providers.py:320-321,643-644` |
| bindings.rag 的 provider/model/host/region/dimensions/settlement_version | 供应商来源绑定（12 键） | 是 | `evaluation/live.py:315-335`；`live_authorization.py:307-335`（只核对显式传入键） |
| bindings.rag.plan_version / request_plan_sha256 / serial / embedding_requests=7 / rerank_requests=4 / ocr_* / token caps | **J2 受控计划的计划值**（`s2j2-controlled-plan-v1`） | **否**（P1 路线不消费） | 仅形状/敏感校验 `live_authorization.py:266-304`；J2 路线严格核对 `controlled_execution.py:362-376,379-444,1149-1159` |

### 依据 A：7/4 可由 `request_plan_sha256` 反解为 **S2-DEV 的 J2 计划**

只读复算（零调用、零写入）：

```text
ControlledRequestPlan(stage="S2-DEV", chat_requests=2, embedding_requests=7,
                      rerank_requests=4, ocr_text_requests=1, ocr_table_requests=1)
  request_plan_sha256 = 11b0218d23d4f0d8b51387ad387d485aaaecab13853423c408a7c40cee5ae52a
GO bindings.rag.request_plan_sha256 = 11b0218d…e52a（完全一致）
total_calls = 2+7+4+(1+1) = 15；plan.stage = "S2-DEV"
```

历史证据 `docs/evidence/LOCAL-R1-20261101/PM/S2-LIVE-GO-20261104.json:3,24,55-77` 保留了同一
`request_plan_sha256` 与完整 chat 绑定（`chat_requests=2`、stage=S2-DEV），证明当前
P1-RETRIEVAL GO 的 bindings.rag 是**沿用 J2 计划的 rag 块**。`backend/tests/evaluation/
test_live_request_accounting.py::test_go_plan_counts_bind_the_s2_j2_plan_not_p1_request_caps`
用 sha 复算锁定该关系。

### 依据 B：P1 live 路线的绑定核对**只传 12 个 provider 键**

`evaluation/live.py:315-335` 的 `_assert_live_bindings` 调用 `assert_provider_binding` 时，
显式传入的期望键集合 = {base_url_host, embedding_provider, embedding_model,
embedding_dimensions, embedding_host, embedding_region, rerank_provider, rerank_model,
rerank_host, rerank_region, region, settlement_version}；不含任何计划值。`assert_provider_binding`
只核对显式传入的键（`live_authorization.py:323-335`），所以 GO 里 7/4 仅是「被解析保存的
附加值」（`_parse_scope_bindings` 只做形状/敏感校验，`live_authorization.py:266-304`）。

### 依据 C：P1 路线的请求上限只来自 `scope.max_requests`

`evaluation/live.py:408-411` 从环境/GO 取 `max_requests` → `resolve_live_gate` 取
`min(请求值, GO)`（`live_authorization.py:617`）→ `BudgetLedger(max_requests=…)`
（`evaluation/live.py:452-461`）→ 预留前 `facts["reservation_count"] >= max_requests` 拒绝
（`rag/budget.py:555-558`）。`request_remaining = max_requests - reservation_count` 只出现在
预检（`evaluation/live.py:770-774`；`runner.py:1103-1114`）。反向验证：`test_plan_counts_
do_not_become_runtime_caps_for_p1_live_route` 把计划值写成 1/1，运行上限仍为 1000，27 个请求的
预检仍 `accepted`。

### 依据 D：J2 计划值在本 GO 下没有可执行路线

J2 受控执行器构造时要求 **chat + rag 双服务绑定**（`controlled_execution.py:1019-1036`），
而当前 GO 只授权 `services=["rag"]`、无 chat 绑定 → 该路线在构造期即拒绝
（`live_authorization.py:531-538`）。故 7/4 既不是 P1 运行上限，也不是当前可执行的 J2 计数门。

## 3. 运行期拒绝链（都在供应商 HTTP 之前）

1. 构造期：`load_live_runtime` → GO 身份/有效期/账本前缀/服务/阶段/请求上限/单请求上界
   （`evaluation/live.py:398-451`；`live_authorization.py:474-661`）。
2. 预检：`plan_live_cost` 计算实际请求总数（embedding 批数 + 每 case 1 query embedding +
   1 rerank），与阶段剩余/`request_remaining`/单请求上界比较；`request_limit_insufficient`
   在 `target.mkdir`/构造 index/provider **之前**抛出（`evaluation/live.py:496-567,543-548`；
   `runner.py:1102-1116`）。
3. 预留前：`BudgetLedger.reserve` 先在锁内做请求期 GO/预算复核（`refresh_request_limits`），
   再判累计请求数/总剩余/阶段剩余（`rag/budget.py:542-569`）。失败即 `RequestLimitExceeded`，
   零 HTTP、零账本新增。
4. 发送前二次复核：`reserve` → `recheck_reservation`（只读、不清账、不退款）→ 通过后才
   `client.post`（`rag/providers.py:329-350,654-668`；`rag/budget.py:605-626`）。
5. 实际计数：每个真实尝试 1 条 `reserved`；run 结束用 `budget_before/after`
   （`runner.py:1187-1205`）与账本 `reservation_count` 对账。

## 4. 如何审计（只读）

```powershell
# 累计预留：跨 kind/stage/run 的 reserved 事件数（= GO 累计口径）
.\.venv\Scripts\python.exe -B -c "import json,collections; p=r'docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl'; c=collections.Counter(); s=collections.Counter()
for line in open(p,encoding='utf-8'):
    e=json.loads(line)
    if e.get('event')=='reserved': c[e.get('kind')]+=1; s[e.get('stage')]+=1
print('total',sum(c.values()),dict(c),dict(s))"
# 2026-11-10 实测：total 505（embedding 259/rerank 164/chat 78/ocr 4；S2-DEV 381/P1-RETRIEVAL 124）
```

- 单次运行：`var/eval/runs/<run_id>/summary.json` 的 `live.precheck`（预估请求/成本）、
  `live.provider_requests.attempts`（实际尝试）、`live.budget_delta`（账本增量）。
- 判断「是否超授权」只看：`reservation_count ≤ scope.max_requests`、阶段 accounted ≤ 3.0、
  单请求预留 ≤ 0.05、总 accounted ≤ 20。**不要**用 7/4 与实际请求数比较（语义不同）。
- 审计时注意：`reservation_count` 是跨 kind/stage/run 的累计值（`rag/budget.py:431,555`），
  不是「本次运行」的请求数；本次运行数看 run summary。

## 5. 对 review #56 / p1-report §4 的口径更正

- #56 的现象（GO 计划 7/4 vs 实际 17/10、39/31）**成立**，但「口径差」应读作：**J2 计划值
  与 P1 运行期实际请求是两类口径**，不是 GO 被违反、也不是跑出了未执行的约束。
- `p1-report.md:63-83` 的 T111/T112 请求数与账本增量属于口径 3/4/5（实际/预留/结算），
  与 `scope.max_requests=1000` 同口径；505/1000、0.0143149/3.0 均在上限内。
- 不改 `S2-LIVE-GO.json`、`budget.json`、`live-ledger.jsonl` 与历史报告；本文件为新增更正说明。

## 6. 剩余风险 / 未覆盖

- 当前 GO 沿用 J2 计划块（含计划值、`request_plan_sha256`、OCR/chat 字段），但 P1 路线不核对
  其计划值；若未来 J2 计划变更或重签 GO，需重新对齐 `request_plan_sha256`（本文件只记录现状）。
- P1 路线对 token caps 不直接读 GO，而由 `settlement_version=usage-conservative-v1` 的冻结值
  （4096/6000，`rag/settlement_policy.py:42,57-58`）决定；当前与 GO 数值一致，若升版本需复核。
- 预检是上限估计（T112 预估 71、实际 70：1 个 query 无候选，未伪造 rerank 请求），不承诺等于
  实际请求数；实际仍以账本 `reserved`/run summary 为准。
- 本次未做任何真实调用/未重跑 live；结论来自源码接线与隔离账本负例
  （`backend/tests/evaluation/test_live_request_accounting.py`，5 passed）。
