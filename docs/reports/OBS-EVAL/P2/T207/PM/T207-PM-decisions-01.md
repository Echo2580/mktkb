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

## 11. 正式执行阶段追加决定（2026-11-11 11:2x–12:2x）
- **H2 首跑 fail-closed 两处**：①`--holdout-manifest` 必须用封存 root 内 manifest（repo 副本仅用于计划生成交叉校验）；②live 门曾无条件要求 ocr（已由 FIX-LIVEGATE 按「计划能力」修正，四项核心操作仍强制）。两次均 0 发送、账本未变。
- **评分口径缺陷定性**：Q09–Q24 仅因 `value_no_fabricated` 失败且数字全部来自引用证据；`gate.py` 明确该检查是诊断字段（T004b）。定性为 P2 评分口径缺陷（非产品缺陷），由 FIX-SCORE 以「金标 ∪ 引用证据」opt-in 修复；R1 重评分 b0 38/40、exact 24/24。
- **产品缺口定性**：N08（图片类问题应 not_found）、C05/C06（冲突披露）为真实产品行为缺口；根因含「live 计划每轮仅 1 次 query_embedding/rerank，而记录型问题做两路召回，第 2 次被配额拒后异常被吞 → document 面候选被裁」。由 FIX-CONFLICT 以产品最小修复（图片意图识别 + 同实体冲突复核只读 SQL）闭环；独立验收 7/7 PASS。
- **MEDIUM-2 口径（冲突披露与候选窗口）**：冲突路径可读候选窗口外**同实体可见正文**（只披露冲突值、不再产出作答值），这是为覆盖「通知类文档被候选窗口裁掉」而做的产品级局部放宽；硬门禁 citation_required 只对 kind=answer，不判 conflict。**经理决定**：T207 接收该行为并在报告/观测矩阵明示；H2/T209 阈值与发布口径由后续审核方复核；若 R4 真实执行出现 gate 侧异常则停并回归。
- **MEDIUM-1（图片拦截过宽）**：组织架构图/流程图/通知图片类提问不得误拒；已派 FIX-CONFLICT-R1 收窄并补反例。
- **R4 定点重测范围**：N08/C05/C06 三例（受影响范围），新计划+新 GO、无 OCR 项；不重跑全量 B0（FIX-CONFLICT 54 例差分仅 N08 变化、FIX-SCORE 仅评分层）。最终 baseline 的完整同版本数据留 T209。
- **H2 聚合缺口**：runner 原只写计数聚合；FIX-H2SCORE 在受限进程内算质量聚合（只写聚合），其首轮验收发现「逐题行缺 product.text → 答案题结构性 0 pass」，已派 R1 修复。

## 12. R4/H2 执行前追加决定（2026-11-11 13:4x–14:2x）
- **F-1 向量层静默降级（新 BLOCKER，已闭环）**：`product_adapter._start_live` 曾把产品 per-request 上限设为计划峰值；page_count=0 计划峰值为 chat 0.018688，而 embedding 单次 POST 预留 0.04096、rerank 0.024 → provider 发送前拒绝、灌库静默降级 `embedding_error`，会产出「看似通过、向量层全灭」的证据（R1–R3 因含 12 页 OCR 峰值 0.5 未触发）。FIX-LIVECAP（commit `1dca413`，独立验收接收）改为 effective=max(计划峰值, 各 provider 单次预留) 且必须 ≤ GO `max_request_cny`，不足则在装配期 `live_request_ceiling_insufficient` fail-closed（不发送/不预留/不降级）；含 OCR 公开计划行为逐值不变。**R4/H2 执行前置：GO max_request_cny ≥ 0.04096（候选 0.5 满足）**。
- **F-3 裁定（文案-only 改动不需重签计划）**：产品输出文本修复不改变计划内容，`plan_sha` 是计划内容哈希 → R4 沿用原计划（`00b9fdef…`）与候选 GO 绑定，不重签计划；GO 仍按流程签发（绑定 plan_sha）。已写入 runbook §9 与 T207 report §9.5。
- **R4PREP 独立验收**：计划/case/ingest/GO 候选逐值 PASS；因 F-1 判不可签，F-1 由 LIVECAP 闭环、F-2/F-3/F-4/F-6 由 R4PREP-R1 文档收口（只动 T207 文档；plan/case/ingest/GO 不改）。
- **R2（commit `24f9cde`）**：冲突回答 text 披露双方取值（通用渲染、≤8 条/字段），C05/C06 冻结评分 fail→pass；54 例仅 C05/C06 变化；独立验收接收。
- **H2 执行前置补充**：固定路径当前为 H2 GO（sha `3ed427f4…`）；R4 需先归档该 GO、签 R4 GO；H2 前再恢复/重签 H2 GO。

## 13. H2 首次真实 run 中止与诊断（2026-11-11 14:5x–15:0x）
- **执行**：H2 GO `3ed427f4…`（plan `f5877f56…`、1100）；run_id `p2-t207-h2-20261111-01`；`--visibility holdout --mode live`，purge 接线修复后成功启动。
- **结果**：**aborted**，`stop_code=product_service_error`，`error_code=MODEL_OUTPUT_INVALID`（HTTP 200，stage=product_answer，turn 1）；已发送 21 chat、63 出站、70 笔预留，结算 0.1825 元（保守 0.1862082），账本 +140 行；累计请求 774。
- **执行面读数**（holdout_scorecard，仅聚合）：total 30 / executed 21 / passed **11** / failed 10 / errors 9（中止后未执行）；分层 paraphrase 8/10、multi_turn 2/5、negative **1/5**、stale_conflict 0/5（4 未执行+1 fail）、cross_doc 0/5（全未执行）。**即使剩余 9 题全过也仅 20/30，低于 24 标准**。
- **另见聚合 block**：`holdout_document_code_unmapped`（mapped 8，missing [`V04`,`V06`]）——H2 labels 期望来源用版本文件名代号（V04/V06），而产品回传 document_name 为基槽名（D01/D02），来源匹配需版本代号→基槽映射（否则 stale_conflict/cross_doc 结构性失败）。
- **MODEL_OUTPUT_INVALID 语义**：模型 HTTP 200 但输出不合 JSON/schema，当前 runner 归为 product_service_error 并整 run 停止；H2 需 30/30 无 error 才能过（errors 会形成 unknown block），单次输出异常即中止使 H2 几乎不可完整；需产品健壮性修复或停止语义裁定（待诊断后决定）。
- **经理处理**：已复制中止产物至 `T207/p2-t207-h2-20261111-01-aborted/`（聚合安全、无逐题）；派受控元数据核对（labels expected_sources 的 doc_code 集合/locator 键集，仅聚合）+ 聚合诊断扩展（expected_kind×actual_kind、失败 check 计数、映射状态；无题干/答案）。诊断后决定产品/评分修复与是否再跑一轮 H2（新计划+新 GO，计入同 20 元/同请求）。

## 14. 主人选择 A：T207 报告收口后暂停（2026-11-11）

- **最新授权**：主人明确选择“不再付费，完成报告与独立复核，如实保留 H2 未达标结论，收口后暂停”；不进入 T208/T209/T900。
  当前宿主没有 wb 子代理工具与 Codex Host CLI，主人另明确允许用内置子代理完成零真实调用独立验收；不再执行旧模型入口要求。
  当前宿主权限以实际 workspace-write 为准，不沿用交接中 danger-full-access 的环境快照。
- **固定文件核对**：账本/预算/GO 分别为 `1648405845fd5e19…` / `79b21700…` / `3ed427f4…`，与暂停交接一致。
  ledger 774 reserved/result；P2 **保守占用** 6.784628 元、项目保守占用 21.8555725 元；本轮新增真实调用/预留均 0。
  原记录把全操作保守占用简称“结算”的地方以此收紧，供应商实账未在本轮核对。
- **矩阵取证政策（预定范围，不择优）**：R1-fixed 取 B0 40/N01–N07/C01–C04；R4 取 N08/C05/C06；R2-fixed 仅取 U01；
  U02–U10 取已有 `scoring/u-controls.json`。按该固定范围过滤后调用既有矩阵工具，无重复 case、保留 Q25/Q33 失败。
  `update_delete` 真运行行覆盖 1/10，`u` 才是 R1+L9 的 10/10 证据表；不把本地控制当真实模型完整更新验证。
  生成 `scoring/closeout/{matrix_observation,verification}.json`，输入文件 hash、原运行身份/配置/索引与复评分比对同存。
- **H2计数更正**：scorecard executed=21（11 pass/10 fail），errors=9；计数聚合 cases.executed=22、with_error=1，故 1 题出错+8 题未开始。
  不是 9 题全未尝试；现有评分把 9 项全补通过也只有 20/30，但有 V04/V06 映射缺口，不能用该读数预测修复后能力。
  `hard_failures=0` 不证明真实硬失败全零；冻结停止语义保持不变、不重跑、不修 FIX-H2MAP。
- **独立验收安排**：H2DIAG 由全新内置上下文验收；若不通过，保存拒收证据并只撤回其源码/测试/契约增量，不发新修复包。
  组合矩阵与最终报告由另一全新内置上下文复核，允许“有质量缺口的报告收口”接收，不允许认证质量达标或 P2 总完成。
- **本轮 U 验证限制**：旧导出 U01–U10 为 10/10；本轮复跑默认 TEMP 权限失败，换可写 TEMP 后在 B0 构建阶段无进展并中止。
  不把中止复跑称通过，不改断言/预算；本轮使用旧控制的来源/时点明确保留。
- **交付与停止**：最终报告 `../T207-final-report.md`、全新复核 `../review-closeout.md`；
  经理确认接收后只暂存 P2 路径并本地 commit；协调文档/面试材料/原有临时文件不入库；不 push/合并/部署。
- **最终经理接收**：H2DIAG 独立拒收后已按计划撤回，源码/测试/两契约 diff 为空；拒收 patch/hash/反例完整保留。
  另一全新内置独立复核完成 223 条同步证据断言、退出 0、网络尝试 0，结论为“限定接收 T207 如实收口，收口范围阻断 0”。
  经理接收该报告范围，不接收 H2 质量/安全通过，不宣称 P2 总完成；回退后经理同步子集16 passed/5 deselected，未执行项不计通过。
  H2 原元数据三文件含封存题号，已仓外逐字节保全并核hash，仓内仅保留三安全聚合；索引为 `../scoring/closeout/h2-artifact-audit.json`。
  后续本地提交仅限 T207 收口与 H2DIAG 拒收证据两目录；提交后更新暂停交接，不再派发下一任务。
