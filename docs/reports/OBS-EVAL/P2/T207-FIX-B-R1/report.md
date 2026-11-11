# P2-T207-FIX-B-R1 开发报告：summary 保守占用漏计 J1 拒绝轮（C1）

- 分支 `codex/p2-e2e` @ `96fede3`（B=`18159a1`）；本包未 commit，未改账本/预算/GO/fixtures。
- 零真实调用（全部 `httpx.MockTransport`，探针 `outbound_network=0`）；依据任务书 `P2-T207-FIX-B-R1-dev.md`。

## 1 根因与修法
C1：answer 轮 J1 结算被拒时，门内账本已按该笔上界写保守 `result`，但 `p2_runner.py` 的
`except`（`gate_settle`）只记停止码、不累计 `ledger.settled_cny`，导致
`summary.conservative_held_cny` 漏这一笔（与契约 §7.2「已写 result 的保守占用总额」不符）。

- `P2RunLedger` 新增互斥计数 `rejected_rounds`（默认 0）。
- 仅当 `settle_success` 抛错且本轮尚未入账（`j1_settle and not settled_booked`）时，按
  `ticket.bound_cny` 补记 `settled_cny` + `by_center_cny` 并计 `rejected_rounds`；不计
  `settled_success`/`settled_failure`；四分支入账收口到一处，`settled_booked` 防重复计数。
- `summary.requests` 新增 additive 键 `rejected_rounds`；`_money_split` 注释同步。

## 2 改动（仅 4 个允许文件 + 本目录）
- `p2_runner.py` +36/-8：计数器、统一入账、J1 拒绝补记、summary 新键；
- `p2-runner-contract-v0_1.md` +21/-2：§7.2 写明 J1 拒绝轮归属/计数，§2 清单补键；
- `test_p2_runner.py` +100/-0（拒绝轮 + 正常轮不误计）、`test_p2_live_wiring.py` +63/-0
  （真实门端到端）；契约改动全部 additive（既有键语义/门槛/schema/status 未动）。

## 3 C1 修复前后（同一探针，`evidence/probe_c1.out.txt`）
场景：Q01 answer 轮 usage `total_tokens=999 != 64+32` → `SETTLEMENT_NOT_RELEASABLE:total_mismatch`，停止码 `gate_error`。

| 量 | 修复前 | 修复后 |
|---|---|---|
| 账本 answer `result` 保守额 | 0.018688 | 0.018688 |
| 账本 result 保守合计 | 0.018812 | 0.018812 |
| `summary.conservative_held_cny` | **0.000124（漏记）** | **0.018812（= 合计）** |
| `run_result.settled_cny` | 0.0 | 0.018688 |
| `summary.rejected_rounds` | 键不存在 | 1 |
| `settled_success` / `settled_failure` | 0 / 0 | 0 / 0 |
| 正常轮 `rejected_rounds` | 键不存在 | 0（不误计） |

正常轮对照：held 0.000508 = 账本合计；`settled_cny` 0.000384（answer 按 usage）。

## 4 验证
```
cd backend
.venv/Scripts/python.exe -m pytest tests/evaluation/test_p2_runner.py \
  tests/evaluation/test_p2_live_wiring.py -q -p no:cacheprovider \
  --basetemp .pytest-tmp/p2-t207-fix-b-r1
# 51 passed, 1 warning（基线 48 + 新增 3；B 的 118 是含 authorization 的三文件口径）
```

- 新增 3 条在 **HEAD 代码**上实跑 `3 failed`（临时换回 HEAD 的 `p2_runner.py`，跑完恢复，
  恢复后 sha256 与改前一致）；修复后全绿 → 有回归力。未跑全仓；无 skip/xfail；未 commit。

## 5 限制
1. `SettlementBoundaryAnomaly`（重算额 > 预留的安全网）也停在同一分支，账本按更高重算额入账；
   门不把金额暴露给 runner，故 runner 仍按上界记（只可能少记、不会虚增），契约 §7.2 已披露。
2. 只跑任务书点名的两个测试文件；其余模块未回归。mock 链 `outbound_network=0`，`billed_cny`
   仍为 0（不冒充真实出网计费）；`provider_billed_cny` 只含从属尝试的 0.000124。
   工作区另有并行包的未提交改动（`cli.py`/`product_adapter.py` 等），非本包改动。
3. sha256（前 16）：runner `c1e336f0b3bebf62`、契约 `90c49fccb191cbc1`、runner 测试
   `5141ff5e0937e235`、live 测试 `c246bd274f099648`。

产物：本文件 + `evidence/probe_c1.py`、`evidence/probe_c1.out.txt`（修复前后）、`evidence/pytest.txt`。
