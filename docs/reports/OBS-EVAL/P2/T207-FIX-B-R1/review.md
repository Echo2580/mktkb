# P2-T207-FIX-B-R1 独立验收 review（只读复核 + 独立复跑，零真实调用）

- 验收角色：独立验收助手（全新上下文，未参与开发）。依据：`.claude/handoffs/prompts/P2-T207-FIX-B-R1-verify.md`；
  开发报告只作线索，**每条结论以我的复跑/自写探针为准**。
- 分支 `codex/p2-e2e`；到达时 HEAD=`ffc9fe5`，采集时 HEAD=`405491c`（并行包 T207-FIX-P R1 的提交，
  非本包）；本包改动仍未提交。工作区同时有并行包 T207-FIX-A 在写（cli/product_adapter/测试/计划 GO 候选稿）。
- 只写：本文件 + `evidence/verify/`（2 个自写探针 + 4 份证据）；未改代码/测试/契约；未 commit；
  零真实出站；未读仓库 `.env`/H1/H2（探针全部 tmp 账本/预算/GO + MockTransport）。

## 0 基线（到达 / 离开一致）

| 文件 | sha256 | 大小 |
|---|---|---|
| `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl` | `6b053520…ee345c`（= FIX-B 基线） | 1,050,298 B |
| `docs/evidence/LOCAL-R1-20261101/budget/budget.json` | `79b21700…a910b1a9`（一致） | 1,738 B |
| `docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json` | `79a5f318…c19070e`（一致） | 1,232 B |

三份真账本/预算/GO 未变；T207 的 `T207-GO*.CANDIDATE-DRAFT.json` 被并行包 FIX-A 改动，**不是**上述真 GO。
详见 `evidence/verify/00-scope-and-baseline.txt`。

## 1 逐条判定

| # | 条目 | 判定 | 一句话理由 |
|---|---|---|---|
| 1 | 范围 / 未提交 / 无 skip | **PASS（附并发归因）** | 本包仅 p2_runner、契约、两测试文件、FIX-B-R1 新目录；其余 diff 均可归因 FIX-A/FIX-P/FIX-S/PM；禁用文件在 FIX-B-R1 快照 clean（离开时 p2_scoring 被 FIX-S 改，非本包）；三 SHA 不变；无 skip/xfail；无本包 commit |
| 2 | 复跑与回归保护 | **PASS** | 修复后 51 passed（当前 56 − FIX-A 5）；HEAD 上 3 个新用例 3 failed、48 个既有用例 48 passed；新增用例确有回归力 |
| 3 | 不双重计数 / 契约一致 | **PASS（附 1 个非阻断边界 R1）** | 计数互斥、by_center 与账本一致、旧口径正常轮不变；混合轮 0.000384+0.018688=0.019072 只计一次；§7.2 逐值可对 |
| 4 | 与 C1 闭环 | **PASS** | 修复前 summary 0.000124 vs 账本 0.018812（差 −0.018688）；修复后 0.018812=0.018812，rejected=1、settled=0.018688 |
| 5 | 合规与报告 | **PASS（附报告小瑕）** | 4 个 sha 在“去掉并行包追加”后逐值可复现；数字可复现；零真实调用；未读 .env/H1/H2；未 commit；报告 venv 路径写错（非阻断） |

**建议：接收（不返工）**。阻断项 0；R1（异常过滤边界）与 R2/R3（注释/命令路径小瑕）作为非阻断跟进。

## 2 条目 1：范围与未提交

- 本包允许文件（`git diff --numstat`）：`p2_runner.py` +36/−8（5 个 hunk，均标 T207-FIX-B-R1）；
  `test_p2_runner.py` +100/−0（2 个新用例）；`test_p2_live_wiring.py` 中 +63/−0 的 1 个新用例；
  `p2-runner-contract-v0_1.md` +21/−2（§2 与 §7.2）；新目录 `docs/reports/OBS-EVAL/P2/T207-FIX-B-R1/`。
- 当前 `git status` 的其余改动是并行包：
  - FIX-A：`cli.py`、`product_adapter.py`、`test_p2_authorization.py`、`test_p2_product_e2e.py`、
    `p2-live-binding-v0_1.md`、`p2-run-contract-v0_1.md`、p2-runner-contract 的 §7.4、
    T207 计划/GO 候选稿/runbook/evidence、新 evaluation 模块与 `tools/p2_live_execute.py`；
    其任务书明确负责“计划/GO/runbook 重建”与这些代码。
  - FIX-P：已提交在 `405491c`/`ffc9fe5`，当前无工作区 diff。
  - FIX-S：02:03Z 出现 `p2_scoring.py`（+5/−1）与 `test_p2_scoring.py` 的改动（非本包）。
  - PM：`.claude/handoffs/_index.md` 与历史提示词。
- 禁用面（FIX-B-R1 验收快照 01:58Z 为空；离开时仅 p2_scoring.py 被 FIX-S 改）：`p2_contracts.py`、`p2_live.py`、`p2_authorization.py`（**源码**）、
  `p2_scoring.py`（FIX-B-R1 验收快照 01:58Z 为空；离开时 02:03Z 出现并行包 T207-FIX-S 的 5 行改动，非本包）、`rag/settlement_policy.py`、`fixtures/`、业务代码（`conversations/service.py` 等）。
  `test_p2_authorization.py` 是 FIX-A 的测试改动，不是源码。
- 无 skip/xfail：两测试文件新增行逐行 grep，`pytest.mark.skip/skipif/xfail` 为 none；`git diff --check` clean。
- 未 commit：`git log ffc9fe5..HEAD` 只有 `405491c`（FIX-P R1）；FIX-B-R1 的 4 个文件改动仍是未提交状态。
- **并发限制**：共享工作区无法给出“原始任务书口径的干净 git diff”；上述按文件内容/注释/并行任务书归因。
  两个共享文件（契约、live 测试）现在的 hash 与 report 不同，原因是 FIX-A 在报告之后追加内容；
  去掉追加后重建 hash 与 report 逐值一致（§5）。

## 3 条目 2：复跑与回归保护

**修复后 51 passed**（当前两文件 56 个用例，减去 FIX-A 追加的 5 个；原 report 为 51 = 48 基线 + 3 新增）：

```
cd backend
../.venv/Scripts/python.exe -m pytest tests/evaluation/test_p2_runner.py \
  tests/evaluation/test_p2_live_wiring.py -q -p no:cacheprovider \
  --deselect <FIX-A 的 5 个用例> --basetemp <tmp>
# 51 passed, 5 deselected, 1 warning in 32.76s
```

**HEAD 代码上的回归力**（不改工作区）：用临时 `sitecustomize` 在 pytest 收集前把
`mktkb.evaluation.p2_runner` 预置为 HEAD 源码（临时目录同时放 `p2_runner.py`/`product_adapter.py`
供 manifest hash），探针输出 `runner_file` 指向临时目录，证明不是“没加载到 HEAD”：

```
HEAD 3 个新增用例：3 failed, 2 warnings in 4.25s
  test_j1_rejected_settle_books_bound_without_counting_success_or_failure（KeyError: rejected_rounds）
  test_normal_settle_does_not_count_a_rejected_round（KeyError: rejected_rounds）
  test_live_j1_rejected_settle_keeps_conservative_held_cny（settled_cny 0.0 != 0.018688）
HEAD 48 个既有用例：48 passed, 8 deselected in 32.75s
```

原始输出见 `evidence/verify/01-pytest-rerun.txt`。新增 3 用例的行为断言（合法 J1 拒绝场景）：

| 断言 | 修复前 | 修复后 |
|---|---|---|
| `summary.conservative_held_cny` == 账本 result 保守合计 | 0.000124 vs 0.018812（False） | 0.018812 == 0.018812（True） |
| `run_result.settled_cny` == 该笔上界 | 0.0 | 0.018688 |
| `summary.rejected_rounds` | 键不存在 | 1 |
| 正常成功轮 `rejected_rounds` / 金额 | 键不存在 / 0.000384 | 0 / 0.000384（不变） |
| `settled_success/failure/unpaid` | 0/0/0 | 0/0/0（互斥） |

## 4 条目 3：不双重计数与契约

- **四分支统一入账**：失败结算、零付费、usage 缺失、成功结算在 `p2_runner.py:1477` 只累加
  `settled_cny` 一次（成功分支原有的 3 处 `settled_cny +=` 已删除）；`settled_booked` 防同一轮二次入账；
  J1 拒绝只在 `j1_settle and not settled_booked` 时补记一次（:1487-1502）。
- **互斥**：成功计数在 `settle_success` 返回后 +1（:1472），异常不加；failure/unpaid 分支不置 `j1_settle`；
  `rejected_rounds` 只在异常补记分支 +1。probe：拒绝轮 0/0/0/1；混合轮 1/0/0/1。
- **by_center 与账本一致**：拒绝轮 `run_result.by_center_cny["answer_retrieval"] = 0.018688`，
  `sum == settled_cny`；混合轮 0.000384+0.018688=0.019072。
- **混合轮不双重计数**（`probe_mixed_rounds.py`，两回合：先成功后拒绝）：
  修复后 `settled_success=1`（0.000384）+ `rejected_rounds=1`（0.018688）= `summary_held` 0.019072
  = 两行 `charged_cny` 之和；`requests_sent=1`；第 2 行 `billed=false/error_code=gate_error`。
  修复前 summary 只 0.000384、第 2 行 charged 0，漏 0.018688。
- **旧键语义**：正常轮修复前后 held 0.000508、settled 0.000384、provider_billed 0.000508、sent 1 全同；
  只有被拒轮原先漏记的 0.018688 现在进入 `settled_cny/by_center/conservative_held`——这是恢复
  §7.2 对 `conservative_held_cny` 的既有定义，不是把该笔冒充成供应商已计费（`provider_billed_cny`
  仍只含从属 0.000124）。`settled_failure/failed_rounds/unpaid_rounds/billed_cny` 未改。
- **契约逐值**：见 `evidence/verify/03-contract-vs-code.txt` 的 10 行对照表（summary 键、金额、
  互斥、requests_sent、provider_billed、run_result.settled_cny、requests.jsonl 行、boundary 限制），
  全部与实现/探针一致。

**R1（非阻断边界）**：`except Exception` + `j1_settle` 假定“门已写 result”。真实门
`settle_success` 的 `evidence_required`（p2_authorization.py:1178-1179）和 `estimate_out_of_bound`
（:1193-1194）在写账本**之前**抛错；若调用方用真实门却没注入 `settle_evidence`（`run_p2` 签名允许，
p2_runner.py:728），runner 会按上界补记而账本无该 result，形成相对账本“虚增”，与 §7.2 前提不符。
正常 live 入口 `run_live_p2` 总是注入 `make_settle_evidence`（p2_live.py:1391），实测未触发；
建议后续只对 `SettlementNotReleasable/SettlementBoundaryAnomaly` 或“已写 result 的 reason”补记，
或先核对门账本确有该 reservation 的 result。

## 5 条目 4：C1 闭环（修复前 vs 修复后，同一自写探针）

真实 P2Gate + MockTransport，answer 轮 usage `total_tokens=999 != 64+32` → `gate_error`：

| 量 | 修复前（HEAD） | 修复后（工作区） |
|---|---|---|
| 账本 answer result 保守额 | 0.018688 | 0.018688（不变） |
| 账本 result 保守合计 | 0.018812 | 0.018812（不变） |
| `summary.conservative_held_cny` | **0.000124（漏记，差 −0.018688）** | **0.018812（= 合计）** |
| `summary.rejected_rounds` | 键不存在 | 1 |
| `run_result.settled_cny` | 0.0 | 0.018688 |
| `requests.jsonl[0].charged_cny` | 0.0 | 0.018688（billed=false，error_code=gate_error） |
| `settled_success/failure/unpaid` | 0/0/0 | 0/0/0 |
| `provider_billed_cny` | 0.000124 | 0.000124（只含从属） |
| `billed_cny` / outbound | 0.0 / 0 | 0.0 / 0（mock_intercepted=5） |
| 正常轮 held / settled | 0.000508 / 0.000384 | 0.000508 / 0.000384（不变） |

与 report 的表格逐值一致；我的探针脚本 `evidence/verify/probe_c1_independent.py`、
原始对照 `evidence/verify/02-probe-c1.out.txt`。

## 6 条目 5：合规与报告可复现性

- report 的 4 个 sha16：`p2_runner c1e336f0`、契约 `90c49fcc`、runner 测试 `5141ff5e` 直接一致；
  live 测试 `c246bd27` 需去掉 FIX-A 之后追加的 219 行后重建，重建文件 51,686 B、hash 逐值一致。
  契约当前 21,310 B；去掉 FIX-A §7.4 段（含段前空行，第 235-259 行）后 19,243 B、hash `90c49fcc` 逐值一致。
  → **report 的 sha 可复现**；当前共享文件 hash 不同是并行包追加造成。
- 数字：0.018688/0.018812/0.000124/1/0 均可复现；report 的 51 passed 可用“当前 56 − FIX-A 5”复跑得到。
- 零真实调用：测试模块自带 `t09_network_guard`；我的探针 `outbound_attempts=0`、`mock_intercepted=5`；
  全部账本/预算/GO 为 tmp 副本。
- 未读 `.env`/H1/H2；未 commit；未改代码/测试/契约。
- **报告小瑕**：
  1. `evidence/pytest.txt` 与 report §4 的命令写 `cd backend; .venv/Scripts/python.exe`，但 backend 下
     没有 `.venv`（venv 在仓库根，pytest 警告显示 `..\.venv`）；该字面命令不可执行，用 `../.venv` 等价复跑
     得到同样 51 passed。
  2. report 写 `@96fede3`；到达时 HEAD 已是 `ffc9fe5`，采集时 `405491c`（并行包提交）。p2_runner 内容
     在 `ffc9fe5..405491c` 未变，不影响复跑，但 HEAD 标注已过时。
  3. report §2 称“`_money_split` 注释同步”，实际只同步了函数 docstring 第一段；关系句
     `p2_runner.py:1090-1091` 仍写“零付费轮 + 失败轮”，未加 J1 拒绝轮（行为/契约不受影响）。
- 存在一次**偶发**失败：合并 51 用例的一次 HEAD 运行中 `test_mock_dry_run_binds_identity_and_passes_trace_integrity`
  报 `FileNotFoundError: .../bound/p2-run/dataset.jsonl`；该用例单跑通过，48 用例整跑也通过，
  判为并发工作区/文件系统瞬时现象，非本包代码路径（不掩盖，记录在 01 证据）。

## 7 限制 / NOT-RUN

1. **共享工作区并发**：无法在“冻结的原始工作区”上重跑；FIX-A 在本验收期间继续改共享测试/契约/计划 GO 候选稿，FIX-S 在 02:03Z 改了 p2_scoring.py。
   我已用“重建 hash + 并集归属”复核，但不能排除 FIX-A 后续再改；本 review 的结论以采集时 hash 为准
   （p2_runner `c1e336f0`、runner 测试 `5141ff5e`、契约重建 `90c49fcc`、live 测试重建 `c246bd27`）。
2. **未跑全仓**：按任务书只跑两个测试文件；未跑 `test_p2_authorization.py`/产品 e2e/其余模块。
   复跑期间还有第三个并行包 T207-FIX-S 在 02:03Z 改了 `p2_scoring.py`（+5/-1，与评分器跨空白匹配有关，
   不属 FIX-B-R1 的 diff）；56/3+48 的复跑采集在该改动之前，02:03Z 之后又复跑 51 用例仍 51 passed（见 01 证据 [F]），FIX-B-R1 的 4 个文件 hash 未受其影响。
3. **R1 边界未动态触发**：需要真实门 + 缺失/非法 `settle_evidence` 的受控接线；为避免改动 runner/测试，
   仅做静态代码核对（p2_authorization.py:1178-1194、budget.py:776-789），未构造运行时反例。
4. 未读 `.env`/H1/H2；未做真实出站；未验收 FIX-A/FIX-P/FIX-S 的并行改动。

## 8 最终建议

**接收（不返工）**。C1 已闭环：J1 拒绝轮的保守上界从“只进账本、不进 summary”变为
`conservative_held_cny = 账本合计`，计数进互斥的 `rejected_rounds`，成功/失败/零付费口径与正常轮金额不变，
契约 §7.2 与实现逐值一致，3 个新用例在 HEAD 上确实失败、修复后 51 passed。

非阻断跟进（建议 T207 正式矩阵前顺手处理，不要求本包返工）：
1. **R1**：把补记条件从 `except Exception` 收紧到“门已写 result 的 J1 拒绝”
   （`SettlementNotReleasable/SettlementBoundaryAnomaly` 或核对门账本 result 存在），避免
   `evidence_required/estimate_out_of_bound/BudgetLedgerInvalid` 这类写前异常造成相对账本虚增；
2. **R2/R3**：修 `_money_split` 关系句（p2_runner.py:1090-1091）与报告里的 venv 路径/HEAD 标注。

## 9 产物清单

- `evidence/verify/00-scope-and-baseline.txt`：范围归因、4 文件 hash 与重建、三 SHA、skip/commit 检查。
- `evidence/verify/01-pytest-rerun.txt`：51/56/3+48 的命令与原始输出摘录、偶发失败记录。
- `evidence/verify/02-probe-c1.out.txt`：真实门 C1 修复前后 + 混合轮不双重计数的自写探针输出。
- `evidence/verify/03-contract-vs-code.txt`：§7.2 十项逐值对照 + 残余风险 R1-R4。
- `evidence/verify/probe_c1_independent.py`、`probe_mixed_rounds.py`：可重跑的探针脚本。
