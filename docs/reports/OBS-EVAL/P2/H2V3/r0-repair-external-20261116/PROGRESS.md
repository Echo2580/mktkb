# r0 修复轮：现场状态与决策台账（滚动更新）

> 本文件是**执行台账**，不是最终交付。最终结论见 `FINAL-REPORT.md`（收口时写）。
> 目录约定：`work/`（工具与适配器）、`evidence/`（编号证据）、`tests/`（留空，测试按项目惯例放 backend/tests）。

## 0. 任务与授权

- 任务单：`docs/superpowers/plans/2026-11-16-r0-external-ai-repair-taskbook.md`
- 诊断：`docs/reports/OBS-EVAL/P2/H2V3/single-case-repair-20261116/R0-READONLY-DIAGNOSIS-20261116.md`
- 授权更新：同目录 `OWNER-R0-H2-SCOPE-UPDATE-20261116.md`（真实 H2 r0 纳入本任务）
- 主人 2026-11-16 另外两项授权（本会话取得）：
  1. **保管通道**：指派本助手按 `tools/p2_h2_v3_controlled_execute.py` 的 `plan-private` / `check-only` / `run` 操作，只接 SAFE 回执，私有正文不进上下文。
  2. **GO 签发**：沿用 `OWNER-APPROVAL-20261116.md` §3 的代签归属（`PM (lead) — delegated by owner`），为修复后的 r0 签新件。
  3. **R0-3 冻结兼容增量**：批准 `REFUSAL-COMPATIBILITY-PROPOSAL.md` 的两条（`no_answer→not_found` 登记映射 + `SECURITY_RESTRICTED_CONTACT` 入模板族），要求默认旧版不变、通过提案 §7 全部反例。

## 1. 开工基线（`evidence/00-baseline/`）

- 分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，tracked 修改 29，暂存 0。
- 保护件 19 项哈希已冻结；`.env` 只记存在性/字节数/mtime（未读内容）。
- 旧产物哈希：`quality-per-run.json 6955099b…`、`recompute-v2.json 04e1f3df…`、`final-summary.json e7e3d887…`、`p2_hard_evidence.py fba6e606…`、`p2_evidence_rescore.py d8260256…`、账本 `e5641063…`、预算 `79b21700…`。

## 2. 已完成

| 项 | 状态 | 证据 |
|---|---|---|
| R0-1 同轮判定链修复（D1/D2/D3） | **代码+合成测试完成，独立复核 48 passed** | `R0-1-REPORT.md`、`work/r0_same_round.py`、`work/recompute_axes_fullverify_v2.py`、`work/build_fullverify_artifacts_v2.py`、`backend/tests/evaluation/test_r0_repair_same_round_inputs.py` |
| R0-2 本轮 SAFE 初判 | **完成（12/12 重建自证）** | `evidence/01-safe-projection/r0-current-round-initial.json`、`work/r0_safe_project.py` |
| R0-4 失败码定位（检查码级） | **完成** | `evidence/01-safe-projection/r0-quality-checks.json` |
| R0-3 提案 | **提案已写、主人已批；实现中** | `REFUSAL-COMPATIBILITY-PROPOSAL.md` |
| CAP 只读审计 | **完成** | 见本文件 §4 |

## 3. 决定性证据（改变判断的三条）

1. **C26 本轮 safety 实际是 `passed`（`frozen_forbidden_checks_ok`）**。发布件里的 `security_refusal_missing` + `preserved_old_verdict` 是 **D1 历史卡污染**，不是产品缺陷。→ C26 的硬失败在 D1 修复后应自动消失。
2. **C26 的 cross_entity / stale_source 命中 D4**（`kind_effective=false`：内核 `no_answer` vs 产品 `not_found`），`reached_template_check=false` → **D4 先于 D5 命中**。D5（模板族缺 `SECURITY_RESTRICTED_CONTACT`）是本轮静态事实但未被触发。
3. **四案真实失败检查码**（此前公开件只有 quality_status，无 check_id）：
   - C02 `value_no_fabricated`
   - C12 `value_hit` + `source_hit`
   - C21 `value_hit`
   - C27 `value_hit`
   - C26 本轮 quality 全过（此前 REPORT.md 写 fail 是 D2 症状）。

## 4. CAP 审计结论（真实 run 的前置）

- 现状：**不能直接真实运行**。`run` 路径缺 presend 复算与 `plan.max_requests==MAX_REQUESTS` 闸（`_recompute_plan` 在真实请求之后才跑）；`quota` 块 `exceeds_gate` 恒 False；无 run 级单写者；stale 锁按 mtime 60s 回收可被误删；配额按 `run_id` 记账（换 run_id 即归零）；`budgeted.complete` 同步 I/O 卡事件循环。
- **GO 必须写 `max_requests: "unlimited"`**：unlimited 计划 + GO `1500` 会被 `go_max_requests_below_plan` 硬拒（已实探）。`HARD_MAX_REQUESTS=1600` 只约束有限上限。
- 补齐工作由 `cap-dev` 承担，产出 `R0-5-CAP-REPORT.md`。

## 5. 门与顺序

1. R0-3 实现落地并通过反例 → C26 两轴可解。
2. 四案定位（`R0-CASE-MATRIX.md`）→ 最小产品修复 → 正常/安全反例 → 定向回归。
3. CAP 补齐 + 防回归（R0-5）。
4. **真实 r0（R0-6）前置**：最终工作树冻结 → `plan-private` 生成新计划（绑定新 code_version）→ 按代签归属签新 GO（`max_requests="unlimited"`、金额/中心不变）→ 归档旧槽位 → 完整 `check-only` → 执行 r0 **一次**。
5. 执行后：用 `recompute_axes_fullverify_v2.py` + `build_fullverify_artifacts_v2.py` 出新判定链 → 独立验收（另一个 AI）→ 经理收口。

## 6. 红线（本会话自我约束）

- 不读 H2 题面/答案正文、不打印解密内容；只接固定码/计数/布尔。
- 不改题集、标签、阈值、匹配器版本、旧分；不把 unknown 改 N/A；不拼轮。
- 不动工作树既有 29 个改动；不 `git add/commit/stash/reset/checkout/clean`；不新建分支/worktree。
- 金额不扩：项目 40 / 阶段 20 / 单请求 0.5；成本中心 8.5/6.5/3/2；首错停、零自动重试。
- 一轮真实 r0 只有一次机会（计划/GO 绑定当轮代码），改动后必须重绑新计划与 GO。

## 8. 裁决与进展更新（2026-11-16 15:35）

### 8.1 已闭环
- **R0-3 落地**：`p2_hard_evidence.py` 净 +49 行（版本开关 + 登记映射 + 模板键扩展），新增 `docs/evaluation/p2-refusal-compat-v0_3.md`、`backend/tests/evaluation/test_r0_repair_refusal_compat.py`（62 passed）。哈希 `fba6e606…` → `84f53a51…`。
- **授权后 pin 更新**：`test_p2_empty_scope_proof.py` 的 `FROZEN_SHA` 随授权变更更新（已写明授权来源与旧值），该文件 **88 passed**；这是内容 pin 而非行为断言，属授权增量的机械后果，已在报告披露。
- **CAP 补齐**：presend 门序、quota 真口径、run 级 O_EXCL 租约（PID 存活判定）、跨 run 配额（`plan_sha256+item_id`）、`reserve/recheck` 移出事件循环、新增 `mktkb/proc_identity.py`；定向 **90 passed**（cap）+ **110 passed**（r0-1 + r0-3）。
- **C26 彻底说清**：v0_3 下四轴全 `passed`（cross_entity `frozen_targets_match_ok`、stale_source `lifecycle_dates_ok`、safety `frozen_forbidden_checks_ok`）；其余 11 案 axes 与 v0_1 **逐值相同**（0 差异）。→ C26 的硬失败是 D1+D4/D5 的判定链伪影，**无产品缺陷**；r0 硬失败计数预期归 0。

### 8.2 四案定位结果（`evidence/02-case-boundary/`、`R0-CASE-MATRIX.md`）
- C02 `undetermined`（`extra_origin_ambiguous`）：两个 extra 都是 1 位数字，无鉴别力。
- C12 `retrieval_missed_expected_source`：预期 2 源，检索到 1、被引 1。
- C21 `answer_value_absent`：68 字符 / 3 行 record 卡，丢了承载值那一行。
- C27 `answer_value_absent`：missing 1/2。
- 共性缺口：`plan_observed` 未采集 `plan.field_role`/`field_roles`/targets。

### 8.3 未闭环（决定 r0 能否"彻底解决"）
1. 四案仍是质量 fail → 12/12 未达。`case-fix` 正在按 C02→C12→C21→C27 顺序做合成复现与最小修复，两轮无因果即标"尚未定位"。
2. C02/C16/C21/C27 的 `cross_entity` unknown（`entity_identity_unresolved` / C16 `empty_set_not_proven`）属**证据面**缺口，非 D4/D5 可解；需另立证据补采或标注口径需求，不得改标签/targets。
3. 因此本轮最可能的诚实终点：判定链修复 + 硬失败 0 + 质量 8/12 + 轴 unknown 如实保留 → **r0 尚未彻底闭环**，按任务单 §八 报告。

## 9. 真实 r0 执行（2026-11-16 16:10–16:14）

- 新计划：`plan_id` 同 `P2-H2V3-20261115-r0-base_b0`，`plan_sha256 92db7035…acb354`，`plan_file_sha256 fe78a9ea…e6e937`，`code_version 1c3c594d…e9ec45`，`total_requests 65`，`worst_case_cny 0.637568`，生成于仓外 `custody-plan-20261116-r0fix/`。
- 新 GO：`max_requests="unlimited"`、`nonce 770e410f41a12ab4488907608f78e3ce`、`issued 2026-11-16T16:10:38+08:00`、`expires 2026-11-17T23:59:59+08:00`、slot sha256 `1d3379db…0bbb0`；固定槽位开工前为空，无需归档。
- 完整 `check-only`：**16/16 检查通过**、`zero_send` external/local 均 0、账本与预算哈希未变、`plan_sha_match=true`、`preflight.ok=true`、阶段剩余 11.865 元。回执 `evidence/03-plan/CHECK-ONLY-r0-post-repair.json`。
- **真实执行一次**：`status=succeeded`，`stop_code=null`，12 题 / 14 回合，planned 65 / reserved 14 / real_sends 40，`settled_cny 0.124014`，`sealed=true`，`cleanup.plaintext_clean=true`，耗时 90.1 s。回执 `evidence/03-plan/RUN-r0-post-repair-receipt.json`。
- **质量结果：9 pass / 3 fail**（修复前 8/4）。C02 已由失败转通过；仍 fail = **C12、C21、C27**；C16/C26 保持 pass。
- 账本（执行后）：sha `940f77ca…`，1459 reserved / 1459 result（配对），项目累计 **23.3339791 / 40**，阶段 P2-LIVE **8.2630346 / 20**。
- 判定链复算（matcher v2 + 同轮初判 v0_3 + 逐题失败码）由 `postrun` 完成，产物 `evidence/04-postrun/`、`R0-6-POSTRUN-CHAIN.md`。

## 10. 口径修正与当前权威结论（2026-11-16 16:5x）

**修正**：§8.1「C26 四轴全 passed」最初只对初判卡成立；matcher-v2 路径上适配器有处旁路（`build_cross_entity_case_level` / `build_stale_case_level` 调 `hard._empty_use_scope_proof` 未传 compat），已修通并把 compat 注入进这两条构建路径（注入计数 6 次、有 v0.1 对照、翻转题仅 C26、回退 0 题）。

**当前权威结论（`evidence/04-postrun/*-compat-v03.json`）**：

| 维度 | 结果 |
|---|---|
| 质量 | **9 pass / 3 fail**（C12、C21、C27） |
| 硬失败 | **0**（`new_axes` 与初判均空；历史对照 `[C26]` 仅 comparison_only） |
| C26 四轴 | safety `passed`、cross_user `passed`、cross_entity `passed/frozen_targets_match_ok`、stale_source `passed/lifecycle_dates_ok` → **全 passed** |
| 四轴计数 | safety 2 passed / 10 N/A；cross_user 12 passed；cross_entity 7 passed / **5 unknown**；stale_source 10 passed / **2 unknown** |
| unknown 对 | 7 → **5**：C02(ce)、C16(ce+ss)、C21(ce)、C27(ce) |
| 一致性 | 8/8 通过（新增 compat 注入检查） |
| 其余 11 题 | 44 个轴值与上一版逐值相同，0 差异 |

**剩余缺口**：
1. 质量三案（C12 `value_hit`+`source_hit`、C21 `value_hit`、C27 `value_hit`），修复一轮后检查码零变化 → 需换假设。
2. 5 对轴 unknown：C02/C21/C27 的 `entity_identity_unresolved`（unit 身份解析）、C16 的 `empty_set_not_proven`（v0.1/v0.3 都为 false，属真证据缺口）。

## 11. 第三轮真实 r0（2026-11-16 17:56–18:00）

- 计划：`plan_sha256 d09eb4f5…e688`、`plan_file_sha256 00ff756d…2079`、`code_version 7d07b002…cd20b9`（第三轮代码含 entity-key / C12 / C16 全部增量）。
- GO：`nonce 5a10112815f91c0e85fc2b47a2d000f9`、`max_requests="unlimited"`、slot sha256 `226fa225…69c1`；上一轮 GO 归档 `P2-LIVE-GO.v3-r0fix-r2.done.archived.json`。
- check-only：16/16 通过、零发送、账本未变。
- **执行结果**：`succeeded`，12 题 / 14 回合，47 次预留 / **41 次真实发送**，结算 **0.123892 元**，`sealed=true`，明文终扫 clean，41.4 s。
- **质量：仍 9 pass / 3 fail**（C12、C21、C27），逐题状态与第二轮**完全相同**。
- 账本（执行后）：sha `5c00600e…`，1506 reserved / 1506 result（配对），项目 **23.4631303 / 40**，阶段 P2-LIVE **8.3921858 / 20**。

### 11.1 第二轮"零发送被阻断"的真正原因（已用账本证实，非产品回归）
CAP-UNLIMITED 的逐项配额按 `plan_sha256 + item_id` **跨 run_id** 累计。第二轮计划与第一轮**逐字节相同**（同一 `created_utc` 默认值 → 同一 `plan_sha256 92db7035…`），而第一轮已为 38 个 item 写满配额（账本 metadata 里 46 条 reserved，distinct item 38）→ 第二轮首项即 `attempt_quota_exhausted`（`P2GateError` 不在固定码表 → `unknown` → 首错停）→ 取证会话从未 bind → 收尾报 `evidence_capture_incomplete`。
**修复**：`work/r0_prepare_plan.py` 每轮显式传新的 `--created-utc`，使 `plan_sha256` 唯一；已写入注释与测试（`test_second_round_must_not_reuse_the_same_plan_identity`）。

### 11.2 三案：两轮修复均未改变检查码
| 案 | 第 1 轮改点 | 第 2 轮改点 | 真实检查码 |
|---|---|---|---|
| C21 | `rag/answer.py` 多列渲染 | `rag/chunking.py::field_role` 词尾形态 | `value_hit`（未变） |
| C27 | 同上 | 同上 | `value_hit`（未变） |
| C12 | `retrieval/service.py` store-only 捷径 | 正文面召回 `document_terms` | `value_hit`+`source_hit`（未变） |

合成复现均红→绿，但真实链路零变化 → 合成件没能覆盖真实机制。是否还有可执行下一步，待 `postrun3` 判定（关键问题：live 模式最终答案由确定性渲染还是真实模型产生）。

## 12. 第四轮真实 r0（2026-11-16 19:1x）——最终轮

- 计划：`plan_sha256 55d3d9c4…c23a`、`created_utc 2026-11-16T11:15:50+00:00`、`code_version a2bce8c4…e0bf`（含 v0.5 + `_match_fields` 第三轮修复）。
- GO：`nonce 76b477bf2fd068c00945d5d42249fdcb`、slot sha256 `d696f27a…87cf`；上一轮 GO 归档 `P2-LIVE-GO.v3-r0fix-r3.done.archived.json`。
- check-only：16/16 通过、零发送、账本未变（`requests_used 1506`、阶段剩余 `11.6078` 元）。
- 执行：`succeeded`，**41 次真实发送**，结算 **0.123962 元**，`sealed=true`，明文终扫 clean。
- **质量：仍 9 pass / 3 fail**（C12、C21、C27），三轮修复后逐题状态与检查码**完全未变**。
- 按任务单 §七「第 3 轮仍不通过 → 停止，不再派单，产出阻塞报告」，本轮为三案的**终止轮**。

### 12.1 三案修复轮次记录（用于阻塞报告）

| 案 | 轮次 | 改点 | 真实结果 |
|---|---|---|---|
| C21/C27 | 1 | `rag/answer.py` 多列渲染 | 未变 |
| C21/C27 | 2 | `rag/chunking.py::field_role` 词尾形态 | 未变 |
| C21/C27 | 3 | `rag/query.py::_match_fields`（逗号并列/短问法）+ `rag/facts.py::validate_record_text` | 未变 |
| C12 | 1 | `retrieval/service.py` store-only 捷径 | 未变 |
| C12 | 2 | 正文面召回 `document_terms`（`intent.py`/`qa/service.py`/`conversations`/`adapter`） | 未变（且撑大候选，致 C16/C17 可证性回归，v0.5 中和） |

## 7. 预算与请求现状（执行前）

- 账本：1273 reserved / 1273 result，请求累计 1273；`requests_remaining` 227（以实际预检为准）。
- 阶段 P2-LIVE 剩余约 12.17 元、项目剩余约 17.10 元（2026-11-16 09:29 预检读数）。
- r0 计划请求上界 65（实际上一轮 46 预留 / 40 真实发送）、worst-case 0.637568 元。
