# T900 证据索引（最终）

2026-11-20/21（Asia/Shanghai）。独立验收窗口 `t900-acceptance`。本目录只含 T900 自写探针、只读复算输出、浏览器证据与负例日志；不含产品源码、测试、题集或账本副本。

## 阶段二（2026-11-21）· 正式总验收：**有保留通过**

| 类别 | 路径 | 内容 | 状态 |
| --- | --- | --- | --- |
| 报告 | `../../T900-ACCEPTANCE/report.md` | 阶段二正式验收报告：v0.2 冻结门、门禁复跑、B0/N/C/U/H2、八硬门、D-011、负例、资金、浏览器、限制 | 交付 |
| 结论 | `../../review.md` | T900 独立总判定：**有保留通过**（20 PASS / 0 FAIL / 0 BLOCKED / 1 NOT-RUN） | 交付 |
| 区块 | `../../T900-ACCEPTANCE/p2-report-block.md` | 给 `p2-report.md` 的独立结论区块 | 交付 |
| 冻结 | `probes/freeze_v2.py` → `probes/out/freeze_v2_final.json`、`logs/freeze-v2.log` | v0.2：47 技术工件 drift 0；2 台账前缀 violations 0；missing 0；exit 0 | 已运行 |
| 门禁 | `phase2/gate-result.rerun.json`、`phase2/gate-rerun-compare.json`、`logs/wire-real-ncu-t900.log` | `wire_real_ncu.py` 独立 exit 0；与冻结 JSON `d4c98f92…` / 53,053 B **逐字节相同** | 已运行 |
| 门禁 | `probes/gate_audit.py` → `probes/out/gate_audit.json` | 47 行 38/0/0/9、`reason_codes=[]`、行 id 摘要、八硬门、N/C/U/H2、tallies、证据清单；**50 项断言 0 失败** | 已运行 |
| D-011 | `probes/d011_probe.py` → `probes/out/d011_probe.json` | 披露 10/10/1；自报放大不采；伪造计划数被拒；自造 U01 run 级失败双 blocked；对照 pass | 已运行 |
| 负例 | `probes/negatives_probe.py` → `probes/out/negatives_probe.json` | 卡文件=聚合哈希 → blocked；伪造 attested 99/actual 12 → blocked；对照 pass | 已运行 |
| B0 | `phase2/b0-diff.json`、`phase2/b0-admit.json`、`logs/b0-phase2.log` | verify/restore/list/diff/admit 全 exit 0；7 工件逐字节一致；`2226fa20…` | 已运行 |
| T208 | `probes/t208_audit.py` → `probes/out/t208_audit.json`、`logs/t208-judge-budget.txt` | 24/24、4 scored + 1 unknown、硬失败 retained、0.0383、GO/plan；judge budget 27 passed | 已运行 |
| 资金 | `probes/funds_audit.py` → `probes/out/funds_audit_phase2.json`、`logs/phase2-zero-new-usage-final.txt` | 2679/2679/0；阶段/中心余额；本轮新增 0（账本 088dec… 不变） | 已运行 |
| 浏览器 | `browser/t08-phase2.log`、`browser/d3p2-run.log`、`browser/d3p2/actual/playwright-t900-phase2.json` | T08 10/10；acceptance-05 2/2（`external=[]`） | 已运行 |
| 浏览器 | `browser/d3p2/screenshots/t900-phase2/05-sources/*.png` | 来源抽屉、受保护原件、删除后失效、新问答（5 张） | 已保存 |

阶段二结果：技术门通过；B0 40/40、38 通过、24/24、OCR 8/8；N/C/U 8/8、6/6、10/10（无条件 7/2/9，正式 8/6/10）；H2 30/36、10/5/5/5/5、29/30、硬失败 0、必需未知 0；八硬门汇总 pass；D-011 与两组负例通过；B0 档案恢复；浏览器通过；本轮新增 0。保留项见 `../../review.md` §保留项 与 `../../T900-ACCEPTANCE/report.md` §12。

## 阶段一证据（2026-11-20）

| 类别 | 路径 | 内容 | 状态 |
| --- | --- | --- | --- |
| 报告 | `../../T900-PREP/prep.md` | 阶段一总表、逐包清单、B0 恢复、资金、浏览器、负例、缺口、阶段二待办 | 交付 |
| 探针 | `probes/funds_audit.py` → `probes/out/funds_audit.json` | 共享账本只读重算：2679/2679 配对、B0 112/112、中心/阶段余额、GO/预算/账本绑定、重复项、请求累计 | 已运行 exit 0 |
| 探针 | `probes/chain_trace.py` → `probes/out/chain_trace.json` | B0 回执↔admission↔baseline↔approval↔archive 摘要闭合；T206/T208/T209 回执↔账本 | 已运行 exit 0 |
| 探针 | `probes/evidence_inventory.py` → `probes/out/evidence_inventory.json` | T201–T209 与四个新包的目录、三层文件、文档摘要与当前源码匹配（启发式：64/16 位十六进制） | 已运行 exit 0 |
| B0 | `logs/b0-t900-verify-restore-list.log` | `baseline verify` / 隔离 `restore` / `list` 原始输出与退出码（0/0/0） | 已运行 |
| B0 | `logs/b0-diff-restored.json` | 恢复基线 vs 当前 B0 的 `p2-diff`（exit 0；Q25/Q33 仍失败；release blocked） | 已运行 |
| B0 | `logs/b0-admit-t900.json` | `p2-admit` 独立重算的 admission（proof 与存档一致；evidence 2226fa…） | 已运行 exit 0 |
| B0 | `logs/b0-archive-manifest.json`、`logs/b0-list-official.txt`、`logs/b0-list-restored.txt` | 归档清单副本、官方/恢复列表 | 已保存 |
| B0 | `logs/b0-restore-compare.json` | 归档 vs 恢复：baseline 5/6 同（仅 `baseline.json` 的 `run_dir` 重写）、run 7/7 同 | 已保存 |
| 负例 | `logs/neg-wrong-binding-archive.log` | 篡改归档字节 → `BaselineArchiveError`，exit 3 | 已复现拒绝 |
| 负例 | `logs/neg-wrong-binding-receipt.log` | receipt.baseline_id 错绑 → `b0_approval_receipt_mismatch`，exit 3，目标未创建 | 已复现拒绝 |
| 负例 | `logs/neg-false-applicability-unapproved-template.log` | 未批准模板冒充正式配置 → `b0_gate_file_not_approved`，exit 3 | 已复现拒绝 |
| 负例 | `logs/neg-false-applicability-old-baseline.log` | 旧 P1 基线跨 pipeline 套用 → `CrossVersionBaselineError`，exit 3 | 已复现拒绝 |
| 候选 | `logs/candidate-snapshot.txt` | 22:53 快照：44 修改/453 未跟踪；关键文件 SHA-256；任务 4 根目录临时文件清单 | 快照 |
| 零新增 | `logs/zero-new-usage.txt` | 收尾时账本/预算/GO 摘要；账本 5,359 行；B0 结束后 0 行 | 已核 |
| 回归 | `logs/collect-t209-six.txt` | T209 六文件 `--collect-only`：157 collected，exit 0（未执行） | 已收集 |
| 浏览器 | `browser/summary.json` | 两轮离线浏览器结果、版本、断言、截图、清理 | 已运行 |
| 浏览器 | `browser/t08-run.log` | T08 stub 后端 + Vite：02-chat + 04-kinds，10 passed / 43.3s，exit 0 | 已运行 |
| 浏览器 | `browser/d3-run.log`、`browser/d3/actual/playwright-t900-phase1.json` | acceptance-05：2 expected / 0 unexpected；外发 0 | 已运行 |
| 浏览器 | `browser/d3/screenshots/t900-phase1/05-sources/*.png` | 来源抽屉、受保护原件、删除后失效态、删除后新问答（5 张） | 已保存 |
| 浏览器 | `browser/d3/actual/t900-phase1/a14-protected-file.json`、`a19-*.json` | 实际接口响应：原件 200/nosniff；删除 applied；新问答未引用 D03 | 已保存 |

备注：

- 浏览器运行在 `frontend/` 下产生仅被 `.gitignore` 覆盖的测试缓存（`.e2e-data/`、`e2e/.auth/`、`test-results/`、`playwright-report/`）；`git status --short -- frontend` 在运行前后均为空，未改源码或测试。
- 运行器曾生成 `browser/d3/tmp/`（隔离 SQLite/上传副本与 Playwright HTML 报告），交付前已删除；截图、断言 JSON、服务日志与运行记录均保留。
- 仓库根 `.tmp-t900-isolated/` 已按任务书“自建自清”删除；其 B0 恢复/负例输出已复制到本目录 `logs/`。
- 归档清单、admission、diff 均为只读来源的副本；原文件未改。
