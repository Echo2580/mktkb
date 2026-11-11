# P2-T207-FIX-CONFLICT-R1 报告（收窄图片拦截 + 复核异常兜底 + 报告口径）

范围：只闭环独立验收对本包提出的 MEDIUM-1 / LOW×2。零真实调用；未改 `evaluation/**`、fixtures、账本/预算/GO；未 commit。

## 1. 改动（+30 行，不改既有分支；`copy.py` 未动，sha256 前 16 = `cfabcc3a3a4ff258`）
- `conversations/intent.py` +28：`image_source_question` 收窄（见 §2），`IntentPlan.image_not_supported` 与 service 路径不变。
- `conversations/service.py` +2：`_same_entity_evidence` 的 except 增 `OperationalError`（§5）；docstring 口径改为"只披露冲突值、不产出作答值"。
- 新增 `tests/integration/test_t207_fix_conflict_r1.py`（3 项，挂 `t09_network_guard`）；上一包的测试文件与 4 项断言未改（sha16 `f858cd1a30bef651`）。

## 2. 收窄规则（前 → 后，口径：图名必须"短修饰"引用，资料名+图名不算图片输入）
| 句式 | R1 前 | R1 后 |
| --- | --- | --- |
| 来源介词 + 图名 | 根据/依据/从… 与图名间隔 ≤10 字 | 间隔 ≤4 字（"根据货架照片"命中；"根据物料领用通知图片"不命中） |
| 祈使看图 | `看(这/那)(张)?(图/照片…)` | 保留；新增 `看(看/一下/下)+≤4 字+图名` |
| 图片内部 | 图名+里/中/上 **或裸"图里/图中"** | 只认"图名+里/中/上"，且图名须在同一子句内以 ≤4 字短修饰出现（"照片里…"命中；"物料位置表截图里"不命中） |

## 3. 反例矩阵（`evidence/counterexamples.json`，同一产品 HTTP 入口，D01/D03/D07/D09 已发布）
| 问题 | R1 前 | R1 后 |
| --- | --- | --- |
| 组织架构图中市场部向谁汇报？ | not_found（图片拒答） | **answer**（D07） |
| 流程图里第三步是谁审批？ | not_found（图片拒答） | **answer**（D07） |
| 根据物料领用通知图片要求先填写什么？ | not_found（图片拒答） | **answer**（D09/D03/D07） |
| 从物料位置表截图中能看出城东店的宣传海报放在哪？ | not_found（图片拒答） | **answer**（D01） |
| 从物料位置表截图里能看出什么？（无实体） | not_found（图片拒答） | clarification（既有补槽，正常路径） |

图片类正例仍命中：`根据货架照片告诉我没有标记物品的位置`、`看这张图…`、`照片里…`、`从这张截图看…`、`看看货架照片…`。

## 4. 三例复核 + 54 例差分（`evidence/impact-diff.json`，与上一包验收的 `impact-after.json` 同口径逐题比对）
- N08：`not_found` + `IMAGE_NOT_SUPPORTED` 文案**逐字不变**，`strict_status=pass`。
- C05/C06：仍 `conflict`，值 `B区1号货架第二层`/`D区暂存柜`、`010-00000001`/`010-00000099`，两值两来源不变。
- 54 例（Q01–Q40/N01–N08/C01–C06）：`changed_ids = []`（kind/文本/来源含 locator/冲突/候选/判分全一致）。

## 5. 异常兜底（LOW）
`_same_entity_evidence` 只捕获 4 类稳定异常（新增 `OperationalError`）：复核放弃 → 不披露冲突、由既有路径给结论，不冒泡 500；**不宽捕获**其它异常（安全类照旧冒泡）。
测试注入 DB 层异常（`candidate_ids=None` 的 record 探针抛 `OperationalError`）：R1 后 200 + `answer` + `conflicts=[]`（探针确实执行过）；R1 前该用例 HTTP 500（`evidence/verify.txt` 第 1 节）。

## 6. 口径更正与未决分歧
- 更正：旧报告"复核不产生任何字段值"不严谨 → **"只披露冲突值（本问请求字段的原值 + 来源摘要），不产出作答值（无唯一答案值、不引入其它字段值、正文只有字段名）"**。
- 分歧（需发布方口径）：硬门禁 `citation_required` 只对 `kind=="answer"` 生效（`evaluation/gate.py:1658-1659`），conflict 轮适配器 `retrieved=()/evidence=()`（`evaluation/product_adapter.py:2116-2130`），故**不触发门禁失败**；但产品级"引用⊆本轮候选"在 conflict 路径被**局部放宽**——复核只读产品检索索引（SQL 只读、无供应商调用），可读到候选窗口外的同实体可见来源。若要求冲突也严格受候选约束，需另立设计（把 document 面召回并入同一计划项）。

## 7. 回归（`evidence/verify.txt`）
`tests/integration` 425 passed；`tests/unit` 361 passed / 1 failed（既有环境漂移 s2h 预算 40≠10，验收方已在 HEAD 复现）；`tests/acceptance`+`test_p0_acceptance` 77 passed；`p2_public_controls`+`test_chat`+`t106_copy`+两个 t207 文件+`t103_record_fallback` 86 passed。
新测试在"只回退这两个产品文件"的 R1 前源码上 **3/3 失败**（同次运行上一包 4 项仍通过）→ 锁定有效且可归因。

## 8. 限制
- 零真实调用，未做 live 复测：结论只覆盖离线可测部分；"引用⊆候选"是否接受仍待发布方确认。
- 收窄用"短修饰 ≤4 字"的字面启发式，不是语义判定：`从位置表截图里…`（3 字资料名）仍会被判为图片输入而拒答——属已知边界，未扩大改动去修。
- 本节反例多依赖具体资料内容才能"answer"（如 `流程图里…审批` 需要 D07 的"审批意见"）；反例只锁定"不被图片规则拦截"，不锁定检索质量。
