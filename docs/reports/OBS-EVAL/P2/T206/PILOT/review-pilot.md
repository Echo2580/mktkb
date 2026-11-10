# P2-T206 真实 pilot 独立复核（review）

- 角色：全新上下文独立复核助手。只读：未改账本/预算/GO/产物/代码，未 commit/push，未发起真实调用，未读 `.env`/H1/H2。
- 现场：`codex/p2-e2e` @ `5ce4b16`；run_id `p2-t206-pilot-20261111-01`。
- 复算脚本与机器结果：`evidence/verify/verify-pilot.py` → `verify-pilot-out.json` / `verify-pilot-out.txt`（无网络、不 import `mktkb`，自行重实现 canonical 摘要）。

## 结论

**建议接收 pilot（限"授权/账本/回执/额度"四面），并附 5 条返工单**；**不接收**"Q01 覆盖同槽 V1→V2"这一覆盖声明（事实不成立）。质量层不作结论（`gate.quality_gate=deferred-to-T205`、`gate_v0_3` 仍 unapproved）。

| # | 复核项 | 判定 |
|---|---|---|
| 1 | GO/预算签署面 | **PASS**（2 处元数据瑕疵，不阻断） |
| 2 | 账本增量 | **PASS** |
| 3 | 回执/产物一致性 | **PASS**（1 处口径需说明） |
| 4 | 停止/失败语义 | **PASS**（1 处口径冲突） |
| 5 | 成本/额度 | **PASS** |
| 6 | 质量观察 | **记录（不阻断）**，Q01 按冻结标签为失败 |
| 7 | 合规 | **PASS**（对本次复核范围） |

## 1 GO/预算签署面 — PASS

- `docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json`（raw `79a5f318…`，canonical `b0849326…`）：12 个必需字段齐全，非 DRAFT（`issued_by=PM (lead) — pre-authorized…`），nonce 32，有效期 **13.0 天**（≤14），`max_requests=566`（61≤566≤1000），`operations` 覆盖计划 6 类，`cost_centers 9/6/3/2=20` 覆盖计划，`stage_limits P2-LIVE=20`。
- `scope.plan_sha256=02725aa7…` 与 `p2-pilot-plan-v0_2.json` 的 **重算 canonical 摘要逐位一致**（raw 文件 sha 为 `daafa15f…`，两者用途不同，勿混）。
- 计划算式复算：26 项 / **61 请求** / worst **0.839072** / 峰值 0.5，且无单项超 `max_request_cny=0.5`（OCR 一页 0.5 **恰在界**，未越界）。
- 账本绑定 `f4710b18…` = **不可变历史前缀**（首条 `historical_import` 行）摘要，非整文件摘要；整文件 pilot 前摘要 `1f46d1b9…`/958,277 B/1011 行 记录在 `pilot-record.ledger_before`。设计使然，**非缺陷**。
- 预算 `budget.json`（`736b4d2b…`）：limit **40**、`P2-LIVE=20`、另 5.03+2+15.4+… 合计 **39.97**，`39.97+0.03=40.00` 闭合；历史 0.03、已发生占用 15.0709445 保留未清。
- 瑕疪（低）：① `remaining_conservative_cny_at_start=19.97` 是**改前口径**（20−0.03），未随 limit→40 更新（应为 24.9290555）；后端无读取点（`git grep` 仅 tool 写入），不影响门。② `stage_revision.revised_at=2026-11-11T01:45:00+08:00` 晚于文件自身 mtime `01:28:42`（=17:28:42Z），时间戳记载不可信（内容未被改，见 §7）。

## 2 账本增量 — PASS

- 亲自读 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl`：pilot 块位于**第 1012–1095 行连续 84 条**，全 `stage=P2-LIVE`，42 `reserved` + 42 `result`，reservation 与 result **一一配对无缺无孤**。
- 独立求和：`reserve_cny=0.6893120`、`conservative_charge_cny=0.5713583`；中心 `ocr=0.5`、`answer_retrieval=0.0713583`（judge/independent=0）。
- 逐笔复算 charge：38 笔带 `settlement.recomputed_conservative_charge_cny` 且与 `conservative_charge_cny` **全部一致**；其中 3 笔 chat 用 `usage×官方单价` 复现（prompt 2 元/M、completion 8 元/M）**逐笔相符**，35 笔 embedding/rerank 用 `total_tokens×unit_price` 复现**逐笔相符**；OCR 1 页 = 固定 0.5；余 4 笔（OCR+3 拒答）无 recomputed 字段，拒答按全额上界留账。
- 请求：新增 42，全局 **547**（505+42）≤ GO **566** ≤ 硬顶 **1000**；`P2-LIVE` 阶段累计 42；**无 P2 阶段外新增**。
- 完整性：`settlement_rejected=0`、`boundary_anomaly=0`；前缀 `1f46d1b9…` 不变 ⇒ **纯追加**；accounted `15.0709445+0.5713583=15.6423028` 与逐笔 `prior_accounted_cny/stage_accounted_cny` 递推一致；42 笔 reservation **全部**记 `total_limit_cny=40 / stage_limit_cny=20`。

## 3 回执/产物一致性 — PASS

- `PILOT/` 7 个产物与 `D:\mktkb-p2-run\pilot-20261111-01\p2-run\` **逐字节相同**（cases/dataset/gate/summary/manifest/run_result/requests）；`pilot-record.json` 为 PM 新增。
- `gate.attempts`：`gate_reserved=42=expected`（36 非 answer + 6 answer），72 回执 = 36×2，回执 reservation_id **⊂ 账本**且无多余；回执 `charged` 合计 `0.5095523`=`center_stage_total_cny`；`center_total_with_answers=0.5713583`=账本。
- 出站：summary/briefing 39 = transport(chat 3/embed 33/ocr 1/rerank 2) = 账本 42 笔中 39 笔真实发送（6 chat 里 3 笔零调用仍是 reservation）。
- `binding` 完整（`missing=[]`）：config_hash、dataset_sha256、dataset_version、index_revision=5、pipeline_version、`trace_identity_bound=true`，manifest trace 六字段齐；`citation_evidence` 4 轮/6 引用/**verified 6、active 6、in_run 6**。
- 数据集：5 行与 `fixtures/evaluation/{b0,regression}.jsonl` 冻结行**逐字符相同**（仅 CRLF）；其 LF 归一摘要 `a3878212…` **=** `binding.dataset_sha256`（4712 B）。注意：磁盘上 `dataset.jsonl` 原始摘要为 `a510d71b…`（4717 B，CRLF），核验时须归一换行，否则误判。
- 凭据抽检：8 个产物对 `sk-`/`api_key`/`Authorization`/`Bearer`/`AKID`/`secret`/环境变量名/`password` 全 **clean**。
- 需说明：`run_result.json` 是 **answer 单侧**记账（reserved 6 / settled 0.061806），与账本 42 笔**不同范围**，非矛盾；建议产物内明写 scope。

## 4 停止/失败语义 — PASS（口径冲突 1 处）

- `gate.failure=null`、`stop_code=null`、`status=succeeded`、`real_sends_allowed=true`、`artifact_validation.ok=true`、`gate_notes=[]`；8 项 checks 全 `ok`；产物内**不存在** `usage_evidence_missing`/`attempt_accounting_mismatch`/`attempt_quota_exhausted`/落盘 `P2_NO_PAID_ATTEMPT` 字样。
- 零付费拒答**有据**：3 笔 chat `status=failed`，`error_code=P2_NO_PAID_ATTEMPT:{conflict,not_found,answer}`，`usage=null`，`requests.jsonl` 对应 `provider_calls.chat=0`（RG005 连 embedding/rerank 也为 0）；chat 出站实测 3 = 3 笔成功答案。
- 口径冲突：`summary.requests.settled_failure=0` 而账本有 **3 条 `status=failed`**（被计入 `unused_no_paid_attempt=3`）。同一事实两种词汇，验收易误读，建议 T207 前统一。
- 口径冲突 2：3 笔零调用拒答仍按**全额上界**留账（3×0.018688=**0.056064**），`requests.jsonl` 也写 `billed=true`；账本 `provider_billed_cny=null`。保守留账合乎 runbook §6.1，但"billed" 与"供应商账单"不是一回事，须在报告口径中分开。
- `gate.checks` 的 `detail` 在 `ok:true` 时仍写失败文案（如 not_expired→"授权已过期"），属证据可读性瑕疵。

## 5 成本/额度 — PASS

- 结算 **0.5713583** ≤ pilot ≤**2** ≤ `P2-LIVE` **20** ≤ 项目 **40**；剩余：阶段 19.4286417、项目 24.3576972；请求 42/61 计划、547/566 GO、547/1000 硬顶；OCR 1 页 0.5。
- 预留 vs 结算：reserve 0.689312 → settled 0.5713583，**释放 0.1179537**（chat 超预留 0.050322 + 检索类 0.0676317）。
- 口径提醒：settled 里 **0.056064 是零调用拒答的保守留账**，不是供应商花费；按 usage 重算的真实清单价花费 ≈ **0.5152943**（ocr 0.5 + 检索 0.0095523 + 答案 0.005742）。中心占用 answer_retrieval 0.0713583/9、ocr 0.5/6。

## 6 质量观察 — 记录，不作达标结论

按冻结标签做机械核对（不计分、不替代 T205/T209）：

- **Q01 → 与期望不符（本 pilot 唯一实质失败）**：期望 `exact` 值"B区1号货架第二层"，实际 `kind=conflict`、0/1 命中、无引用。根因线索：`run_manifest.ingest` 里 `V03_物品位置表_历史V1.xlsx` 与 `D01_物品位置表.xlsx` 是**两个独立文档**（document_id 不同、各 `version_number=1`、都 active），B0 的"同槽 V1→V2"配方**未复现**；故冲突来自播种方式，而非"同文档版本串值"。**报告 §2 的"顺带覆盖版本槽"与事实不符**，须更正。
- Q25：`answer`，期望值 2/3 命中（"领取时登记数量"因插入"实际"未整串命中），来源含期望 `D03 paragraph:5`，另掺 `D09` 图片文本；句子三段近重复拼接，可读性一般。
- RG005：`not_found` 且不合禁用语，**零 chat 零出站**，属正确拒答。
- RG006：t2 命中"40"且无禁止值（正确）；**t1 命中"40"但同时给出禁止值 `店内外侧`/`QF01`** —— 若禁止值口径是"末轮"，t1 可接受；若是"整例任意轮"，t1 即失败。口径需 T207 明确，本次不作判罚。
- Q37：OCR 路径 `answer` 命中"领用登记表"，引用 `D09 p1`，1 页 0.5 元可追溯；但答案仅一句且与 Q25 高度重复。
- 归属建议：5 题全部列入 T207 失败/覆盖归因（Q01 首轮定位），**不得**把"运行成功/账本自洽"写成"质量达标"。

## 7 合规 — PASS（本次复核）

- 只读：三份固定文件与我到达时一致（GO raw `79a5f318…`=pilot-record、budget raw `736b4d2b…`=pilot-record、账本前缀 `1f46d1b9…` 未动且整体 `6b053520…`=record）⇒ **运行后无人改写**三者，仅账本合法追加。
- 未 commit/push（PILOT 仍 `??` 未跟踪）；未发起真实调用；未联网；未读 `.env`/H1/H2（仅读公开冻结 `fixtures/evaluation`）；本复核只写 `PILOT/review-pilot.md` 与 `PILOT/evidence/verify/`（3 文件）。

## 返工单（不阻断 pilot 接收，需在 T207 前闭环）

1. 更正 `report.md` §2：Q01 的"同槽 V1→V2 覆盖"不成立（实际两独立 active 文档）。若要该证据，须**新计划+新 GO** 重跑（计入同 20 元/同累计请求，不得复用本次）。
2. 产物注明 `run_result.json` 为 answer 单侧范围；否则 6 vs 42 会被读成账实不符。
3. 统一失败口径：`settled_failure` 与账本 `status=failed` 对齐；零调用拒答应标"保守留账"而非 `billed`。
4. 修 `budget.json` 两个元数据字段（`remaining_conservative_cny_at_start`、`stage_revision.revised_at`）——只由经理在预算修订时改，本人未动。
5. 说明/修正 `settlement.output_valid=false`（chat 侧是 dataclass 默认值，`build_chat_evidence()` 从不赋值，非质量信号），并明确 `paid_attempt` 字段缺失语义。
