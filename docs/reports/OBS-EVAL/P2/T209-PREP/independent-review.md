# T209-PREP 独立验收报告

- 角色：E2 T209-PREP 全新独立验收上下文（非开发、非经理）；未改产品代码/测试/契约/开发报告。
- 现场：`D:\GPT项目\市场部AI知识库`，`codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存 0。
- 证据：全部独立探针/输出在 [independent/](independent/)；命令与退出码见 [10_command_log.txt](independent/10_command_log.txt)。
- 结论：**10/10 关键项 PASS，overall PASS**（仅 E2 准备工程；不构成正式 T209 通过、质量通过或发布批准；未记录任何通过标记）。
- round 2：开发已按 D1 定向返工并冻结；本上下文复验 D1 **resolved**，40/80/120、冻结 20/20，最终仍 **overall PASS**（详见 §七）。

## 一、逐项结论

| # | 项 | 状态 | 独立证据（checks/关键事实） |
|---|---|---|---|
| 1 | 报告分列 | PASS | [02](independent/02_report_probe.txt) 74 checks：4 run succeeded/30 题/36 回合；质量 FAIL 19/30、11 fail、2 safety；证据 missing=27、cross_entity 27 unknown；软评分 NOT-RUN/UNKNOWN；资金三行分列；`to_dict` 无 overall/ready；对照 24/30+0 硬失败→`not_ready`（非 pass 非 fail），执行成功未掩盖质量 |
| 2 | 口径反例 | PASS | 02 C1-C24 + [03](independent/03_candidate_probe.txt) S28-S32d：单 scenario verified 外推被拒；27 missing≠27 答错；recorded_status≠rescored；跨轮/跨 pipeline/跨 scope `scores_comparable=false`；`release_ready=true`/`detail_export=true`/题干标签逐题字段/额外 overall 字段均拒绝 |
| 3 | candidate 不可发布 | PASS | 03 S0-S45（52 checks）：archive/verify/restore/list/diff 五属性恒 false；恢复 `approval=None` 且无 approval.json；对恢复基线 `diff_runs` → `baseline_unapproved`，`require_release_baseline` 拒绝；`approve_baseline` 调用 0；改 publishable/state/加 approved/改 report 均拒绝 |
| 4 | 坏输入 fail-closed | PASS | [04](independent/04_bad_inputs_probe.txt) 22 checks（18 类）：manifest 缺/坏 JSON/双路径逃逸/run_id/suite/identity 不匹配/字段类型/额外字段；payload 内 approval.json；payload 跨归档摘要互换；归档根与 payload junction；已审批源/holdout 源/非 SplitReport/非目录；已存在目标/缺 artifact；均拒绝且无 `.staging-*` 半成品 |
| 5 | 正常归档可恢复 | PASS | 03 S2-S32d：candidate/blocked 全链；restore 不改源字节、不写正式 registry；list 两次一致且排序；diff 只读、不求和、`score_merge_allowed=false`；跨身份不可比 |
| 6 | 复用/改动对账 | PASS | git：reused 3 模块+4 测试 `git diff` 干净、hash 与 00-protected-pre 一致、mtime ≤11-14T05:36（早于 T209 13:12 窗口）；新模块实际调用 `archive_baseline`/`verify_archive`/`restore_baseline`，payload 即既有归档原字节。`diff_runs` 未复用：`diff_candidates` 是候选归档只读对比（见残余 R4），无 gate/审批逻辑复制 |
| 7 | 测试完整性 | PASS | 34 passed（junit 34/0/0/0）、80 passed（80/0/0/0）、collect 114；0 skip/xfail；34×`t09_network_guard` SETUP/TEARDOWN；无 assert True/or True；负向 canary 预期失败证明 guard 真实；`monkeypatch` 仅用于 approval sentinel（目标略弱，见观察 O2） |
| 8 | 零真实调用/保护件 | PASS | 34 项 guard；[05](independent/05_zero_calls_probe.txt)：源码扫描 0、import+渲染 0、完整 candidate 链 socket/DNS 0；资金 4/4、锁 2/2、C 12/12、E0 6/6、E1 5/5、正式 baseline 2/2、real-h2 1/1；`LOCAL-R1` git clean；正式 registry mtime 2026-11-09 未变 |
| 9 | 冻结清单 | PASS | [06](independent/06_freeze_recheck.txt)：18/18 hash 重算；模块/测试/dev-report hash 一致；pre/post 67/67、changed=0；T209 目录仅 2 个新代码测试+报告目录，无未列开发文件；15 个 tracked 修改全部早于 T209 |
| 10 | 报告/契约一致性 | PASS | [08](independent/08_contract_probe.txt) 30 checks：未记录通过标记；NOT-RUN/残余四项如实；34/80/114/red/protected 日志自洽；dev-report 引用 30 个测试名全部存在；示例报告与链式 demo 可逐字节复现（06 F5/F7） |

## 二、关键命令与计数（全部亲自复跑）

- `pytest test_p2_candidate_report.py -q -rs --junitxml=…` → exit 0，34 passed，0 skipped。
- `pytest test_report.py test_baseline_portability.py test_diff_release_gate.py test_p2_gate.py` → exit 0，80 passed。
- `pytest <5 files> --collect-only -q` → exit 0，114 collected。
- `01_protected_recheck.py` → exit 0，42/42 对象一致（pre/post 均 IDENTICAL）。
- `02_report_probe.py` 74/74、`03_candidate_probe.py` 52/52、`04_bad_inputs_probe.py` 22/22、`05_zero_calls_probe.py` 7/7、`06_freeze_recheck.py` 9/9、`08_contract_probe.py` 30/30，全部 exit 0。
- 负向 canary `guard_canary.py` → exit 1（预期）：guard 捕获 `socket.create_connection('example.com',80)` 并使 teardown 失败。

## 三、独立反例（开发测试未覆盖/不同构）

`manifest` 路径逃逸（candidate 层）、`run_id`/`suite`/`identity` 不匹配、字段类型错误、payload 内实际 `approval.json`、payload 跨归档摘要互换、归档根 junction、payload 目录 junction、缺/截断 manifest、已审批源（独立自建审批）、holdout 源、非 SplitReport、非目录、已存在目标、缺 artifact、改 report 后重算 `report_sha256`、跨 scope/pipeline/round 归档 diff。严格拒绝且未留半成品。

## 四、缺陷与残余（不改变本次 PASS，但须如实交接）

- **D1（非阻塞缺陷）**：`build_execution` 在 4 个 run 全 `failed` 时聚合状态为 `not_run`；`failed` 枚举不可达（[09](independent/09_edge_probe.txt)）。不影响本次分列/不掩盖判定，但会误述执行失败，建议正式 T209 前修。
- **O2（观察）**：`test_candidate_flow_never_calls_approve_baseline` 只 patch `baseline_module.approve_baseline`，无法捕获 `from .baseline import approve_baseline` 的直绑；但模块无该名、源码扫描 0、独立运行期计数 0，结论仍成立。
- **R1**：伪造报告可重建 manifest 使 `verify` 通过（无外部签名、无 round-run 成员绑定），但仍不可发布、恢复 approval=None、`diff_runs` 仍 `baseline_unapproved`；开发 §11.3/11.4 已披露，独立复现。
- **R2**：自由文本 `note`/`detail` 不做内容扫描（仅字段级拒绝）；若上游写入题干/答案文本，模块不阻止。
- **R3**：真实 run card 未消费、无外部签名、无 round-run 绑定、POSIX symlink 未测（开发已列，未变）。
- **R4**：`diff_candidates` 未复用 `diff_runs`；二者口径不同（候选归档只读对比 vs 发布 gate diff），无 gate/审批逻辑复制、无求和/合并；风险低但正式阶段需固定口径。
- **R5**：`LOCAL-R1` 仅元数据指纹（48,814 文件/5.10GB），4 个资金/GO 文件为逐字节 SHA；开发已披露，未越界读取私有内容。

## 五、与开发报告的差异

- 34/80/114、18/18、67/67、04 示例、05 链式 demo 均独立复现一致；开发自报核心可核。
- 开发未列 D1；其余残余（card 未消费、签名、round-run 绑定、POSIX symlink）如实，未发现夸大。
- 开发测试的 approval monkeypatch 目标较弱（O2），但开发结论不依赖该单点，独立证据补强。
- 未发现弱化测试、假模块、真实调用、保护件变化、正式 registry/基线写入。

## 六、判定（round 1）

- 10 个关键项全部 PASS → **overall PASS**（限 E2 T209-PREP 独立验收）。
- 该 PASS 不构成正式 T209、质量通过、基线批准或发布批准；D1 交 round 2 定向复验，R1-R5 交经理与后续正式阶段。
- 复查入口：`independent/00_environment.txt`、`01`-`10` 探针输出、两份 junit、`collect-114.txt`、`setup-show-34.txt`、`guard_canary_expected_failure.txt`。

## 七、D1 返工复验（round 2，2026-11-14）

- 触发：round 1 发现 D1（4 run 全 failed→`not_run`、`failed` 枚举不可达）。
- 新冻结对象独立复算与 lead 一致：模块 `597be014…`、测试 `f1edcaed…`、dev-report `2493ef09…`、freeze `005c240c…`（20 项）。
- D1 定向复验（[11_d1_rework_probe](independent/11_d1_rework_probe.txt) 50/50；[09_edge_probe](independent/rework/09_edge_probe.txt) 观测）：
  - 4 run 全 failed→`failed`；`failed` 可达；2 succeeded+2 failed→`partial`；全 not_run/0 run→`not_run`；全 succeeded→`succeeded` 不变；
  - `to_dict`/`from_dict` canonical 往返（含空 runs）；渲染“执行成功/执行失败/执行部分完成/未执行”与枚举一致，并含聚合映射行；failed 报告不含“状态: not_run”；仍无 overall 字段；
  - 非数组 runs / 非法 run status 仍 fail-closed。
- 新增测试：D1 回归 6/6 passed（`-k execution_aggregate or failed_execution_report`，junit 6/0/0/0）；开发提供的 `12-d1-red.txt` 记录旧行为失败（4 failed/2 passed，all-failed→not_run、0 run 被拒），`13-d1-green.txt` 为修复后 6 passed；断言直接针对 all-failed、0 run 与渲染。
- 全量：**40 passed**（junit 40/0/0/0）、既有 **80 passed**（80/0/0/0）、**collect 120**；0 skip/xfail；40×netguard SETUP/TEARDOWN；无 assert True/or True/xfail；approval sentinel 观察 O2 不变。
- 语义不变：02 74/74、03 52/52（候选不可发布/恢复/diff）、04 22/22（18 类坏输入）、05 7/7（零调用）；R1/R2 残余复现未变。
- 冻结/保护件：[06](independent/rework/06_freeze_recheck.txt) 20/20；[01](independent/rework/01_protected_recheck.txt) 42/42；pre/post 67/67 IDENTICAL；资金 4/4、锁 2/2、C 12/12、E0 6/6、E1 5/5、正式 baseline 2/2、real-h2 1/1；LOCAL-R1 git clean；正式 registry 未写；reused 7 文件 git-clean 且 hash 一致。
- **最终判定：D1 resolved；最终仍 overall PASS**（限 E2 T209-PREP 独立验收）。R1-R5 保留；不构成正式 T209、质量通过、基线/发布批准；未记录通过标记。
- round 2 证据：[rework/](independent/rework/)（junit-40/80/6、collect-120、setup-show-40、11 探针、01/02/03/04/05/06/08/09 复跑、command log）。
