# P2 后续收尾 · 重新资格化与重新冻结报告

- 日期：2026-11-21（Asia/Shanghai）｜分支 `codex/p2-e2e`｜HEAD `93486b6`（工作树未提交）
- 性质：**开发自测 + 真实单次 B0 + 正式门禁 + 重新冻结**。独立复验结论由独立上下文另出（见 §9）。
- 候选：[`candidate.md`](candidate.md)｜新冻结件：[`candidate-freeze.v0_3.json`](candidate-freeze.v0_3.json)（`payload_sha256=13e9d0996c329f9da6c86a72b8759b1e357f8f379fcf8028847bd273359456af`，22 个文件）
- 证据口径：**开发自测 / 独立复验 / Mock 浏览器 / 真实调用** 四类分列；未执行项一律 `NOT-RUN`。

## 1. 当前结论（先看这段）

**修复候选已完成本机重新资格化：同流水线的新真实 B0 通过全部已批准门槛，正式跨场景门禁 `pass`（0 blocked / 0 pending），FU-2 端到端派生（4/4 卡 + 官方验卡 + 确定性）与浏览器 29/29 均跑通，新冻结件已生成。发布仍由你决定；真实受限批次与真实亲验不在本轮授权内。**

| 项 | 状态 | 一句话 |
|---|---|---|
| FU-2 目录依赖（`cd backend` 必红） | **PASS** | 用例内 `monkeypatch.chdir(ROOT)`；仓库根与 `backend` 各 **19 passed** |
| FU-2 独立派生正例（正式 CLI 出卡） | **PASS（附保留）** | **4/4 场景卡**产出、官方 `validate_hard_evidence_scorecard` **4/4 ok**、三输出目录逐字节确定性；合成证据为 incomplete → 四轴 unknown、`verified=false`（未伪造 pass） |
| FU-1～4 定向集 + B0 回归 | **PASS** | **86 passed**（5+19+21+24+1+16），exit 0 |
| 集成 21 文件 | **PASS** | 重新登记前 **428 passed / 12 failed**（12 条=旧 B0 版本门）；重新登记后 **440 passed / 0 failed** |
| 版本门隔离正反例 | **PASS** | 负例仅 `candidate.pipeline` 阻断；模拟同身份 → `pass`；被准入身份真实复跑 **42 passed** |
| 候选指纹 + 原冻结件复核 | **PASS** | 47/47 对 `93486b6` 一致；2/2 台账前缀一致；改前 7/7 一致；无意外差异 |
| **新真实 B0** | **PASS** | 40/40 执行、**38/40** 正确、**精确 24/24**、**OCR 8/8 执行（7 通过）**、硬失败 0、未知 0、real_calls 112 |
| **新基线接收** | **PASS** | `2b40ee9b4740` 已登记（`p2-admit` + `p2-approve` exit 0） |
| **正式跨场景门禁** | **PASS** | `pass`，**39 / 0 / 0 / 10**；`candidate.pipeline`=pass、`b0.admission`=pass、`evidence_provenance`=pass |
| **重新冻结** | **PASS（待主人确认）** | `candidate-freeze.v0_3.json`，18 个文件逐字节锁定 |
| 隔离浏览器复验 | **PASS** | 修复断言文案后 **29 passed / 0 failed**，外部出站 **0** |
| 提交 / 推送 / 合并 / 部署 | **NOT-RUN** | 未获授权，全部未做 |

## 2. 现场核对（开工）

```
git rev-parse --abbrev-ref HEAD → codex/p2-e2e
git rev-parse HEAD             → 93486b6
git status --porcelain -uno    → 14 项（13 项含在 v1 指纹，另有 live_authorization / p2_release_inputs / 3 个启动器 / 2 个簿记件）
```

**开工漂移（已登记、文件全部保留、未回退）**：v1 指纹之外还有 6 个已跟踪改动，其中
`live_authorization.py`（产品，**改了流水线摘要**）与 `p2_release_inputs.py`（门禁基线登记常量，**不改**流水线摘要）
属产品面；`tools/start_local.py`、`一键启动.cmd`、`启动-真实问答.cmd` 属本地启动器；
`.claude/handoffs/_index.md`、`T207-QUALITY-REPAIR/manager.md` 属簿记件。分类与逐文件摘要见
[`evidence/candidate-inventory.json`](evidence/candidate-inventory.json) 的 `extra_tracked_drift`。

## 3. 本轮实际执行的检查（命令 → 退出码 → 分母）

| # | 类别 | 命令（仓库根；`py` = `.\.venv\Scripts\python.exe`） | 退出码 | 结果 |
|---|---|---|---|---|
| 1 | 开发自测 | `py -m pytest backend\tests\evaluation\test_p2_fu2_derive_cards.py -q` | 0 | **19 passed** |
| 2 | 开发自测 | 同上但 `cwd=backend`：`..\.venv\Scripts\python.exe -m pytest tests\evaluation\test_p2_fu2_derive_cards.py -q` | 0 | **19 passed**（修复前 1 failed） |
| 3 | 开发自测 | `py -m pytest test_p2_fu{1..4}_*.py ::test_live_mode_binds_actual_rag_index_revision test_p2_b0.py -q` | 0 | **86 passed**（26.74s / 复跑 41.00s） |
| 4 | 开发自测 | 21 文件集成集（重新登记**前**，`-rf`） | 1 | **428 passed / 12 failed**（171.64s），12 条全是 `candidate.pipeline` 旧 B0 版本门 |
| 4b | 开发自测 | 21 文件集成集（**重新登记后**，同一命令） | **0** | **440 passed / 0 failed**（149.12s）；见 [`evidence/logs/integration-post-requalification.log`](evidence/logs/integration-post-requalification.log) |
| 4c | 开发自测 | 3 个 release-gate 文件（重新登记后） | 0 | **42 passed**（原先 12 failed 的同一批） |
| 5 | 隔离实验 | `py .../version_gate_isolation.py` | 0 | 负例 `blocked`（仅 `candidate.pipeline`）；模拟同身份 `pass`（32/0/6） |
| 6 | 独立复跑 | 干净检出 `93486b6` + `PYTHONPATH=<clean>\backend\src`，3 个 release-gate 文件 | 0 | **42 passed**（26.35s / 22.67s 两次） |
| 7 | 开发自测 | `py .../requalify_offline.py` | 0 | 指纹 13/13 改后（1 项为本轮 FU-2 修正）、7/7 改前；47/47 冻结件；2/2 前缀 |
| 8 | 只读预检 | `py .../b0_preflight.py` | 0 | 沿用旧额度 → `stage_budget_insufficient`+`center_budget_insufficient:ocr`；拟议调额 → `ok` |
| 9 | 真实（授权后） | 环境预检 `preflight_env.py`（同进程注入 `.env` 白名单） | 0 | chat `deepseek-flash`@api.deepseek.com；embedding dashscope；OCR `ap-guangzhou` 启用 |
| 10 | 真实（授权后） | 调额 + 新 GO：`issue_b0_go.py --apply` | 0 | 预算 revision 10；GO 签发并固定路径复核 `production_ready=true`；nonce_len 32 |
| 11 | 真实（授权后） | 单次 `p2-run --mode live --visibility public`（run `p2-t209-b0-20261121-01`） | **0** | 391.21s；40/40 题；真实出站 chat 40 / embedding 36 / rerank 24 / OCR 12 |
| 12 | 真实（授权后） | `py -B tools\rag_eval.py baseline p2-admit --run var\eval\runs\p2-t209-b0-20261121-01\p2-run` | **0** | 40/40、38/40、精确 24/24、OCR 8/8、硬失败 0、未知 0；基线 `2b40ee9b4740` |
| 13 | 真实（授权后） | `baseline p2-approve --receipt ...` | 0 | 基线登记落盘（6 件登记目录） |
| 14 | 正式门禁 | `py .../run_gate.py --out-dir .../gate` | **0** | `pass`，39/0/0/10；`candidate.pipeline`=pass |
| 15 | 重新冻结 | `py .../freeze_candidate.py` | 0 | `candidate-freeze.v0_3.json`，18 文件锁定 |
| 16 | 浏览器（隔离） | `py -B backend\tests\acceptance\support\run_browser_acceptance.py --label p2requal-20261121 --evidence-root ...` | 1 → **0** | 首轮 28 passed / 1 failed（断言过期）；修正断言后 **29 passed / 0 failed**；外部出站 **0** |
| 17 | 探针 | `py .../fu2_feasibility_probe.py` | 0 | 合成 30 题/36 回合包通过正式 `prepare_annotation`；端到端 `NOT-RUN` |
| 18 | FU-2 端到端 | `py .../fu2_e2e_derive.py` → `tool derive-cards`（4 run，exit 0） | **0** | 4/4 卡产出（`2c5d37fa`/`3ec4aef2`/`a301c176`/`5e47b293`）；官方验卡 **4/4 ok**；三目录逐字节确定性；`network.external=0` |
| 19 | 浏览器（复跑） | 同一运行器 `--label p2requal2-20261121` | **0** | **29 passed / 0 failed** |

## 4. 新真实 B0 回执（run `p2-t209-b0-20261121-01`）

| 项 | 值 |
|---|---|
| 候选流水线 | `pipeline_source_sha256=13a962ed…`；`pipeline_version=d3ca88d2c515+13a962ed…` |
| 计划 | `plan_id=P2-T209-B0-20261121-01`；`plan_sha256=d38e3c7cdaf88f1bf7ed1d41f4e3c6bf4b4d96e867511a1a78c06662d5f71d2d` |
| GO | 阶段 `P2-LIVE`；`max_requests=unlimited`；`max_request_cny=0.5`；24h；跑完已按执行前字节恢复固定槽（`43e0f622…`，校验相等） |
| 执行 | `live / end_to_end`，串行、零重试、首错停止；耗时 **391.21s** |
| 质量 | 执行 **40/40**、正确 **38/40**（≥36）、精确 **24/24**、OCR 执行 **8/8**（通过 7）、硬失败 **0**、必要未知 **0**、错误 0、未执行 0 |
| 硬门禁 | `exact_value_contract=pass`、`citation_required=pass`、`trace_integrity=pass`；其余 5 项 `not_applicable` |
| 真实调用 | `real_calls=112`（chat 40 / embedding 36 / rerank 24 / OCR 12）；`mock_intercepted=0` |
| 准入 | `p2-admit` exit 0；`evidence_sha256=f94bbb5b…`；`p2_release_status=blocked_pending_n_c_u_h2_evidence`（N/C/U/H2 是下一道门，非 B0 失败） |
| 逐题证据 | `var/eval/runs/p2-t209-b0-20261121-01/p2-run/{cases,cases.jsonl,dataset.jsonl,requests.jsonl,run_manifest.json,run_result.json,summary.json,gate.json}`（7 件工件摘要见冻结件 `b0.run_artifacts`） |

## 5. 费用与账务（应用保守记账；供应商实账未出）

| 项 | 值 |
|---|---|
| 预留 / 结算 / 悬账 | **112 / 112 / 0** |
| 预留合计 | **6.586448 元** |
| 保守计入（`conservative_charge`） | **5.719853 元**（= `provider_billed_cny` 5.7198526，OCR 后付费尚未出账） |
| 批内上界 | 7.464016 元（未超） |
| P2-LIVE 阶段 | 调额 24.00→**32.00**（+8.00，`later_shared_reserve` 50.07→42.07）；执行后已计 **27.813622 / 32.00**，余 **4.186378** |
| 项目总上限 | 100.00 不变；执行前已计 37.175129，执行后 42.894982 |
| GO 恢复 | 固定槽 `43e0f622…` 恢复并校验相等 |

## 6. 正式门禁与重新冻结

- 门禁输入：复用已交付的正式接线 `wire_real_ncu.build_inputs`（真实 N/C/U + H2 聚合 + 绑定/适用性证明），
  **只**把 `b0` 换成本轮新基线；`candidate_pipeline` 由 `pipeline_source_sha256()` 现算。
- 结果：`decision=pass`，`release_allowed=false`，`owner_release_decision=not_decided`，
  **39 pass / 0 blocked / 0 pending / 10 observed**；`candidate.pipeline`、`b0.admission`、`evidence_provenance` 均 pass。
- **四处必须披露的源码/夹具改动**（都是"跟随已登记基线"，不是放宽判据）：
  1. `backend/src/mktkb/evaluation/p2_release_inputs.py`：已登记基线 `7981d4afc2d1` → `2b40ee9b4740`（含三份登记件摘要）；
  2. `backend/tests/evaluation/test_p2_release_gate_fixtures.py`：夹具改从上述常量取基线 id / run id（不再写死）；
  3. `backend/tests/evaluation/test_p2_release_gate_negative.py`：负例的假登记目录名同样改用常量，断言语义未变；
  4. `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/wire_real_ncu.py`：正式门禁接线脚本的 `b0` 块改用常量。
  批准配置 `gate_v0_3_approved.json`、八项硬门禁、分母与阈值、旧门禁快照与旧基线原件**全部原样**。
  这四个文件都**不在** `pipeline_source_sha256()` 覆盖集内，**已复核摘要仍为 `13a962ed…`**，故不影响新 B0 绑定。
  改动 1–2 落地后，原有 12 条版本门失败由 `blocked` 转为 `pass`（440/0），即"重新登记后自动变绿"，未靠改断言放行。
- 旧门禁快照（`CROSS-SCENARIO-GATE/gate-result.real-ncu.json`，38/0/9）保留未覆盖；新结果写在新目录。

## 7. 浏览器复验（隔离实例 + 受控替身网关）

- 运行器：`run_browser_acceptance.py`（后端 8188 + 独立数据目录 + 进程级出站闸门；Vite 5199）。
- **生成式问答标注**：本套件用 `ControlledModelGateway`/`EvidenceEchoGateway` **受控替身**回显证据字段，
  **不是真实模型生成**；文中"生成式问答"一律按 **Mock/替身** 理解。
- 结果：**29 passed / 0 failed**（首轮 28/1，修正断言后全绿），外部出站 `external_count=0`、本地 153。
- 首轮唯一失败与处置：`acceptance-07-update.spec.ts:217` 原先断言 `资料已更新，本次回答已中止，请重新查询。`，
  实际渲染为 `资料已更新，本次回答已中止，未保存旧版本答案；这不是服务故障，请基于最新资料重新查询。…`。
  **判定为验收断言过期，不是产品回归**（产品文案在 `backend/src/mktkb/copy.py`，HEAD 字节未改）。
  处置：把断言改为跟随 `copy.KNOWLEDGE_CHANGED` 的**完整新句**（更严，不放松），复跑 **29/29 全绿**。
- 覆盖：登录权限、上传发布、来源访问、缺字段提示、换版、删除后失效、响应式与布局、A-29 无外泄，逐项见
  `browser/actual/playwright-p2requal-20261121.json` 与截图。

## 8. 未执行 / 阻断（不得计为通过）

| # | 项 | 状态 | 原因 / 所需 |
|---|---|---|---|
| 1 | FU-2「独立合成样本 → 正式 `derive-cards` CLI 出卡 → 正式验证器验卡」 | **已关闭（附保留）** | 4/4 卡 + 官方验卡 4/4 + 三目录确定性；合成证据 incomplete → 四轴 unknown、`verified=false`，未伪造 pass |
| 2 | 四真实 run 的 `derive-cards` CLI 组合（真 binding） | **NOT-RUN** | 无受限真件授权；合成 4-run 已按 `--compose never` 逐 run 出卡 |
| 3 | 浏览器 `acceptance-07` 全绿 | **已关闭** | 断言改为跟随 `copy.KNOWLEDGE_CHANGED` 完整新句，复跑 29/29 |
| 4 | 真实模型/OCR 的**主人亲验**（生成式问答、来源详情） | **NOT-RUN** | 需主人另行授权 `S2-OWNER-ACCEPTANCE`（10.00 元阶段，已用 10/106 次） |
| 5 | N/C/U 6 条原机械失败（N01/C01/C02/C05/C06/U01）与 D-011 披露 | 保留原样 | 历史证据适用性未变，未重跑 |
| 6 | H2 30 题历史受限聚合 | 保留原样 | 未重跑 |
| 7 | 历史泄露清单 746 件逐件复核 | **NOT-RUN** | 按任务书"只登记不改" |
| 7b | 三张卡的真实**分享副本**（严格模式）再扫描 | **NOT-RUN** | 分享副本属对外动作，需单独授权；派生件的公开产物已由 `derive-cards` 的 strict 模式产出 |
| 8 | 供应商实账核对 | **NOT-RUN** | OCR 后付费未出账 |
| 9 | 提交 / 推送 / 合并 / 部署 | **NOT-RUN** | 未获授权 |

## 9. 独立复验（与本报告分开记录）

- 本轮**开发自测**已完整记录于上；**独立复核**由独立上下文按
  [`candidate-freeze.v0_3.json`](candidate-freeze.v0_3.json) + 本报告 §3 命令清单定向复跑，
  结论另出文件，**不得**以本报告替代。
- 复用验收方既有探针（`docs/reports/OBS-EVAL/P2/FOLLOW-UP/review-evidence/probes/`）可复跑
  FU-1/FU-3/FU-4/字节扫描；本轮新增脚本见 `evidence/scripts/`。

## 10. 需要主人决定

| # | 事项 | 影响 |
|---|---|---|
| **D1** | 是否**发布**本新冻结候选（`payload_sha256=13e9d099…`） | 门禁技术结论 `pass`，但 `release_allowed=false`、`owner_release_decision=not_decided` 由主人填 |
| D2 | 是否接受「门禁重新登记基线 + 三处夹具/接线跟随」这 4 个文件的改动（§6）作为发布面的一部分 | 否 → 需改为外部登记方式或回退（回退会让 12 条版本门重新变红） |
| D3 | ~~是否要求先把 FU-2 端到端派生正例补齐再发布~~ | **已处置**：4/4 卡 + 官方验卡通过；保留项仅"合成证据 incomplete → 四轴 unknown、verified=false" |
| D4 | ~~是否修 `acceptance-07` 断言文案~~ | **已处置**：断言跟随产品文案，浏览器 29/29；如需保留旧断言请告知回退 |
| D5 | 是否授权真实亲验 live 部分（§8 #4） | 影响亲验覆盖率与费用（`S2-OWNER-ACCEPTANCE` 余 96 次 / 9.99 元） |
| D6 | 提交/推送/合并/部署是否授权 | 当前全部未做，工作树交付 |

## 11. 交付清单与提交建议（提交本身未执行）

**交付形态**：工作树交付。`git add` / `commit` / `push` / `merge` / `deploy` 均**未执行**（各自需授权）。

建议提交内容（两批，便于回滚）：

| 批次 | 文件 | 说明 |
|---|---|---|
| A 产品/测试/门禁接线（19） | `candidate-freeze.v0_3.json` → `candidate.files` 全量 | 逐文件 SHA-256/字节已锁定 |
| B 证据与报告（新增目录） | `docs/reports/OBS-EVAL/P2/FOLLOW-UP/requalification/**` | 报告、冻结件、preflight、gate、browser、logs、scripts |
| C 运行数据（**不入库**） | `var/eval/runs/p2-t209-b0-20261121-01/**`、`var/eval/baselines/2b40ee9b4740/**`、`var/eval/t209-prep/b0-live-20261121/**` | 与既有约定一致：`var/**` 为机内材料，按路径登记引用 |

建议提交信息：

```
chore(p2): requalify candidate with new real B0 and refreeze

- new real B0 p2-t209-b0-20261121-01 (live/end_to_end): 40/40, 38/40 pass,
  exact 24/24, OCR 8/8 executed, hard failures 0, unknown 0, real calls 112
- baseline 2b40ee9b4740 registered and accepted (p2-admit + p2-approve)
- formal cross-scenario gate: pass (39/0/0/10), candidate.pipeline pass
- re-register gate baseline pins (criteria unchanged); fixtures/wiring follow
- FU-2 cwd-dependency fix; browser knowledge_changed assertion follows copy
- freeze: candidate-freeze.v0_3.json payload_sha256=13e9d099…
```

## 12. 证据索引

| 证据 | 路径 |
|---|---|
| 候选清单（v2 指纹 + 漂移 + 冻结件复核） | [`evidence/candidate-inventory.json`](evidence/candidate-inventory.json) |
| 候选说明 | [`candidate.md`](candidate.md) |
| 新冻结件 | [`candidate-freeze.v0_3.json`](candidate-freeze.v0_3.json) |
| B0 只读预检 + 绑定计划 | [`evidence/b0-preflight.json`](evidence/b0-preflight.json)、[`evidence/b0-request-plan.bound.json`](evidence/b0-request-plan.bound.json) |
| 请批单 | [`b0-preflight-request.md`](b0-preflight-request.md) |
| 版本门隔离正反例 | [`evidence/version-gate-isolation.json`](evidence/version-gate-isolation.json) |
| 调额 + GO 签发 | [`evidence/go-issue.json`](evidence/go-issue.json)、`evidence/budget.before.json`、`evidence/go-slot.before.json` |
| 新基线接收回执 | [`evidence/b0-acceptance-receipt.json`](evidence/b0-acceptance-receipt.json) |
| B0 运行日志与元数据 | `var/eval/t209-prep/b0-live-20261121/logs/`（`run.meta.json`、`p2-run.stdout-stderr.txt`、`p2-admit…`、`p2-approve.txt`、`env-preflight.txt`） |
| 正式门禁 | [`gate/gate-result.json`](gate/gate-result.json)、[`gate/inputs.json`](gate/inputs.json) |
| 浏览器 | `browser/actual/playwright-p2requal2-20261121.json`、`browser/actual/acceptance-state-p2requal2-20261121.json`、`browser/logs/`、`browser/screenshots/` |
| FU-2 端到端派生 | [`evidence/fu2-e2e-derive.json`](evidence/fu2-e2e-derive.json)、[`evidence/fu2-e2e-cards/`](evidence/fu2-e2e-cards/)（卡 + 证明 + 材料清单）、`evidence/scripts/fu2_e2e_derive.py` |
| FU-2 可行性探针 | [`evidence/fu2-feasibility.json`](evidence/fu2-feasibility.json) |
| 定向测试日志 | [`evidence/logs/fu-targeted-and-b0.log`](evidence/logs/fu-targeted-and-b0.log)、[`evidence/logs/clean-admitted-identity-gate.log`](evidence/logs/clean-admitted-identity-gate.log)、[`evidence/logs/integration-post-requalification.log`](evidence/logs/integration-post-requalification.log) |
| 可复跑脚本 | `evidence/scripts/{requalify_offline,b0_preflight,version_gate_isolation,issue_b0_go,run_gate,freeze_candidate,fu2_feasibility_probe,fu2_e2e_derive}.py` |
| 旧冻结件 / 旧门禁快照（保留） | `docs/reports/OBS-EVAL/P2/candidate-freeze.json`、`docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/gate-result.real-ncu.json` |
