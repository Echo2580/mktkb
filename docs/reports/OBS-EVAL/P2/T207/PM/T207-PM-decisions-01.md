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

## 7. T207-FIX-P 验收与裁量（2026-11-11 09:3x）
- 独立验收 `8e7999d6-58a5-4ae1-a70d-9e8aaf463265` 判 **接收（阻断 0）**：真实缺陷成立（F02/F03/F04 修复前 service_error/MODEL_OUTPUT_INVALID → 修复后 answer/200；F01/F05 不变）；未弱化（编造值 1.88、未引用来源值 2.5 新旧皆拒；记录型 5 样本新旧输出逐字相同）；回归 210/7/13/4 passed，probe 出站 0。
- **裁量 1（4 个公开财务反例重定性）**：独立复核 5/5 成立——F01-F05 意图全为 mode=document（记录型分支不执行）；「缺 90%/2.99」来自 Mock 适配器首条证据前 3 字段渲染（product_adapter.py:531/545）；F02 金标数字 {2026,10,28,8000} 使 E-2 仍 fail；F04 标签自相矛盾（expected_kind=not_found + should_refuse=False）。**结论：不是产品规则路径缺陷**；除已修真实缺陷外不做产品改写（避免绕过模型陈述→产品校验不变式）；T205 评测控制继续有效（4 诱饵 fail/2 正向 pass）。F04 标签矛盾与 E-2 正向控制需求记录为 T209/T205 文档清理项，非阻断。
- **裁量 2（唯一放宽）**：问题前提值可出现在答案值位置（旧口径拒、新口径收）。判定为合理且必要，但须钉边界并转 T209 知悉。已派 **T207-FIX-P-R1**（只加显式边界单测 + 报告补充，不改产品语义）。
- 瑕疵：report 写新单测 82 行、实测 89 行（sha 一致，笔误），不阻断。
- 经理接收：本地 commit `ffc9fe5`（12 文件，未 push；仅 service.py + 新单测 + FIX-P 报告/证据/review）。
- **T207-FIX-P-R1（边界单测）**：独立验收 `9aec8bfc-…` **接收（阻断 0）**；8 passed；旧口径下 (a)/(d) 在旧代码 TypeError/REJECT、新口径 ACCEPT，(b) 1.88 REJECT，(c) 记录型三样本逐字相同；报告数字（89/195 行、sha16）实测一致。经理接收 commit `405491c`（8 文件，未 push）。
- P-R1 验收备注：①(c) 的 3 样本中仅样本1 逐字取自既有测试；②所谓“值位置”实为 token 全局匹配（(a)/(d) 同路径）；③report 末行出处措辞小误；④**全角数字（８０００）在新旧口径都放行**（`_VALUE_TOKEN` 只认 ASCII，属既有口子，非本包引入）→ 列入 T209 阈值/校验收口清单。均非阻断。
- 清洁项：工作区出现未跟踪 `undefined/`（多代理临时目录解析产物，含 edit*.py 等）；A 包运行中暂不删除，A 收口后确认无引用即清理，禁止入 commit。

## 8. T207-FIX-B-R1 验收与接收（2026-11-11 10:0x）
- 独立验收 `dd620b46-…` 判 **接收（阻断 0）**：C1 闭环（修复前 summary 0.000124 vs 账本 0.018812；修复后 0.018812=账本合计、rejected_rounds=1、settled_cny=0.018688、正常轮不变）；混合轮不双重计数（0.000384+0.018688=0.019072）；契约 §7.2 十项逐值一致；范围合规、三份固定 SHA 未变、无 skip/xfail。
- 经理接收：commit `b1bfa60`（14 文件，未 push）；`test_p2_live_wiring.py` 与并行包 FIX-A 同文件，本包 1 个 +63 块延后随 A 提交（已记录，不重复计）。
- 非阻断跟进（记入收口清单，不阻塞执行）：R1 except-Exception 假定门已写 result 的边界（正常 run_live_p2 不触发）；R2/R3 `_money_split` 关系句未含拒绝轮、report 的 venv 路径/HEAD 标注过时。

## 9. T207-FIX-A 验收中发现的问题（2026-11-11 10:1x，待 A-R1 闭环）
核心机制（计划/GO 重建、拆 run 242/15/6 与 263/8.145808、授权窗口 801/807/822、R3→R2→R1 反证、ingest 12/4/2、cases 52/2/1、wrapper、版本槽 e2e）已由独立验收通过；以下为需闭环项：
1. **FIX-S 集成**：A 的 `test_p2_score_run.py` 冻结「Q39 必 fail / b0 39」；FIX-S 修复后 Q39 pass（实际 40），该测试红 → A 不能按“套件全绿”接收。A-R1 需把期望改 40，并同步 A report §6.1（Q39 缺口已被 FIX-S 修好，不再是待决项）。
2. **H2 候选 GO 与 runbook 命令 plan_id 不一致**：GO scope.plan_id=`P2-T207-H2-20261111`，runbook §8.1 命令 `--plan-id P2-H2-20261111` → 会 `go_plan_id_mismatch` 拒（fail-closed 但跑不通）。统一为一个值并同步文档。
3. **p2-score holdout 缺输入码**：文档承诺 `holdout_input_missing` 但代码不存在；既无 `--holdout-cases` 也无 `--verdicts` 时 TypeError。A-R1 补显式稳定码 + 测试（不改输出聚合口径）。
4. **旧 GO 拒绝原因文档写错**：实际为 `go_plan_id_mismatch`（非 `go_plan_sha256_mismatch`）；同步 runbook/report。
5. **文档数值**：cost §1 仍写硬顶 1000/余 453（应为 1600/653）；§6 写“公开矩阵 255/小计 1281”与 §3 的 263 矛盾；§5 H2 worst 6.368256 系 4 倍误算（36×0.044224=1.592064；计划实测 1.731328）。A-R1 全部更正并给复算。
6. 待补 **H2 灌库方案**（D01–D06+V01–V07、五条 stale_conflict 假设、批数 B）——并入 A-R1（零真实、离线状态验证）。
- 经理决定：A-R1 完成后重新独立验收（可复用同一验收线新上下文），通过后再接收 commit；FIX-S 验收独立推进。

## 10. T207-FIX-S 验收与接收（2026-11-11 10:2x）
- 独立验收 `07f387e8-…` 判 **接收（阻断 0）**：opt-in 默认行为与 HEAD 逐值一致（check_value 30,912 对 / _value_pattern 69 条 / score_case 230 个 CaseResult 均 0 分歧；Q39 默认仍 fail）；Q39 P2 路径 24 变体 0 判定错误（正确写法含空格/Tab/换行/全角 pass；错日期/错年份/错时间/缺时间/1 6:00/顺序颠倒/12026 全 fail）；P1 183 passed、gate+quality 109、exact 只覆盖 stratum=exact；范围合规、无 skip/xfail、零真实。
- 经理接收（未 commit，待 A 先提交）：**提交次序约束**——S 的新测试从 FIX-A 未跟踪的 `p2_public_cases.load_b0_cases` 导入，必须 A 先落盘再提交 S；否则干净检出会 collection error。
- 集成影响：A 的 `test_p2_score_run.py` 冻结 b0 39/1 现应改 40/0（已并入 A-R1）。
- 小瑕疵（收口清单）：S 报告 HEAD 标注 @405491c 已过时（现 b1bfa60）；§3「无空格命中」措辞需注明 case 仍 fail（value_no_fabricated）。