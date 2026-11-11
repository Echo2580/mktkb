# P2-T207 准备交付经理复核与决定（2026-11-11 08:5x）

- 角色：项目经理（Lead）。只读复核 + 决策，不改源码/计划正文（dev 交付物）。
- 现场：codex/p2-e2e @ 9a740ce；账本 `6b053520…`（1095 行/1,050,298 B）、预算 `79b21700…`、GO `79a5f318…` 三份只读复核**未变**；git 新增仅 `docs/reports/OBS-EVAL/P2/T207/**`；HEAD 未变。

## 1. 接收结论（T207 准备，G2 通过）
- 交付齐：plan/GO DRAFT×2/import recipe/cost-and-quota/fix-scope/runbook/report/evidence（16 文件）。
- 经理独立复算（亲自运行 p2_contracts，非引用 dev 自述）：`plan_sha256=d788a83b3b27ff4e4aa43cb89b2230012d4f89eeecd232e2ac489e398cb3a947`、233 项/60 case(55 真回合+INGEST+4 OCR 文档码)/254 请求/worst 8.127376/峰值 0.5/中心需求 `answer_retrieval 2.477376 + ocr 5.65`；`preflight_p2` 对**真实固定路径快照** `ok=true`、`requests_remaining=453`、`production_ready=true`；候选 GO `authorize_p2` 通过但 `production_ready=false`；固定路径真实 GO 按预期拒绝（`go_plan_id_mismatch`）。
- 结论：算术/契约/只读证据成立，**准备交付接收**；但矩阵当前不可执行（缺口清单成立），计划与 GO 均为暂定版，修后重建。

## 2. 经理补正（对准备交付的差异，均不改门槛）
1. **F2 解除（H2 语料包）**：`D:\mktkb-p2-holdout\v2\custodian-report.md` 已声明 H2 只用 fixtures 的 **D01–D06 + V01–V07（17 份）**，requires_ocr 全 false、未引用 D07–D10；case_id/分层/轮数可见性按 `audit.md` 表（manifest/audit/保管报告对开发、验收、经理可见），题干/答案仍禁读。H2 灌库需按保管报告 §6 的五条假设构造状态（V03 历史版、V04 发布为 v3、V01 与 D01 双有效冲突、V06 取代 D02、V05 发布删行且 V07 仍有效）；不得据此改题或按题调参。
2. **R2 重复 Q01 + OCR 请求漏计**：准备版的 R2=`Q01+U01+C05` 与 R1 的 B0 40 重复付费；R1 请求 230 漏计 12 页 OCR。修正拆分：**R1=B0 40+N8+C01–C04（52 回合；请求 242=208+22+12）**、**R2=U01+C05（2 回合；15 请求）**、**R3=C06（1 回合；6 请求）**；累计 263 请求、worst 约 8.145808 元（以修后脚本实算为准）。Q01 只在 R1 执行，且其版本槽必须在 R1 灌库中真实复现。
3. **F4 不作代码改造（口径决定）**：U 行 L/R 采用**报告级证据表**：U02–U10 取既有 `test_t09_mutation.py` 本地控制（L），U01 取 R2 真实 smoke（R）；公共平台矩阵只出 B0/N8/C6（均 live），U 不并入 `score_public_suites`。因此不引入 `evidence_basis/allow_mixed_basis` 的 API 变更，避免为凑矩阵放宽既有 `execution_mode_mixed` 检查。T207 产出「运行观测矩阵」（逐 case provenance：run_id/index_revision/config_hash/basis），**明确非 release 结论**；baseline 组成与证据口径由 T209 决定。
4. **F6 确认**：`gate_v0_3` unapproved → T207 不产 `release_ready`；收口语只能是「执行完成 + 观测值」，不得写质量达标/放行。
5. **F7 执行口径**：每次 run 新开一扇门（独立进程），不得复用同一 gate；`attempt_accounting_mismatch` 不放宽；runbook 已有约束，A 包补一条验证用例。
6. **计划/GO 重发**：修后由矩阵工具按 `max_requests=1200` 重建公开计划（累计授权：R1 801 / R2 1031 / R3 1050 左右），H2 计划 `max_requests=1100`；PM 按新 plan_sha 重签 GO；`budget.json` 不改；中心 8.5/6.5/3/2。

## 3. 请求硬顶治理变更（D1）
- 决定：`p2_contracts.HARD_MAX_REQUESTS` 与 `live_authorization.MAX_GO_REQUESTS` **同值 1000→1600**；保持既有相等不变式与 P1 行为（P1 已签 GO 的 `max_requests` 仍各自生效，不构成对 P1 的追加授权）。
- 依据（实算）：已用 547 + T207 公开 263 + H2 回合 144 + H2 灌库 ≤20 + T208 judge ≤160（3 元/0.018688）+ T900 independent ≤107（2 元/0.018688）= 1,241；+20% ≈1,489 → 取整 **1600**。
- 授权来源：主人 2026-11-10 预授权「必要时应实算提至 ≤2000」「GO 在 P2≤50 元、累计请求≤2000 内由经理拟定」；本变更不触预算、不改门槛。**到值即停**：累计 reservation 到 1600 时任何发送前拒绝；各计划自身 max_requests 是更早闸门。
- 落盘：本条即经理记录；实现与契约文本由 T207-FIX-B 执行，独立验收核对「无其他放宽」。

## 4. 修复与派发决定
- 并行派发（写域不相交）：**T207-FIX-B**（pilot 返工②③⑤ + 输出有效性结算修复 + 请求硬顶治理）与 **T207-FIX-P**（公开财务反例 4 项最小修复，产品规则路径）。
- T207-FIX-B 独立验收通过后，派 **T207-FIX-A**（矩阵工具：ingest-plan/版本槽、H2 规划器、N8/C6 只读转换器与 run case 文件、run 产物→评分/聚合驱动、计划/GO/runbook 重建）。
- 每包：全新开发上下文 → 全新独立验收 → 经理接收并本地 commit（仅 P2 路径、不 push）。两轮不通过按任务书重审拆小。

## 5. 风险（记录）
- H2 真实评测是首次 H2 执行；若 <24/30 或硬失败>0，问题照实归因（不得读题改题/调参）。
- 产品反例修复触及规则路径核心（字段角色/实体判定/分档/有效期），回归风险高；以离线控制 + B0/N/C 本地对照为准，发现与冻结期望冲突先报告。
- OCR 文本长度仍为假设（每页 ≤2,700 字）；超限在发送前 `attempt_quota_exhausted` 停，不超支但已付页费。
- 多 run 观测矩阵不得被表述为 release/达标；T209 负责 baseline 与阈值。

## 6. 文件
- 本记录：`docs/reports/OBS-EVAL/P2/T207/PM/T207-PM-decisions-01.md`
- 准备交付：`docs/reports/OBS-EVAL/P2/T207/**`