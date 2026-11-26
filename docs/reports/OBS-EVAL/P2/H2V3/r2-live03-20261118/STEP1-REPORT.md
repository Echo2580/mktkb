# T-R2-LIVE-03 步骤1 前置验证包（合成数据，开发+独立验收）

日期：2026-11-18。范围：仅合成数据与公开材料；未读任何真实题面/答案/私有密文/key/.env，未触碰 var/、账本写入、GO、旧封存。零真实请求、零外发。

## 1. 开工基线

- 分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，39 个已跟踪修改、0 暂存、353 未跟踪（含 P2 源码新文件）。
- 39 个已跟踪脏文件字节哈希清单摘要 `765b6e76bb234cdf74576acf4c4b9d1c1f82086d967a3823683ea5f7a6ad695e`；收工复算**逐字节一致**（未越界改跟踪文件）。
- 受查源码 `p2_evidence_capture.py` 为**未跟踪新文件**，不在 39 件清单内；其改前字节按精确差异重建（见 §3）。

## 2. 复现（未改代码，先红）

正常生产路径（ProductEvalAdapter 正式问答入口 → capture_scope → finish_turn → EvidenceWriter.write_turn → manifest/receipt → 磁盘回读 → SAFE 认证入口）实测：

- 磁盘密文 `capture.status='active'`（sink 从未 seal；`CaptureSink.seal()` 此前只被测试 fixture 调用）。
- manifest 逐回合 `capture_status='active'`。
- SAFE `project_authenticated_turn` 判 `sink_unsealed`。
- 根因：写盘快照取的是未收尾 sink；写后回执只存在于内存对象，磁盘 envelope 按契约不含 sealed 键。既往认证测试由 fixture 预设 `status='sealed'`，掩盖了生产路径缺口。

## 3. 最小修复（3 行）

`backend/src/mktkb/evaluation/p2_evidence_capture.py` `EvidenceCaptureSession.finish_turn` 在 `build_turn_evidence` 前调用既有 `turn.sink.seal()`（active→sealed；failed 保持不变）。复用真实 sink 收尾，不改 SAFE 工具、不改写前/写后阶段契约、不改评分/分类/阈值。

- 改前 SHA-256（重建）：`601096bc3b37180e77332d53d15647cc4998c33e44bef4c56cf411509f26e2fb`
- 改后 SHA-256：`f2b2398b24b61b044b508c2473f8271b70fcf68d53010af9c10571e8f176eb9d`
- 差异见 `step1-minimal-fix.patch`。
- 保护件未动：`observability/evaluation_capture.py` = `24a66783…`（与 PROTECTION.md 一致）；SAFE 工具 `safe_plan_projection.py` = `486fae88…`（一致）；`p2_evidence_io.py` = `1c16a3da…`（未改）。

## 4. 验证计数与退出码

| 项 | 结果 |
|---|---|
| 参考节点基线（e2e readback + F1-A HTTP join） | 2 passed，exit 0 |
| 开发合成测试 `test_r2_live03_production_seal_safe.py`（修复前） | 红：`active≠sealed`、`manifest_capture_status_not_sealed`（复现成立） |
| 开发合成测试（修复后） | 5 passed，exit 0 |
| 独立验收 `test_r2_live03_independent_acceptance.py`（全新合成资料：丙/丁店、升降台/周转筐/平板车、哨兵 INDEP_R2LIVE03_CANARY_7e21d9） | 5 passed，exit 0；文件 SHA `83e0d427ed3c1de92f703be7dc3e2228cff080597f251e43fe86cebbf7b168ab` |
| 主窗口复跑两文件 | 10 passed，exit 0 |
| 定向回归（e2e 全文件/F1 全文件/capture/io/contract_v02 + 新测试） | 52 passed + 1 既有失败，exit 1 |
| 零外发正对照 `test_p2_v3_wiring.py::test_zz_outbound_positive_control` | 1 passed：DNS/直连/urllib/httpx 4 类探针全拦，external=4、local=0 |

既有失败（与本次无关，同环境 A/B 证实：移除修复行后同样失败）：
`test_p2_capture_contract_v02.py::test_gap_rework_identity_unparsable_pagination_and_candidate_marker`（`candidate_observation.availability` observed≠not_observed）。未修、未扩范围，如实保留。

## 5. 守卫记录

- 全部合成测试挂 `t09_network_guard`（teardown 断言 external=0）；各 adapter `network_stats().outbound_attempts=0`；`MockChatBackend.call_count=0`；只用临时合成 Fernet key 与 pytest 临时仓外目录。
- 正对照计数 4（见上）；正常阶段外发尝试数 0。
- 输入身份：合成 run_id 前缀 `r2live03-*` / `r2live03-indep-*`；输出身份：SAFE 固定码/布尔/计数，脱敏闭包断言哨兵/题面/实体原文不在 SAFE 输出与 manifest 公开摘要。

## 6. SAFE 实测字段与缺项（逐项）

正例（C29 同形跨层枚举直答，4 回合）：磁盘 `capture.status='sealed'`、密文无 sealed 键；writer/manifest 回执 sha256/bytes 与磁盘一致；SAFE `observed`，`join='joined'`，roles={location,status}，`effective_mode='record'`、`effective_enumerate=true`，candidate_count/truncated/page_has_more 均 observed。

同形变体（关 `_store_join_chunks`）：正文缺店家级值、来源数减少；SAFE `join='unknown'`（≠joined）且候选计数仍 observed → **联结未发生与联结后缺覆盖可区分**。replay 回合 → `incomplete`。

缺项列明：
1. `candidate_scope_limit` 恒 `'unknown'` —— SAFE 工具硬编码，非采集缺失；
2. 枚举轮 `stores_count` 实测 **0**（stores_status=observed，与 joined 并存）——口径待保管/评分侧核对，非 not_captured；
3. 变体联结码为 `unknown` 而非具体 fail-closed 码（裸二元组替换下的设计内行为）。

以上不导致联结后原因完全不可区分 → 按任务书 §3.2 放行，不补额外观测。无 not_captured 字段。

## 7. 负例（全部固定码拒绝）

坏密文/错 key/错 binding → `authentication_or_read_failed`；缺 binding → `binding_unavailable`；failed sink/捕获错误 → `sink_failed`；active → `sink_unsealed`；incomplete/replay/timeout/missing_kinds → `incomplete`；回执 sha 错配/缺失、manifest 状态异常 → 绑定核对可检出。采集开关 on/off 业务输出与引用一致（随机记录短码归一化后逐字相等）。

## 8. 只读预算核对（步骤2 前置，公开账本）

- 账本 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl`：SHA `ded89d915582eb5cd235be7ed0485667d8c20337e8d80a8b8ac856c5d0701bc4`，4001 行，2000/2000 reserved/result 全配对，无待结算预留。
- 项目 24.8148354/40，剩 15.1851646；P2-LIVE 9.7438909/20，剩 **10.2561091**。
- 中心：answer_retrieval 3.5938909/8.5（剩 4.9061091）；ocr 6.15/6.5（剩 0.35，但 r2 历史 153 笔预留 **0 笔 OCR**，本轮范围亦不含 OCR）；judge 0/3；independent 0/2。
- `provider_billed_cny=null` → 保守口径。配置读数与冻结口径一致（40/20/0.5、8.5/6.5/3/2、unlimited 仅取消全局次数）。
- r2 历史参考：attempt2 planned 37 / reserved 31 / real_sends 29 / settled 0.0433 元；新计划最坏费用须由 plan-private 生成时按逐项配额正式核算。
- GO 槽位现状：仍为 attempt2 GO（绑旧 plan_sha `2edf5d9a…`，expires 2026-11-18T20:26+08:00）——本轮不可复用，须由合法签发/安装方归档后装新 GO。

## 9. 停止点与缺项（步骤2 授权边界）

步骤1 放行条件满足，源码按任务书冻结（本包哈希为准）。步骤2 需要**获授权执行者在受控环境**提供：

1. 本轮已确认的保管/执行授权（指明角色、窗口、受控渠道）——当前公开记录中**不存在**（交接 #70：现行保管授权未获确认；本窗口未收到任何填写完成的授权件）；
2. `$R2CustodyInputRoot`（冻结语料根：manifest.json/annotations-v0_2.fernet/review-v0_2.fernet）与 `$R2ScenarioKeyFile` 经受控渠道交给获授权执行者；
3. 新计划生成后由签发方审核预算摘要并签发本轮新 GO。

本开发窗口不持有、不索取、不代读上述私有输入；不将任务书或模板解释为许可（交接 #70 教训）。步骤2–4 停在授权边界，等待主人指定获授权执行者/保管人并走受控渠道。