# R0-5 CAP-UNLIMITED 补齐报告（2026-11-16）

## 0. 结论（先给）

- **CAP 代码层面：可放行**。审计中的 6 条缺口 + 1 条零测试缺口全部有实现或测试覆盖；
  定向套件 `test_p2_authorization.py + test_p2_h2_v3_controlled_entry.py` = **90 passed / exit 0**。
- **不代表可以立刻真实 run**，外部条件仍有三条：① 本次改了 `code_version`，旧 r0 计划/binding/GO
  必然 `code_changed_since_plan`，必须重跑 `plan-private` 并重签 `max_requests="unlimited"` 的新 GO；
  ② 新计划必须再过一次真实 `check-only`（本单按约束未运行）；③ 会话期间另一写者改动了冻结件
  `p2_hard_evidence.py`（见 §4），放行前须由 lead 复核/冻结。
- 本单未发送任何真实请求，未运行 `plan-private` / `check-only` / `run`，未读 `.env`/H2 私有材料。

## 1. 缺口 → 改动 → 测试（逐条）

| # | 审计缺口 | 改动 | 测试证据 |
|---|---|---|---|
| 1 | `run` 的 `_recompute_plan` 在真实请求之后；无 `plan.max_requests==MAX_REQUESTS` 闸 | `run_command` 在 `check_target_paths`/`_execute_loaded` **之前**执行 `_plan_dial` + `_recompute_plan`；失败固定码 `plan_dial_failed` / `plan_recompute_failed`（不吞 `EntryError`）；sidecar 复用 presend 结果并标注 `plan_recompute_phase=presend` | `test_run_refuses_finite_plan_dial_before_bundle_and_send`、`test_run_refuses_recompute_mismatch_before_bundle_and_send`：`load_v3_bundle`/`_execute_loaded` 为"调用即失败"探针，external 连接 0 |
| 2 | `quota` 硬编码 `governance_cap="unlimited"`、`exceeds_gate` 恒 `False` | 新增纯函数 `_request_gate` / `_quota_summary`：unlimited → `gate_mode="unlimited"`、`exceeds_gate=None`、`not_enforced_reason="unlimited_no_cumulative_request_gate"` 且列出仍生效的 4 道闸（plan_dial/GO/逐项配额/金额）；有限计划 → 取 `min(plan, GO)` 真算 `exceeds_gate` | `test_quota_summary_states_unlimited_has_no_total_request_gate`、`test_quota_summary_still_computes_a_finite_gate` |
| 3 | 无 run 级单写者；`check-only` 的 `zero_write` 对并发写者竞态；重名只是事后保护 | 新增 O_EXCL 租约 `_acquire_run_claim`（写 PID + 进程启动标记 + 有界 stale，读回校验）：`run` 占 **本机登记处 + seal 目录**，`check-only` 占本机登记处（给了 `--seal-root` 时再加 seal）；被活进程持有时固定码 `run_claim_held`、零发送；`seal` claim 排在"seal 必须为空"检查之后，避免自撞。**活 PID 不按时间抢**（宁可人工确认/杀进程）；只有死 PID、PID 复用（启动标记不同）才回收，读不到标记时 6h 兜底 | `test_run_claim_excludes_concurrent_holder_and_releases`、`test_run_claim_reclaims_dead_pid_but_never_a_live_one`、`test_run_refuses_when_claim_held_before_bundle_and_send`、`test_run_releases_claim_when_a_later_presend_check_refuses`（第 4 条为实现后补的泄漏回归，非红先行） |
| 4 | `rag/budget.py` 仅凭 mtime 60s 回收 stale 锁 → 慢持有者被误删 | 新增 `mktkb/proc_identity.py`（Windows `GetProcessTimes`/`GetExitCodeProcess`；Linux `/proc/<pid>/stat` starttime；其余 POSIX `kill(0)`）。`_stale_lock` 改为：死 PID/PID 复用（启动标记不同）才回收；活 PID 不抢；无 PID 的坏锁才回退 mtime | `test_ledger_lock_from_a_dead_pid_is_reclaimed_immediately`、`test_ledger_lock_of_a_live_pid_is_not_stolen_even_past_the_mtime_window` |
| 5 | 逐项配额按 `run_id` 记账，换 run_id 即归零 | `P2Gate._request_guard` 的 unlimited 分支改为按 **`plan_sha256 + item_id`** 跨 run_id 累计；非 P2 历史预留（无 plan 元数据）跳过，**同阶段**无 plan 身份的预留仍 `run_plan_unknown` 拒绝（真实账本 908 条 P2-LIVE 均有 plan_sha256，505 条非 P2 无元数据） | `test_unlimited_item_quota_accumulates_across_gate_instances`（先播种 3 条 S2-DEV 历史；第二个 gate 换 run_id 仍 `attempt_quota_exhausted`） |
| 6 | `budgeted.complete` 同步 `reserve/recheck` 卡事件循环，`service.py:1772` 的 `wait_for` 失真 | `reserve` 与 `recheck_reservation` 都改到 `asyncio.to_thread`；`_pre_send_check` 返回 awaitable；`DeepSeekClient.complete` 用 `inspect.isawaitable` 等待（旧同步回调仍兼容） | `test_turn_times_out_instead_of_hanging_when_the_ledger_lock_is_held`：锁被活 PID 占住时 `_call_model` 在 0.2s 内 `ModelTimeout`（修复前 0.8s 后 `ModelBudgetRefused`），且账本 0 条 `reserved` |
| 7 | unlimited 分支零测试 | 见上列新增测试 + `_plan_id_derivation`/`_plan_dial` 内建校验 | 另：`unlimited 计划往返`、`preflight requests_remaining=="unlimited"`（1500 历史也不出 `request_budget_insufficient`）、`unlimited 计划+unlimited GO`、`unlimited 计划+1500 GO → go_max_requests_below_plan`、`_assert_authorization_live` 同断言、`BudgetLedger("unlimited")` 非 P2/无 guard 双拒 |

## 2. 测试证据（命令、退出码、统计）

统一前置：`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；命令均带 `-B -p no:cacheprovider`。

| 阶段 | 命令（pytest 路径） | 结果 |
|---|---|---|
| RED-1 | `backend\tests\evaluation\test_p2_h2_v3_controlled_entry.py` | **exit 1**：8 failed（首跑有 4 条先暴露测试夹具目录未建；其余为 `_quota_summary`/`_run_claim`/presend 门缺失。夹具修正后未再单独红跑，直接进入实现） |
| RED-2 | `backend\tests\evaluation\test_p2_authorization.py` | **exit 1**：4 failed / 77 passed（跨 gate 配额、死/活 PID 锁、异步超时） |
| GREEN | 上述两个文件一起，`--basetemp backend\.pytest-tmp\cap` | **exit 0：90 passed** |
| REG-1 | `backend\tests\rag` + `test_j2_ocr_budget` + `test_k_r1a_ocr_source_identity` + `test_s2c_numeric_and_refresh` + `test_s2h_r3_official_profile` | **exit 1：464 passed / 2 failed**（均为既有/环境失败，见 §3） |
| REG-2 | `test_p2_holdout_plan` + `test_p2_h2_controlled_entry` + `test_p2_live_wiring` + `test_live_request_accounting`（basetemp 在仓外） | **exit 0：66 passed** |
| REG-3 | `unit\test_s2d_post_send_guard` + `unit\test_s2h_r2_conservative_profile` + `integration\test_s2d_post_guard_http` | **exit 0：16 passed** |
| REG-4 | `unit\test_conversations` + `integration\test_s2c_paygate_http` | **exit 0：52 passed** |

说明：REG-2 的 v2 入口测试要求 `out_dir` 在仓外，跑在 `backend\.pytest-tmp\cap` 下会以
`path_inside_forbidden_root` 失败（与本单改动无关）；换仓外 basetemp 后 66 全过。

## 3. 未做项 / 已知失败 / 理由

- **未跑真实 `plan-private`/`check-only`/`run`**：任务硬约束禁止；CAP 实现靠合成 binding + 零发送探针验证。
- **未跑全仓 pytest**：会话内有另一写者正在改 `backend/tests/evaluation/` 其它新文件与冻结件；
  已按改动面跑定向回归（上表）。全量结果不能归因于本单。
- 既有失败（未修，非本单引入）：`rag\test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan`
  断言真实 `budget.json limit_cny==20.0`，而 v3 预算已为 40.0（哈希与 R0 基线一致）；env=40 时仍失败，属陈旧的
  20 元口径断言。`unit\test_s2h_r3_official_profile.py::...worst_case...` 只在 env=20 时失败（真实预算 40），env=40 通过。
- OCR 网关（`providers/ocr_budgeted.py`）仍同步 reserve：审计条目点名的是 chat 路径 `budgeted.py:300`；OCR 单页、
  调用面小，未纳入本次最小改动。
- 取消/超时若恰好发生在 `reserve` 的线程等待中，可能留下"已预留、无 result"的保守占用（不发请求、
  不回 0、不重复计），与进程崩溃语义一致；未加后台补记以保持最小改动。
- 租约登记处按"同机 + 同仓库"隔离；跨机器共享 seal 目录不在本次覆盖内（当前 r0 为单机执行）。

## 4. 保护件哈希（前 → 后）

比较对象：`evidence/00-baseline/protected-hashes.txt`（R0 审计基线，2026-11-16 10:34）。
逐项脚本比较结果：**16 项 SAME，3 项 DIFF**（2 项本单预期 + 1 项外部改动）。

| 保护件 | 前（基线） | 后/现状 | 判定 |
|---|---|---|---|
| `p2_hard_evidence.py` | `fba6e606…a843529b` | `84f53a51…bd485b`（mtime 15:19:01） | **DIFF，非本单改动**：本单从未编辑/写入该文件；会话期间另一写者改动，请 lead 复核 |
| `p2_authorization.py` | `b2b4f22a…b91f8951` | `e10bd691…ac35f61c` | 预期（条目 5） |
| `tools/p2_h2_v3_controlled_execute.py` | `0de0774d…31b7cc9` | `0337b252…e8a17216` | 预期（条目 1/2/3） |
| `p2_evidence_rescore.py` | `d8260256…7841f3e9` | 同 | SAME |
| `p2_holdout_scenarios_v3.py` / `p2_holdout_scenarios.py` | `383f8f2b…` / `bb9ae59a…` | 同 | SAME |
| `p2_contracts.py` / `p2_holdout_plan.py` / `p2_runner.py` | `3341ea79…` / `47125ae9…` / `80824570…` | 同 | SAME |
| `p2_holdout_source_map.py` | `e44d825e…` | 同 | SAME |
| `docs/evaluation/p2-evidence-rescore-v0_1.md`、`p2-holdout-v3.source-map.json` | `e0487f25…`、`03665c48…` | 同 | SAME |
| `docs/evidence/.../budget.json` | `79b21700…10b1a9e` | 同 | **SAME（金额未动）** |
| `docs/evidence/.../live-ledger.jsonl` | `e5641063…ed6b656` | 同 | **SAME（账本未动）** |
| 旧 fullverify 证据 3 件 | `6955099b…`/`04e1f3df…`/`e7e3d887…` | 同 | SAME |
| `tools/p2_h2_controlled_execute.py`（v2 旧入口） | `48d130e7…` | 同 | SAME（未绕过/未改） |

注：`p2_evidence_rescore_axes.py`、`p2-evidence-rescore-v0_2.md` 等未列入 00-baseline 的冻结件，
本单未打开/写入；如需"前后"证明，请以 R0 收口时的统一哈希快照为准。

本单新增/修改（供复核）：
`proc_identity.py c708b5e4…`、`rag/budget.py 8d306436…`、`providers/budgeted.py d9be0018…`、
`providers/deepseek.py 758ca4a1…`、`test_p2_authorization.py fb88d85c…`、
`test_p2_h2_v3_controlled_entry.py 193f0740…`。

## 5. 放行条件（CAP 侧）

1. 重跑 `plan-private`（新 `code_version`）→ 新 GO（`scope.max_requests="unlimited"`，金额/中心不变）；
2. 真实 `check-only` 必须 `ok=true`、`quota.gate_mode=="unlimited"`、`zero_write/zero_send` 全真；
3. 冻结件复核通过（尤其 `p2_hard_evidence.py` 的外部改动），再按 taskbook §5 顺序执行 r0 一次。
