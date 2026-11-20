# P2 · T900 阶段一预备核验报告

**角色**　全新独立验收窗口 `t900-acceptance`（非开发方；不采信开发方结论，以本窗口实测为准）。
**日期**　2026-11-20（Asia/Shanghai）。
**现场**　分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；工作树保留既有未提交改动（快照时 44 修改 / 453 未跟踪）。
**环境**　Python 3.12.7（`.venv`）、pytest 9.1.1、Playwright 1.64.0、Node 24.16.0、Chromium build 1248。
**依据**　[T900 任务书](../../../../superpowers/plans/2026-11-20-p2-closeout-5-t900-acceptance.md)、[原 P2 任务书 T900 与 §8–10](../../../../superpowers/plans/2026-11-10-mktkb-p2-taskbook.md)、[正式门槛批准记录](../T209-PREP/threshold-approval.md)、[T209 关项记录](../T209-PREP/t209-b0-closeout.md)、[T900 证据索引](../evidence/T900/index.md)。
**证据根**　下文 `probes/…`、`logs/…`、`browser/…` 均相对 `docs/reports/OBS-EVAL/P2/evidence/T900/`（即 `../evidence/T900/`）；§2 的包路径相对 `docs/reports/OBS-EVAL/P2/`。
**本轮范围**　只做阶段一预备核验；正式质量门、H2 同批、N/C/U、跨场景正式判定全部留阶段二，标 `PENDING-TASK234`。未发真实请求、未出站、未重放产品、未新增费用。
**阶段一结论**　**`PREP-PARTIAL`**。基线、资金、浏览器、负例与证据链可核部分已完成；候选未冻结、请求上限口径冲突、T900 真实抽验预算不足、四个新增包未交付，维持阶段二前置阻断。

## 0. 状态统计（本报告总表）

| 状态 | 项数 |
| --- | ---: |
| PASS | 16 |
| FAIL | 1 |
| BLOCKED | 3 |
| NOT-RUN | 1 |
| PENDING-TASK234 | 2 |
| **合计** | **23** |

> 统计边界：`PASS` 只表示“本窗口实际跑过并得到预期结果”，不表示 P2 质量或发布通过；`BLOCKED` 表示受外部条件/授权限制未完成；`NOT-RUN` 表示本轮明确未执行；`PENDING-TASK234` 表示待任务 2/3/4 交付后由同一窗口续判。

## 1. 总表（逐项）

| # | 核验项 | 状态 | 命令 / 工件 | 版本 | 日期 | 限制 | 复核人 |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | T201–T209 与新增包“开发/独立/经理”三层证据存在性 | PASS | [逐包清单](#2-逐包证据清单)；`probes/out/evidence_inventory.json` | 各包交付时版本 | 2026-11-20 | 早期包经理接收以任务书 §10 进度记录为准，无独立 receipt 文件；T209 attempt3 结果复核经主人免除 | t900-acceptance |
| 2 | 各层所测源码摘要 vs 当前候选 | FAIL | `probes/out/evidence_inventory.json`；`logs/candidate-snapshot.txt` | HEAD 97b0066 + 未提交树 | 2026-11-20 22:47–22:53 | 候选未冻结：T201/T203/T205/R2/T206-LIVE 等摘要不符；任务 1/4 在审计期间继续写入（见 §8-G1） | t900-acceptance |
| 3 | T209 attempt3 额外独立结果复核的免除原话与范围 | PASS | [§3](#3-t209-attempt3-独立结果复核的免除原话与范围) | — | 2026-11-20 | 案卷只有经理转述，**无主人带引号原话**；属证据缺口 G5 | t900-acceptance |
| 4 | B0 归档 `7981d4afc2d1` 校验（13 文件 / 摘要 / 审批绑定） | PASS | `baseline verify` → `logs/b0-t900-verify-restore-list.log`；`logs/b0-archive-manifest.json` | gate v0.3 approved `7fa6f47a…` | 2026-11-20 | 只读校验，不改归档 | t900-acceptance |
| 5 | B0 隔离恢复 / 列表 / 同批 diff | PASS | [§4](#4-b0-归档恢复实测)；`logs/b0-diff-restored.json` | baseline `7981d4afc2d1` | 2026-11-20 | 恢复只重写 `run_dir`；7 份运行工件逐字节一致 | t900-acceptance |
| 6 | B0 准入独立重算（评分 + 八项硬门禁 + trace） | PASS | `p2-admit --out logs/b0-admit-t900.json`；重算 proof == 存档 proof | `mktkb.p2.b0.admission.v0.1` | 2026-11-20 | 38/40、精确 24/24、OCR 8/8 执行且 7/8 通过；硬门禁 0 失败/0 必需未知 | t900-acceptance |
| 7 | 回执 ↔ admission ↔ baseline ↔ approval ↔ archive 摘要闭合 | PASS | `probes/out/chain_trace.json` | evidence `2226fa20…` | 2026-11-20 | 仅 B0 主链；T206/T208/T209 另列 | t900-acceptance |
| 8 | 预算 / P2 阶段 / 四中心 / GO 绑定 | PASS | `probes/out/funds_audit.json`；`logs/zero-new-usage.txt` | 预算 40 / P2 24；GO `426c8228…`（封存） | 2026-11-20 | 当前固定槽 GO 是签发前旧 GO `43e0f622…`；B0 GO 存于 attempt3 `go/`（见 §5.4） | t900-acceptance |
| 9 | 预留 / 结算 / 未完成 / 重复请求 | PASS | `probes/out/funds_audit.json` | 账本 2,679 预留 / 2,679 结算 | 2026-11-20 | 供应商账单字段全 null；“重复”只能是账本内同 `request_sha256`/同 `item_id` 的启发式 | t900-acceptance |
| 10 | 供应商实账差异 | BLOCKED | `funds_audit.json` → `vendor_billed_nonnull_rows=0` | — | 2026-11-20 | 无供应商账单/后台只读权限；只能给保守账本口径，不能称实际账单 | t900-acceptance |
| 11 | 请求上限合规 | BLOCKED | `funds_audit.json` → `requests_used=2567`、`max_requests="unlimited"`、累计 2,679 | T209 任务书与 §12 口径冲突 | 2026-11-20 | 原任务书 §12 预授权 ≤2000；T209 taskbook 明写 `unlimited`；两处冲突需主人澄清（见 §8-G2） | t900-acceptance |
| 12 | 本轮新增真实用量 = 0 | PASS | `logs/zero-new-usage.txt`；账本最后一行 `2026-11-20T11:31:46Z`，之后 0 行 | ledger `088dec5f…` 前后一致 | 2026-11-20 | 覆盖本轮三路开发窗口与 T900 只读核验；不能替代逐窗口自证 | t900-acceptance |
| 13 | T900 真实抽验预算可行性 | BLOCKED | `funds_audit.json`：P2 阶段余 1.9062308，independent 中心余 0.05 | 原口径 ≤5 题 / 2 元 | 2026-11-20 | 无新 GO/调额不可执行；本轮未申请、未执行 | t900-acceptance |
| 14 | 原业务数据与隔离目录 | PASS | `var/mktkb.sqlite3` mtime 2026-11-05；B0 run 使用 `var/eval/runs/<run_id>/` 独立 data | — | 2026-11-20 | 只核 mtime/路径隔离，未对原库做内容审计 | t900-acceptance |
| 15 | 依赖 / API / schema 本轮影响 | PASS | `git status`：`backend/pyproject.toml`、API/schema 目录未在本轮修改 | — | 2026-11-20 | 候选仍含 17 个历史产品源码未提交改动与 44 个 tracked 修改（§8-G3） | t900-acceptance |
| 16 | 现有回归影响（P2 定向执行） | NOT-RUN | 仅 `--collect-only` 六文件：157 collected，exit 0（`logs/collect-t209-six.txt`） | pytest 9.1.1 | 2026-11-20 | 任务 1/4 并行编辑中，执行会混入半成品；正式执行留阶段二 | t900-acceptance |
| 17 | 浏览器 T08：02-chat + 04-kinds | PASS | `npx playwright test …` → `browser/t08-run.log` | Playwright 1.64.0 / Chromium 1248 | 2026-11-20 | 离线 stub 后端（真实 FastAPI + EchoGateway），非真实模型 | t900-acceptance |
| 18 | 浏览器 acceptance-05：来源打开 / 失效 / 权限 | PASS | `run_browser_acceptance.py … acceptance-05` → `browser/d3-run.log` | 同上 | 2026-11-20 | 真实 FastAPI +  seeded B0 + 受控模型/OCR 替身；`external=[]` | t900-acceptance |
| 19 | 证据链抽验（B0/T206/T208/T209） | PASS | `probes/out/chain_trace.json` | 见各 run | 2026-11-20 | T207 H2 聚合/两轴与四新包不在本轮闭合范围 | t900-acceptance |
| 20 | 错绑定负例 | PASS | `logs/neg-wrong-binding-archive.log`、`logs/neg-wrong-binding-receipt.log` | — | 2026-11-20 | 篡改只发生在 `.tmp-t900-isolated/` 副本 | t900-acceptance |
| 21 | 假适用性负例 | PASS | `logs/neg-false-applicability-unapproved-template.log`、`logs/neg-false-applicability-old-baseline.log` | — | 2026-11-20 | 覆盖“未批准模板冒充正式配置”“旧 P1 基线跨 pipeline 套用”两类 | t900-acceptance |
| 22 | 正式质量门 / H2 同批 / N/C/U / 八硬门禁正式判定 | PENDING-TASK234 | 任务 2/3/4 交付后续判 | — | — | 当前 H2 v0.2 卡缺失、N/C/U 为新配置下的正式证据待核 | t900-acceptance |
| 23 | 新增包 `H2-DOC-REBUILD` / `NCU-RELEASE-EVIDENCE` / `CROSS-SCENARIO-GATE` / `H2-REBUILT-CARDS` | PENDING-TASK234 | 四个目录均不存在（2026-11-20 22:40 检查） | — | — | `NOT-YET-DELIVERED`；任务 4 代码已有未验证文件，但无包报告/独立复核 | t900-acceptance |

## 2. 逐包证据清单

> 判定口径：三层“存在”按文件与任务书进度记录核实；摘要一致性只按文档中可提取的 64/16 位十六进制与当前文件 SHA-256 匹配（启发式，时间窗 22:47–22:53）。当前树仍在变动，结论只代表该时间窗。证据明细见 `probes/out/evidence_inventory.json`。

| 包 | 开发自测 | 独立复核 | 经理接收 | 所测源码摘要（示例） | 与当前候选 | 缺口 |
| --- | --- | --- | --- | --- | --- | --- |
| T201 | `T201/report.md` | `T201/review.md` | 任务书 §7 状态表 + §10（commit `3afe8c3`） | `p2_contracts.py cc3e33f8799e5298`；`p2_authorization.py b0a566b604d136b0` | **不一致**：现 `p2_contracts be873d7b38aa87e4`、`p2_authorization e10bd6910a8db4fb` | 无独立 manager receipt；摘要随后续包演进 |
| T202 | `T202/report.md` | `T202/review.md` | 任务书 §10（commit `97fba10`） | `dataset.py 945d150db9023b19`、`p2_dataset.py 5ddb3d4d3cb52a33`、`test_p2_dataset.py a7e390a390684ff3`、holdout manifest `8874985ef8f4aacc` | **一致（4 项）** | 其余摘要未逐项列；经理接收为进度记录 |
| T203 | `T203/report.md` | `T203/review.md`、`review-R1.md` | 任务书 §10（commit `897a751`、`eed3355`） | `product_adapter.py b7d3f372d65a3f70`、`p2_runner.py dd90e8cc49d1286d` | **不一致**：现 `product_adapter 93d0e54f9b6e…`、`p2_runner 420e3b9db686…` | 运行器后续经 T206/T209 多次修改 |
| T204 | `T204/report.md` | `T204/review.md` | 任务书 §10（commit `7cbabef`） | `p2_ingestion.py 2eda2b3207b3a734`、OCR 测试 2 项 | **部分一致（3 项）** | 其余摘要未逐项列 |
| T205 | `T205/report.md` | `T205/review.md`（6/7 有条件） | 任务书 §10（commit `d850b49`；2b 并入 R2） | 冻结模板 `gate_v0_3.json 3af301dba2d4dbd1` | **部分一致（1 项）**；`gate.py` 已改 | 2b/F2–F4 由 R2 关闭，需按 R2 证据看 |
| R2 | `R2/report.md` | `R2/review-R2.md` | 任务书 §10（commit `a8f2a6b`） | `p2_ingestion.py 2eda2b…`、`ocr_transcripts.py b975e8e4a08ed100` | **部分一致（2 项）** | 与 T203/T204/T205 的关联改动需按 R2 范围理解 |
| T206 | `T206/report.md` | `T206/PILOT/review-pilot.md` | `T206/PILOT/pm-acceptance.md` | 无源码摘要表；以 pilot 产物与账本为据 | 账本 42/42、0.5713583 复算一致 | 质量不达标（已如实记录，不属本包接收范围） |
| T206-PRE | `T206-PRE/report.md` | `review-T206-PRE.md`、`review-R1.md` | 任务书 §10（commit `1e422e9`） | `tracer.py 01dc81e40f20be46`、`gate_v0_3.json 3af301db…` | **部分一致（4 项）** | 经理接收为进度记录 |
| T206-LIVE | `T206-LIVE/report.md` | `review-T206-LIVE.md`、`review-R1.md` | 任务书 §10（commit `5ce4b16`） | F1/F2/F6 改动文件摘要 | **不一致**（当前 `cli`、`p2_live`、`p2_runner` 已改） | 经理接收为进度记录 |
| T207（A 路径） | `T207/report.md`、`T207/T207-final-report.md` | `T207/review-closeout.md`（限定接收） | T207 收口记录 + 后续重测接收 | classifier `49aa66cc…`（T207-RETEST 回执） | **审计开始时一致，22:53 变为 `61fb0dbd…`** | 任务 1 正在改同一分类器；见 G1 |
| T207-RETEST | 开发/执行记录在仓外批次根 | 独立复核 211/211（仓外 `independent-review-t207*`） | `T207-RETEST-20261119/manager-receipt.md`（PASS，29/30、硬失败 0） | `code_version 5bef4158…`；classifier `49aa66cc…` | 分类器现已变；其余 H2 证据仓外 | H2 v0.2 卡缺失、C27/C29 必需 unknown（任务 2/3 范围） |
| T208 | `T208-REAL-JUDGE-DEV/dev-report*.md`、`T208-GATE-WIRING-OFFLINE/dev-report.md` | `T208-REAL-JUDGE-IA/independent-review*.md`、`T208-GATE-WIRING-OFFLINE/independent/*` | `T208-REAL-JUDGE-LIVE/manager-receipt-attempt2.md`、`r02.md` | GATE-WIRING 文档 19 个完整摘要匹配当前文件 | **部分一致（19 项）** | E3 离线接线未见单独经理 receipt；真实裁判回执与账本已复算一致 |
| T209-PREP（E2 候选报告） | `T209-PREP/dev-report.md` | `independent-review.md`（PASS 2 轮）、`review-aggregate.json` | `manager-acceptance.json`（`T209_PREP_PASS`）、`manager-receipt.md` | 1 个 16 位前缀 + 30 个完整摘要匹配当前（`gate.py 102350994939fcd4`、`p2_b0.py 114158ef00f1`、`gate-config b1094cc72623` 等） | **一致（当前时点）** | 经理接收范围是候选报告工程，不含正式 B0 |
| T209 B0 接线/计划/attempt3 | `b0-wiring-*`、`b0-live-execution-attempt3-report.md`、plan draft | `b0-wiring-independent.md`、`b0-index-binding-independent-review.md`、`b0-live-attempt3-plan-review.md`（计划评审） | `b0-wiring-manager-receipt.md`、`b0-attempt3-baseline-approval.json`（主人批准） | 源码 `28aae43c…`；计划 `38d8c7f2…`；GO `426c8228…` | **一致**（pipeline source 重算同值） | **attempt3 结果无独立结果复核包（主人免除）** |
| T209-ENGINEERING-CLOSEOUT | `dev-report.md`、`dev-report-r03.md` | `independent-review*.md`（R03 PASS） | `manager-receipt-r03.md` | `p2_candidate_report.py 17a908a242f1…` 等 4 项 | **一致（4 项）** | R02 曾 BLOCKED，R03 关闭；Windows 目录联接仍缺实跑 |
| `H2-DOC-REBUILD` | 不存在 | 不存在 | 不存在 | — | — | **NOT-YET-DELIVERED** |
| `NCU-RELEASE-EVIDENCE` | 不存在 | 不存在 | 不存在 | — | — | **NOT-YET-DELIVERED** |
| `CROSS-SCENARIO-GATE` | 不存在包报告；`backend/src/mktkb/evaluation/p2_release_*.py` 已有未验证文件 | 不存在 | 不存在 | `p2_release_gate.py 3028980f6b1e0ca0`（22:53） | 未验证 | **NOT-YET-DELIVERED**；任务 4 正在写 |
| `H2-REBUILT-CARDS` | 不存在 | 不存在 | 不存在 | — | — | **NOT-YET-DELIVERED** |

补充：T201–T205 的“经理接收”在原任务书 §7/§10 有明确 commit 与状态记录，但没有像 T206/PILOT、T209-PREP 那样的独立 receipt 文件；这不等于未接收，属记录形态差异。

## 3. T209 attempt3 独立结果复核的免除原话与范围

**案卷中的两处记录（原文照录）**

1. `T209-PREP/t209-b0-closeout.md:3`：
   > “2026-11-20（Asia/Shanghai）。**T209 的正式 B0 基线已接收并关项。** 主人明确跳过 attempt3 的额外独立结果复核，随后批准接收。既有离线独立验收覆盖版本绑定修复，真实运行结果以 attempt3 原件和经理只读复算为据。”
2. `T209-PREP/b0-attempt3-baseline-approval.json` 的 `reason`：
   > “2026-11-20 主人批准接收候选基线并关闭 T209，且明确跳过本轮额外独立结果复核。依据 attempt3 已留存的真实运行证据及经理只读复核。范围限于正式 B0 基线接收。”

**范围界定（本窗口）**

- **被免除的**：为 attempt3 真实运行结果另起全新独立上下文，逐项复核 38/40、精确 24/24、OCR 8/8 执行且 7/8 通过、112 出站 / 5.7200466 元等结果。该范围**未经原安排的独立结果复核，属主人免除**。
- **未被免除、且已有独立证据的**：版本/索引绑定修复的离线独立验收（`b0-index-binding-independent-review.md`，123 passed/0 failed/0 skipped）；计划与预算的经理评审（`b0-live-attempt3-plan-review.md`）；接线的独立验收与经理接收（`b0-wiring-*.md`）。
- **明确不覆盖**：N/C/U、H2 同批、跨场景正式门禁、P2 发布、T900 总判定。批准 JSON 自述“范围限于正式 B0 基线接收”。
- **原话留档缺口（G5）**：仓库内没有主人带引号的原话，只有经理在 closeout 与 approval JSON 中的转述；`manager-decisions.md` 未登记该免除。故本报告只能证明“经理记录如此”，不能证明“主人原话如此”。
- **本窗口的补强（不等于补做免除包）**：本轮 `baseline p2-admit` 独立重算的 admission proof 与存档逐字段相等，`evidence_sha256=2226fa20…`；`p2-diff` 重算也得到 38/40、24/24、8/8 执行。这证明当前代码可从原件复现结果，但**不是**原安排的“额外独立结果复核”交付物。

## 4. B0 归档恢复实测

### 4.1 归档校验

命令（仓库根，`PYTHONPATH=backend/src`）：

```powershell
.\.venv\Scripts\python.exe -m mktkb.evaluation.cli baseline verify --archive var\eval\t209-prep\b0-baseline-7981d4afc2d1\archive
```

实际输出（`logs/b0-t900-verify-restore-list.log`）：

```text
archive ok baseline_id=7981d4afc2d1 run_id=p2-t209-b0-20261120-02 suite=b0 files=13 approved=yes schema=mktkb.baseline.archive.v0.1
source run_dir=D:\GPT项目\市场部AI知识库\var\eval\runs\p2-t209-b0-20261120-02\p2-run
VERIFY_EXIT=0
```

独立复算：13 个成员逐一 SHA-256/字节数匹配 manifest；`archive_manifest.json` SHA-256 = `be511c7e2814374cc2a7e6897196ef6e216e41c1c44574839f700c0ccdc2f9b3`（与关项记录一致）；审批绑定 `gate_result_sha256=2226fa208aec…`；`gate-config.json` SHA-256 = 正式配置 `b1094cc7…`。归档内 `b0-approval-receipt.json`、`docs/reports/…/b0-attempt3-baseline-approval.json` 与注册表回执三处 SHA-256 均为 `f760bf4f4a314772…`（579 B），其 `evidence_sha256=2226fa20…`。

### 4.2 隔离恢复、列表、同批 diff

```powershell
.\.venv\Scripts\python.exe -m mktkb.evaluation.cli baseline restore `
  --archive var\eval\t209-prep\b0-baseline-7981d4afc2d1\archive `
  --root .tmp-t900-isolated\b0\restore2\baselines `
  --runs-root .tmp-t900-isolated\b0\restore2\runs
.\.venv\Scripts\python.exe -m mktkb.evaluation.cli baseline list --root .tmp-t900-isolated\b0\restore2\baselines
.\.venv\Scripts\python.exe -m mktkb.evaluation.cli baseline p2-diff `
  --run var\eval\runs\p2-t209-b0-20261120-02\p2-run `
  --gate-config docs\evaluation\gate_v0_3_approved.json `
  --baseline 7981d4afc2d1 --root .tmp-t900-isolated\b0\restore\baselines `
  --out .tmp-t900-isolated\b0\diff-restored.json
```

结果：

- `restore` 退出 **0**，`files=13`，`approved=yes`，恢复目录 `.tmp-t900-isolated/b0/restore2/`（前一轮为 `restore/`；隔离目录已按“自建自清”清空，输出保留在日志中）。
- `list`（恢复根）退出 **0**，只列 `7981d4afc2d1`；官方根退出 **0**，列 `7981d4afc2d1` 与旧 P1 `bc6f6f906db1`。
- 7 份运行工件（`cases.jsonl`、`dataset.jsonl`、`gate.json`、`requests.jsonl`、`run_manifest.json`、`run_result.json`、`summary.json`）在源 run / 归档 / 恢复目录三处 SHA-256 完全相同。
- `baseline.json` 是唯一字节不同的成员：归档 2067 B vs 恢复 2082 B，差异仅为 `run_dir` 重写为隔离路径；其余 5 个 baseline 成员逐字节相同。
- `p2-diff` 退出 **0**；`still_failing=["Q25","Q33"]`，`new_failures=[]`，`baseline_approved=true`，`config_status=approved`，`p2_release_status=blocked_pending_n_c_u_h2_evidence`，`current_b0` 为 38/40、24/24、OCR 8/8 执行。

### 4.3 独立重算准入

```powershell
.\.venv\Scripts\python.exe -m mktkb.evaluation.cli baseline p2-admit `
  --run var\eval\runs\p2-t209-b0-20261120-02\p2-run `
  --gate-config docs\evaluation\gate_v0_3_approved.json `
  --out docs\reports\OBS-EVAL\P2\evidence\T900\logs\b0-admit-t900.json
```

退出 **0**。重算 JSON 去掉 `p2-admit` 附加的 `baseline_id`/`evidence_sha256` 包装后，与 `var/eval/baselines/7981d4afc2d1/b0-admission.json` **逐字段相等**；`evidence_sha256=2226fa20…`。重算结果：40/40 执行、38/40 通过、精确 24/24、OCR 8/8 执行（7 通过）、八项硬门禁 `pass/not_applicable`、`hard_failures=[]`、`unknown_count=0`、`p2_release_allowed=false`。

### 4.4 P1 差异与原业务数据

- P1 基线 `bc6f6f906db1`：`mode=live`、`scope=retrieval_only`、gate `v0.2`、quality `pass`、审批人主人（2026-11-09）。用 B0 run 对它做默认 diff 被拒：`CrossVersionBaselineError`（`08166b113481` ≠ `d3ca88d2c515+28aae43c…`），exit 3；只有显式 `compare_with` 才允许分析比较。
- 原业务库 `var/mktkb.sqlite3` mtime 为 2026-11-05（P2 真实运行之前），B0 使用 `var/eval/runs/p2-t209-b0-20261120-02/` 下的独立 SQLite/索引/存储；本轮未对原库执行写操作。

### 4.5 其他证据链抽验（回执 ↔ 工件 ↔ 接收记录）

| 链 | 抽验 | 结果 |
| --- | --- | --- |
| T209-PREP 经理接收 | `manager-acceptance.json` 绑定的 `independent-review.md` `eacfed3c…`、`review-aggregate.json` `63888d88…`、新测试 `f1edcaed…` | 3/3 与当前文件 SHA-256 相等 |
| T206 pilot | `pm-acceptance.md` 的 42 预留 / 42 结算 / 0.5713583 / 出站 39 | 账本复算一致（`chain_trace.json`） |
| T208 真实裁判 | `manager-receipt-attempt2.md` 的 24 调用 / 0.0383 / 输入 15,414 / 输出 934 tokens | 账本复算一致 |
| T209 attempt3 | 报告 112 出站 / 5.7200466 / chat 22,047+2,319 tokens | 账本与 summary 一致；决策级 `p2_admit` 复算 proof 相等 |

## 5. 资金与权限对账

### 5.1 只读重算总账（`probes/out/funds_audit.json`，22:44）

| 项 | 数值（CNY） | 说明 |
| --- | ---: | --- |
| 项目总上限 | 40.0000000 | `budget.json limit_cny=40` |
| 项目累计占用 | 37.1647137 | 历史 0.03 + S2 已占用 15.0266296 + P1 0.0143149 + P2 22.0937692；阶段额度分配另计 |
| 项目保守余额 | 2.8352863 | 40 − 37.1647137 |
| P2-LIVE 阶段上限 | 24.0000000 | 经 attempt2 前调额：20→24，P1 3→0.5、共享 1.57→0.07 |
| P2 阶段占用 | 22.0937692 | B0 attempt3 后 |
| **P2 阶段余额** | **1.9062308** | 24 − 22.0937692 |
| answer_retrieval | 4.5867812 / 上限 6.35 / 余 1.7632188 | B0 GO 中心 |
| ocr | 17.4500000 / 上限 17.50 / 余 0.05 | B0 GO 中心 |
| judge | 0.0569880 / 上限 0.10 / 余 0.043012 | T208 两轮合计 |
| independent | 0 / 上限 0.05 / 余 0.05 | 本轮真实抽验未执行 |

账本事实：2,679 笔预留 / 2,679 笔结算 / 待结算 0 / 孤儿结果 0 / 重复 `reservation_id` 0；历史导入 1 条。B0 run `p2-t209-b0-20261120-02`：112 预留 / 112 结算 / 预留合计 6.586448 / 保守结算 5.7200466（= summary `provider_billed_cny`）；chat 输入 22,047 tokens、输出 2,319，与 attempt3 报告一致。

### 5.2 B0 两次真实运行

| run | 结果 | 预留（元） | 保守结算（元） |
| --- | --- | ---: | ---: |
| `p2-t209-b0-20261120-01`（attempt2） | 准入 BLOCKED（trace_integrity） | 6.586448 | 5.7197526 |
| `p2-t209-b0-20261120-02`（attempt3） | 准入 PASS | 6.586448 | 5.7200466 |
| 合计 | — | 13.172896 | **11.4397992** |

- attempt3 单次 5.7200466 ≤ 授权上界 7.464016，单请求峰值预留 0.5 = 上限 0.5，未超单次授权。
- 但两次运行合计 11.4397992，占 P2 阶段 24 元的 47.7%；这是“同一 B0 目标因首次 trace 失败而重跑”的实际成本，不是新题组。该事实在关项记录中只单列 attempt3 的 5.7200466，未在资金段落汇总两次成本（本报告补记）。
- 供应商实账：2,679 条结果中 `provider_billed_cny` 非空 **0** 条；所有结论均为账本保守口径，不能称供应商实际账单。

### 5.3 重复请求与未完成项

- `duplicate_reservation_ids=0`；`pending=0`；`orphan_results=0`。
- 同 `request_sha256` 的重复组 113 组，全部落在同 run 内；逐项核对后仅 `ingest-index-embedding` 的批级拆分为多请求（B0 为 12 批），没有 `answer-*`/`ocr-*` 的重复计费项。
- 账本 `settled_failure=0`、`failed_rounds=0`、`rejected_rounds=0`、`unused_no_paid_attempt=0`（B0 summary）。

### 5.4 GO / 预算 / 账本绑定

| 绑定 | 值 | 核对 |
| --- | --- | --- |
| B0 gate `authorization.go_sha256` | `426c82281fe5412d47e7eb1a72ff900b60552633ec277a959a4cbc5afc25fa71` | = 封存 B0 GO（`attempt3/go/…sealed.json`）的 `payload_sha256` |
| 当前固定槽 `P2-LIVE-GO.json` | `43e0f6229efeae77334e821b91548b7024a1aefdf5824a9586f4c8d12330aaad` | 是签发前 T207 GO；`expires_utc=2026-11-20T02:51:29Z`，已过期；**不等于** B0 GO |
| `authorization.ledger_sha256` | `f4710b18…` | = 当前账本 `historical_prefix_sha256`；`ledger_binding_ok=true` |
| `authorization.budget_sha256` | `b2cff8a0…` | = 当前 `budget.json` 的 `payload_sha256` |
| 当前账本全文 SHA-256 | `088dec5f…` | 与 attempt3 报告“运行后”一致 |

说明：B0 运行结束后，固定槽按任务书恢复为签发前旧 GO（逐字节 `43e0f622…`）；B0 GO 原件保存在 `var/eval/t209-prep/b0-live-20261120-attempt3/go/`。因此“当前固定槽 GO 摘要”与“B0 绑定 GO 摘要”不同，是预期的槽位恢复，不是错绑；但关项记录“预算和 GO 摘要保持一致”的措辞会被误读，应改为“B0 绑定的封存 GO/预算/历史前缀与运行时一致”。（G4）

### 5.5 本轮新增 = 0

- `logs/zero-new-usage.txt`（22:54）：账本 `088dec5f…`、预算 `8f1b061b…`、GO `43e0f622…`，与 22:44 首轮重算完全相同。
- 账本最后一条时间 `2026-11-20T11:31:46.309888Z`；在其后（含本轮三路开发窗口 22:30 之后）**0 行**新增。
- 本轮 T900 只做只读读取、隔离恢复、离线浏览器与本地探针；未发送真实请求、未出站、未新增预留。

### 5.6 请求上限（冲突项）

- B0 签发时账本快照：2,567 预留 / 2,567 结算；B0 后 2,679 / 2,679。
- B0 gate `authorization.max_requests="unlimited"`，`requests_used=2567`；`HARD_MAX_REQUESTS` 代码常量为 1600，`MAX_GO_REQUESTS=1600`，但 `unlimited` 哨兵跳过上限。
- 原任务书 §12 预授权“累计请求 ≤2000”；T209 attempt3 任务书明写“`max_requests="unlimited"` 是累计账本口径，本轮逐项上限仍为 194 次”。两处口径不一致，且当前累计 2,679 > 2000。
- 本窗口不自行判定“越权”：维持 `BLOCKED`，需主人明确“2000 累计上限是否已被 T209 任务书的 unlimited 取代”。（G2）

## 6. 浏览器与接口

### 6.1 可运行用例清单（本机实测）

| 用例 | 环境 | 结果 |
| --- | --- | --- |
| `frontend/e2e/02-chat.spec.ts`（7 项：来源详情、歧义、无答案/部分可答不编造缺失字段、服务故障、网络失败重试、追问、删除会话） | T08 stub 后端（真实 FastAPI + EchoGateway）+ Vite 5173 | **7 passed** |
| `frontend/e2e/04-kinds-and-isolation.spec.ts`（3 项：冲突双来源、资料变更后来源失效、账号隔离） | 同上 | **3 passed** |
| `frontend/e2e/acceptance-05-sources.spec.ts`（2 项：Q01 来源抽屉 + 受保护原件 200；删除 D03 后旧来源 410/失效 + 新问答不引用已删来源） | 真实 FastAPI + seeded B0 + 受控模型/OCR（8188/5199） | **2 expected / 0 unexpected** |

命令与退出码：

```powershell
# 1) T08 离线功能（仓库根 → frontend）
npx playwright test --config playwright.config.ts e2e/02-chat.spec.ts e2e/04-kinds-and-isolation.spec.ts --project=functional --reporter=line
# exit 0；10 passed (43.3s)

# 2) acceptance-05（仓库根）
.\.venv\Scripts\python.exe -B backend\tests\acceptance\support\run_browser_acceptance.py `
  --label t900-phase1 `
  --evidence-root docs\reports\OBS-EVAL\P2\evidence\T900\browser\d3 `
  --playwright-args "e2e/acceptance-05-sources.spec.ts"
# exit 0；PLAYWRIGHT EXIT 0；2 expected / 0 unexpected；external=[]、local_count=131
```

断言与实际接口响应：

- a14：受保护原件 `GET /api/v1/messages/<id>/sources/<id>/file` → **200**，`content-type=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`，`x-content-type-options=nosniff`（`browser/d3/actual/t900-phase1/a14-protected-file.json`）。
- a19：删除 `doc-guide` → `{"applied":true,"deleted":true,"revision":12}`；删除后原件 **410**；旧消息抽屉显示“来源已失效，内容不可访问/已删除”且无原件链接；新问答 `cited_deleted_source=false`（`a19-*.json`）。
- 截图（交付目录）：`browser/d3/screenshots/t900-phase1/05-sources/01-a14-answer.png`、`02-a14-source-drawer.png`、`03-a19-before-delete.png`、`04-a19-expired-source.png`、`05-a19-new-chat-no-evidence.png`。

### 6.2 未跑与原因

- `acceptance-06-conflict`、`acceptance-07-update` 等未选：本轮只选受影响且与“来源/缺字段/隔离”直接相关的项；整套 acceptance 有跨 spec 状态累积，阶段二再按正式清单整轮执行。
- T900 真实产品重放：**未跑**（本轮禁止真实请求/产品重放）。
- 端口清理：两轮结束后 8077/5173/8188/5199 均无监听，无残留进程。

## 7. 负例（自写，实际拒绝）

> 所有负例只操作 `.tmp-t900-isolated/` 下的副本或只读路径；不改归档、baseline 注册表或运行原件。

| 负例 | 构造 | 命令 | 退出码 | 实际拒绝原因 |
| --- | --- | --- | ---: | --- |
| 错绑定-1（归档字节） | 复制 B0 归档到 `.tmp-t900-isolated/neg/archive-tamper`，在 `run/summary.json` 末尾追加 1 字节，不改 manifest | `baseline verify --archive .tmp-t900-isolated\neg\archive-tamper` | **3** | `BaselineArchiveError: 归档文件 run/summary.json 字节数不符（记录 206237，实际 206238）` |
| 错绑定-2（receipt） | 复制 `b0-attempt3-baseline-approval.json`，把 `baseline_id` 改为 `deadbeefcafe` | `baseline p2-approve --run … --gate-config … --receipt .tmp-t900-isolated\neg\receipt-wrong-baseline.json --root .tmp-t900-isolated\neg\baselines-wrong-receipt` | **3** | `B0Error: b0_approval_receipt_mismatch`；目标根**未创建**（fail-closed） |
| 假适用性-1（未批准模板） | 用冻结模板 `docs/evaluation/gate_v0_3.json`（`unapproved`）冒充正式配置 | `baseline p2-diff --run …B0… --gate-config docs\evaluation\gate_v0_3.json --baseline 7981d4afc2d1 --root var\eval\baselines` | **3** | `B0Error: b0_gate_file_not_approved` |
| 假适用性-2（旧 P1 基线） | 把 `bc6f6f906db1`（v0.2/retrieval_only）当作 B0 的可比基线 | `baseline p2-diff --run …B0… --gate-config docs\evaluation\gate_v0_3_approved.json --baseline bc6f6f906db1 --root var\eval\baselines` | **3** | `CrossVersionBaselineError: 跨 pipeline_version 的 baseline 默认拒绝：'08166b113481' != 'd3ca88d2c515+28aae43c…'` |

结论：四类负例均被拒绝，且失败发生在写目标之前；错绑定与假适用性不会产生“看似通过”的基线。

## 8. 当前阻断项与缺口（不因“后面会修”省略）

- **G1（FAIL，候选未冻结）**：工作树 44 tracked 修改 / 453 未跟踪，含 17 个历史产品源码修改（`rag/*`、`qa/service.py`、`providers/*`、`conversations/*` 等）与任务 4 根目录临时文件 `tmp_t4_*.py`、`tmp_run_*.txt`、`tmp_qc.txt`。审计期间任务 1 把 `p2_hard_evidence.py` 从 `49aa66cc…` 改为 `61fb0dbd…`；任务 4 修改 `p2_scoring.py`/`cli.py` 并新增 `p2_release_gate.py`（17,904 B，无测试/无包报告）。**当前没有可引用的冻结候选**，早期包摘要漂移无法用“当前树”裁决。
- **G2（BLOCKED，请求上限）**：累计 2,679 预留（B0 签发时 2,567）> 原任务书 §12 的 ≤2000；B0 GO `max_requests="unlimited"`；T209 任务书又明写 unlimited 是累计口径、逐项 194。需主人澄清以哪一处为准。
- **G3（范围风险）**：T900 原口径“最多 5 题、independent 2 元”在现余额下不可执行：P2 阶段仅余 **1.9062308**，independent 中心仅余 **0.05**。任何真实抽验都需新 GO/调额，本轮未申请。
- **G4（表述/追溯）**：关项记录“GO 摘要保持一致”易被误读为“当前固定槽 GO = B0 GO”。实测当前槽是 `43e0f622…`（签发前旧 GO），B0 GO 是 `426c8228…`（封存件）。绑定本身正确，表述应改。
- **G5（免除原话）**：attempt3 额外独立结果复核的“主人原话”未入卷；只有经理转述（closeout + approval JSON）。`manager-decisions.md` 未登记 D-002。
- **G6（新增包未交付）**：`H2-DOC-REBUILD`、`NCU-RELEASE-EVIDENCE`、`CROSS-SCENARIO-GATE`、`H2-REBUILT-CARDS` 四个目录均不存在；H2 v0.2 硬证据卡仍缺失（仓内只有 v0.1 run card 与 v0.2 scorecard 试跑）。正式 H2/跨场景行只能 `PENDING-TASK234`。
- **G7（T208 E3 经理层）**：E3 离线接线有开发报告与独立探针，但未见单独经理 receipt；真实裁判 attempt2 有 receipt 且金额/调用已复算一致。列为记录缺口，不否定 T208 真实结果。
- **G8（成本提示）**：B0 两次运行合计 11.4397992 元；attempt2 因 `trace_integrity` BLOCKED 仍保守结算 5.7197526。若阶段二还需真实复验，余额 1.9062308 不足以覆盖任何接近 B0 规模的运行。
- **G9（回归未执行）**：本轮只 `--collect-only` 157 项，未执行 P2 定向/旧回归；不能据此声称“现有回归无影响”。正式执行留阶段二，且必须在冻结候选上做。

## 9. 阶段二（最终总判定）待办与所需工件

> 同一窗口 `t900-acceptance` 继续；以下输入齐备后由经理通知本窗口做最终总判定。以下每项都要求“冻结候选 + 原始命令 + 退出码 + 工件路径 + 独立复核”。

### 9.1 任务 1（H2 工程 / 离线重建接入）
- 冻结源码与测试 SHA-256（至少 `p2_hard_evidence.py`、相关 `p2_evidence_rescore*`、新增测试），以及冻结时间点。
- 报告/独立评审/经理接收三层文件；合成覆盖：同版本真命中、跨版本排除、缺身份/使用层→unknown、定位型引用原行为、派生评分版本与原运行身份可查。
- 零真实请求/零出站证明（账本/预算/GO 摘要前后一致）。
- 对 `p2_hard_evidence.py` 从 `49aa66cc…` → 现行 `61fb0d…` 的变更说明：谁改、改了什么、是否影响 T207 29/30 与 B0。

### 9.2 任务 2（H2-REBUILT-CARDS）
- `H2-REBUILT-CARDS/report.md` + 独立复核 + 经理接收。
- 批次身份、完整性摘要、覆盖与五层计数（10/5/5/5/5）、各轴计数、必需/非必需 unknown、实际严格校验结果（`verified` 实际值）、前后原件摘要、零调用记录。
- 给任务 4 的合规聚合与来源证明（不得含题干/标签/逐题/源单元/key）。
- C25 非必需 unknown 的保留方式，以及 C27/C29 两轴 clean 的证明。

### 9.3 任务 3（NCU-RELEASE-EVIDENCE）
- N/C/U 在 **新批准配置 `7fa6f47a…`** 下的正式证据：run ID、config_hash、逐案结果、U 的 L/R 组成（1 真实 + 9 本地）、N 8/8、C 6/6、U 10/10。
- 从原始工件到 gate 行的映射；历史 run 绑定旧配置摘要时如何“只分析、不放行”。
- 独立复核 + 经理接收；零新增真实请求证明。

### 9.4 任务 4（CROSS-SCENARIO-GATE）
- `p2_release_gate.py` 及输入/模型/公开/ H2 子模块的冻结 SHA-256；测试文件与执行结果。
- 输入契约、合成用例、正式门输出 JSON：五层（B0/精确/OCR/N-C/U/H2）与八项硬门禁逐项状态、最小样本、必需/非必需 unknown、`verified` 实际值、发布日期/阻断原因。
- 错绑定/假适用性负例（跨版本、缺卡、未批准配置、伪造聚合）实际拒绝输出。
- 报告/独立评审/经理接收三层；零外部请求/零新增费用证明。
- 特别要求：不得把“H2 卡缺失”默认成 pass；不得用合成卡替代正式卡。

### 9.5 通用（经理/主人）
- 冻结候选：分支、HEAD、未提交 diff 摘要（或临时 commit 的 SHA）、关键文件 SHA-256 清单；确认不再变动后才可做最终判定。
- 请求上限澄清（G2）与 T900 真实抽验授权（G3，如需）；若需真实抽验，给出题组、配额、费用上界、成本中心、新 GO。
- attempt3 免除的主人原话补录（G5）；四个新包的交付路径与白名单。

### 9.6 本窗口阶段二执行计划（收到输入后）
1. 重算 `git status` 与冻结摘要，确认候选未漂移。
2. 执行 P2 定向集成清单（至少 T209 六文件 + T201/T203/T204/T205 受影响用例），记录退出码。
3. 执行任务 4 正式门（离线）并对其输出做独立复核；必要时重跑浏览器受影响项。
4. 对 H2 四卡/组合只做外层聚合核验（不读受限内容），确认公开产物只含允许字段。
5. 复核资金/GO/账本与零新增；给出 `PASS/FAIL/BLOCKED/NOT-RUN` 最终总表与“通过/保留通过/返工/阻断”结论，交主人决定。

## 10. 证据纪律与分列

| 证据类别 | 本报告中的位置 | 边界 |
| --- | --- | --- |
| 开发自测 | §2 各包“开发自测”列 | 只引用开发报告/文件存在，不当作独立结论 |
| 独立离线 | §2 独立列、§4、§7、§9 | 本窗口实际命令/退出码/探针 |
| 已有真实运行 | §5、§4.3、§2 T206/T207/T208/T209 | 只读复算账本/回执/admission；未重放、未新增请求 |
| 浏览器 | §6 | 离线 stub/受控替身；非真实模型/OCR；断言对应实际接口响应 |

**与开发方结论的分歧**：本报告不采信“关项记录已说一致”作为证据；实测以归档、admission、账本、浏览器与负例为准。当前唯一与既有记录实质冲突的是 G2（请求上限）与 G4（GO 表述）；其余为版本漂移与记录形态问题。

## 11. 本轮写入与 Git 影响

- 新增：`docs/reports/OBS-EVAL/P2/T900-PREP/prep.md`、`docs/reports/OBS-EVAL/P2/evidence/T900/**`；隔离目录 `.tmp-t900-isolated/` 已按任务书“自建自清”删除（关键输出已复制到证据目录）。
- 未改：`backend/` 源码/测试、`frontend/` 源码/测试、`fixtures/`、`docs/evaluation/` 冻结题集与阈值、历史 run/账本/GO、T201–T209 既有证据目录。
- 浏览器运行在 `frontend/` 下产生被 `.gitignore` 覆盖的缓存（`.e2e-data/`、`e2e/.auth/`、`test-results/`、`playwright-report/`）；`git status --short -- frontend` 运行前后均为空。
- 未 commit / push / merge / 切换分支；未使用 `checkout`/`restore`/`stash`/`clean`/`reset`；未删除或移动既有文件。

---

**复核人**：`t900-acceptance`（全新独立验收窗口，非开发方）
**阶段一结论**：`PREP-PARTIAL`
**下一动作**：等经理转交任务 2/3/4 的冻结候选与正式证据；本窗口不另起。
