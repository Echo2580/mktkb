# P2-T207-FIX-CONFLICT 独立验收（N08 拒答 + C05/C06 冲突，证伪优先）

**结论：接收（任务 1–7 全部 PASS；附 2 项 MEDIUM 风险与 2 项 LOW 问题，均不阻断本包）。**

- 工作目录 `D:/GPT项目/市场部AI知识库`，分支 `codex/p2-e2e`。验收开始时 HEAD=`edeeefd`；
  验收过程中并行包 FIX-SCORE 于 12:02 提交 `b4b9b72`。**本包 3 个产品文件在两个 HEAD 的 blob 相同**
  （`ce47ca47ba` / `81eeee1a7b` / `917e5cb164`），故该提交不影响本次结论。
- 工作区本包文件 sha256 前 16 与开发报告一致：`intent.py 76123b492ae7c294`、`service.py 51f481062e40f416`、
  `copy.py cfabcc3a3a4ff258`、`test_t207_fix_conflict.py f858cd1a30bef651`。
- 零真实调用；只写本目录 `review.md` 与 `evidence/verify/`；未碰并行包、账本/预算/GO；未 commit。
- 全部证据可在 `evidence/verify/` 复算（脚本：`verify3.py`、`generality.py`、`generality_synthetic.py`、
  `trace_spans.py`；数据：`three-cases-*.json`、`impact-*.json`、`generality-*.json`、`trace-spans.json`、
  `pytest-*.txt`）。

## 逐条判定

### 1. 范围与合规：PASS

- `git diff --numstat HEAD` 本包只有三个产品文件且**纯新增**：`intent.py +42/−0`、`service.py +68/−0`、
  `copy.py +12/−0`；新增 `backend/tests/integration/test_t207_fix_conflict.py`（7333 B）与本报告目录。
- 新增测试无 `skip`/`xfail`/`import pytest`（grep 全 False）；`git diff --cached` 为空、HEAD 无本包 commit。
- 未改 `fixtures/**`、`docs/evidence/**`（账本/预算目录，`git status --porcelain -- fixtures docs/evidence` 为空）、
  GO/预算配置；`docs/evaluation/p2-dataset-v0_1.md` 的改动属 FIX-H2SCORE（见下条）。
- 并行包改动与本包不重叠（按内容归属）：`evaluation/p2_runner.py`、`docs/evaluation/p2-dataset-v0_1.md` §10
  （FIX-H2SCORE，注释明示包名）；`scorers.py`/`p2_scoring.py`/`test_p2_*` 已由 FIX-SCORE 提交进 `b4b9b72`。
- 零真实出站：`repro-before.json`/`repro-after.json` 的 `provider_posts` 全为 `{"attempts":{},"outcomes":{}}`；
  b0/harness 走 `assert_fake_configuration`（假凭据）与模型替身；861 条实跑 0 次外部请求。

### 2. 三例独立复现（前后）：PASS

不采信开发结论，用**两种相互独立的形状**各跑一遍：①开发脚本的"每轮 1 次 query embedding"门控
（`repro_r2_r3.py` 复跑）；②我自己的"rag 候选只剩表格行"裁剪（`verify3.py`，不依赖门控实现细节）。

| 例 | 修复前 | 修复后 |
| --- | --- | --- |
| C05 窄候选 | `answer`，仅 `D01_物品位置表.xlsx`，1 次模型调用 | `conflict`，值 `B区1号货架第二层` / `D区暂存柜`，来源 `D01(文档 V03 槽)`+`V01`，**0 次模型调用** |
| C06 窄候选 | `answer`，仅 `D02_合作店家信息.xlsx`，1 次模型调用 | `conflict`，值 `010-00000001` / `010-00000099`，来源 `D02`+`V02`，**0 次模型调用** |
| C05/C06 不限候选 | `conflict`（两值两来源） | `conflict`（逐字相同） |
| N08 | `clarification`「请补充要查询的门店或物品。」，候选 `城东店/城西店` | `not_found`，无来源、无候选，0 次模型调用；文案含"照片、图片不做实物识别""不读取用户提供的照片""属于首版范围外""无法据此判断物品的位置" |

- 文案口径边界：N08 文本不含 `照片中`/`已定位`/`未标记物品位于`（与 `b0.forbid_phrases` 一致）；
  含"不能识别照片里的实物"属否定句，不构成"声称完成定位"。
- **零写入**：ask 前后对全库逐表计数（`three-cases-*.json.write_diff`）只有会话类表变化
  （`conversations/conversation_messages/conversation_requests/conversation_message_sources`）；
  `source_units`/`retrieval_*`/`document_versions` 行数不变 → 修复路径不写索引、不写账本。
- **Span 契约**（`trace-spans.json`）：N08 trace=`legacy`/not_found/reason=`IMAGE_NOT_SUPPORTED`，
  spans=`{intent_parse, retrieve, commit}` 与 `required_spans` **相等，missing=[]**；
  C05 窄候选 trace=`legacy_with_rag_candidates`/conflict，含 `retrieve` 与新增 `entity_conflict_check`，
  required 仍满足。即"命中仍执行一次正文检索"属实，零模型轮的 Span 契约不破。

### 3. 非硬编码检查（关键）：PASS（附一处文档口径问题）

- 三个产品文件里 **没有** C0x/N0x/Qxx 题号、题面文字、答案值（`B区1号货架第二层`/`010-00000001`/
  `010-00000099`/`D区暂存柜`）、文档名（`D01`/`V01`/`物料位置表`…）特判；新增行只有
  `T207-FIX-CONFLICT`/`N08` 注释与通用句式/实体规则。判断依据是"句式 + 同实体同字段"而不是题面。
- **泛化实证**（`generality-synthetic-*.json`）：临时目录里合成一份**全新资料**
  `合成物料位置通知.docx`（"城东店宣传海报临时调整至 C区9号架。"），与 D01 一起发布，候选裁成表格行：
  修复后 `conflict`，值 `B区1号货架第二层` / `C区9号架`，来源 `D01`+`合成物料位置通知.docx`，0 次模型调用；
  修复前 `answer`（1 次调用）。→ 冲突复核对"未见过的资料与其名称"同样生效。
- **负对照**（`generality-synthetic-*.json` / `generality-*.json`）：
  ①合成"**同值**"通知（"临时调整至 B区1号货架第二层"，与表格逐字相同）→ 两臂都 `answer`（不伪造冲突）；
  ②V07 独立通知的正文未抽出结构化字段（`retrieval_field_index` 为空）→ 仍 `answer`，复核不会把无字段正文
  硬塞进冲突；③只改电话的通知 + 问"地址" → `answer`（按请求字段裁剪）；④问"负责人"（任何资料都没记录）
  → `not_found`（复核不越权造结论）。
- 冻结 54 题的句式命中面（`three-cases-after.json.image_pattern`）只有 `["N08"]`，Q37/Q38 等
  "物料领用通知图片要求…"未被误判。
- **需更正的口径**：报告 §4/§7 称复核"不产生任何字段值"**不严谨**。`_conflict_views` 会把**本问请求字段**的
  原值写进 `conflicts[].entries[].value`（见上表两值），来源还可能是候选窗口外的单元；真正成立的是
  "不产生唯一答案值、不引入其它字段值、响应正文只有字段名不含值"。可能外泄的内容 = 同实体 + 本问字段 +
  已通过可见性/版本复核的原值 + 来源摘要（文档名/定位）。建议报告改为"只披露冲突值，不产出作答值"。

### 4. 影响面独立复核：PASS

- 做法：`before = 工作区 backend/src 的完整副本 + 三个产品文件换成 HEAD 版本`，`after = 工作区`；
  逐文件比对确认**两臂只差这三个文件**（evaluation 代码完全一致），因此差异可归给本包。
- 54 例（Q01–Q40/N01–N08/C01–C06）逐题对照：**changed_ids = ["N08"]，其余 53 例 0 变化**
  （kind/文本/来源/冲突/候选全部一致）。N08：`clarification → not_found`，候选清空，`status pass→pass`、
  `strict_status fail→pass`。
- Q39/Q40 仍 `answer`（来源 D10+V03 槽，盘点"地点"未进冲突）。C05/C06 在离线不限候选口径下前后均为
  `conflict`（与开发"离线本来就对、缺陷在候选窗口"的判断一致）。
- 顺带澄清：C05/C06 的 `strict_status` 在两臂都是 `fail`，原因是 b0 严格口径只查**正文文本**是否含值，
  而冲突正文是通用句式（值在结构化 `conflicts` 里）；这是既有判分口径的产物，**不是本包回归**。
- live 与 offline 差异：live 每轮只有 1 个 query_embedding 计划项，第 2 路召回在发送前被拒 → document 面候选为空
  → 冲突比较看不到正文通知；离线不限候选时正文可召回，故原本就 `conflict`。本包装配的"窄候选"形状与此等价。

### 5. 边界与风险：PASS（结论：不违反 live 硬门禁，但产品级"引用⊆候选"被局部放宽，需发布方确认）

- **是否违反"引用⊆本轮检索候选"**：硬门禁口径上没有。`citation_required` 只对 `kind=="answer"` 生效
  （`evaluation/gate.py:1658-1659`：`if str(kind) != "answer": continue`）；适配器对非作答轮一律
  `retrieved=()`、`evidence=()`（`evaluation/product_adapter.py:2117-2130`），因此 conflict 轮不会因此 fail-closed。
  说明：我没跑 gate 本体（需要 run 目录与 cases.jsonl），这一条是代码口径判定 + 实测 `model_calls=0`/`retrieved` 为空。
- **但产品级候选上界确实被放宽**（实测）：C05 窄候选下 `candidate_calls` 显示候选只剩 9 个 `table_row`
  单元，而返回的来源含 `kind=paragraph` 的 V01 单元（`three-cases-after.json.C05_narrow.source_units`）
  → 引用集合 ⊄ 本轮候选集合，且冲突值随之披露。`_same_entity_evidence` 用 `candidate_ids=None` 直接读
  产品检索索引（只读 SQL、无供应商调用、`limit=20`），可见性/版本仍由 `visible_source_units_stmt` 复核。
  这是**有意的行为变更**（报告 §7 已承认），不触发门禁失败；若发布方要求冲突也必须严格受候选窗约束，
  需按报告建议把 document 面召回并入同一计划项（另做设计）。
- **零付费轮 gate 口径**：计划项 `requests` 是**请求上界**而非期望值（`evaluation/p2_live.py:289-291`）；
  零 chat 发送走 `NO_PAID_ATTEMPT → close_unused（保守留账、不停止）`（`p2_live.py:1289-1300`）。
  C05/C06 修复后正是零付费轮，与既有账本口径兼容；Span 契约亦满足（见第 2 条）。
- 复核**失败面**：只捕获 `KnowledgeRevisionChanged/IndexNotReady/QueryRejected`；DB 层 `OperationalError`
  会冒泡成 500，与同文件其它调用点的宽捕获不一致（LOW，建议补一层兜底）。
- 复核**放大面**：探针不限 term，只看"同实体 + 请求字段"。若同实体另有一份有效资料记录不同值，answer 会变
  conflict——这是本修复的意图，但属行为面扩大；实测 54 例离线 0 变化，live 重测时应观察 Q09–Q24 等记录型题
  是否新增 conflict。

### 6. 回归：PASS（既有 1 failed 确认为环境漂移）

| 套件 | 结果 |
| --- | --- |
| `tests/unit` | 361 passed / **1 failed**（s2h，见下） |
| `tests/integration` | 422 passed（含新增 4 项） |
| `tests/acceptance`（b0_baseline 7 + mutation 13 + security） + `test_p0_acceptance` 7 | 77 passed |
| `test_t207_fix_conflict` | 4 passed；**同一文件在 HEAD 产品源码上 4 项全 fail**（证据 `pytest-t207-new-on-HEAD.txt`） |
| `test_t09_b0_baseline` / `test_t09_mutation` / `test_p2_public_controls` / `test_p0_acceptance` / `test_chat` / `test_p1_t106_copy` | 7 / 13 / 8 / 7 / 52 / 15 全 passed |

- s2h 失败确认为**环境漂移**，三重证据：①报错为 `共享预算总上限必须等于当前项目上限 10.0 元（当前 40.0）`；
  ②**用 HEAD 产品源码同样失败**（`pytest-s2h-r3-on-HEAD.txt`）；③把 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=40` 对齐后
  14/14 全通过（`pytest-s2h-r3-limit-aligned.txt`）。数据源 `docs/evidence/LOCAL-R1-20261101/budget/budget.json`
  的 `limit_cny=40`（live 提额遗留，git 未跟踪/未修改），代码常量 `TOTAL_LIMIT_CNY=10.0`（`live_authorization.py`）。
  账本/预算属禁止改动面，本包未碰。

### 7. 限制：如实声明

- **未做真实调用复测**（按任务要求）。live 形状用两种门控/裁剪仿真得到，二者都复现了
  "修复前 answer、修复后 conflict"，但它们只证明了"候选只剩表格行 ⇒ C05/C06 失败"这一**充分条件**，
  未端到端证明 live 现场的唯一性（AttemptBudget 拒绝 → vector 面降级 → document 面空）。
  因此：**本包结论对"T207 定点 live 重测"只提供产品侧行为保证，仍需一次受控 live 重测确认**；
  该限制来自任务约束，不降低本包（离线可测部分）的判定强度。
- 验收期间 HEAD 由 `edeeefd` 前移到 `b4b9b72`（并行包 FIX-SCORE 提交）：本包产品文件 blob 未变，
  回归与 54 例差分在"evaluation 代码两臂一致"的前提下完成，结论不受影响；但并行包仍在动
  `p2_runner.py`/`docs/evaluation/p2-dataset-v0_1.md`，跨包合并后建议复跑一次 `tests/integration`。
- 我的 b0 装配未启用 trace 持久化（`trace_id=None`），Span 证据改用 `ProductEvalAdapter` 路径取得
  （`trace-spans.json`），不影响契约结论。

## 风险清单（不阻断接收）

| 级别 | 风险 | 证据 | 建议 |
| --- | --- | --- | --- |
| MEDIUM | `image_source_question` 过度拦截：`图中/图里` 与"根据…图片/截图"会命中，对**已发布资料**的图形类问题会误判为范围外拒答 | 探针实测勾中："组织架构图中市场部向谁汇报？"、"流程图里第三步是谁审批？"、"根据物料领用通知图片要求先填写什么？"、"从物料位置表截图里能看出…"（`three-cases-after.json.image_pattern.adversarial`） | 收窄：`图里/图中` 需与 `照片/图片/截图` 共现，或要求"看图/根据…照片"式来源介词；补 4 条反例测试 |
| MEDIUM | 冲突证据可越出本轮 rag 候选（引用⊄候选） | 第 5 条实测（paragraph 单元 V01 不在窄候选内） | 需 PM/发布方确认是否接受；否则把 document 面召回并入同一计划项 |
| LOW | 报告"不产生任何字段值"表述不准 | `conflicts[].entries[].value` 含请求字段原值 | 改为"只披露冲突值，不产出作答值" |
| LOW | 复核异常面偏窄（`OperationalError` 冒泡 500） | `service.py:661` 仅捕获 3 类 | 补一层兜底或与其它入口一致的宽捕获 |

## 最终建议

**接收**。三例独立复现均"修复前失败/修复后通过"，54 例差分只有 N08 变化，新增测试在 HEAD 上 4/4 失败
（锁定有效），既有 1 例失败确认为共享预算漂移而非代码。合并前建议：①按 MEDIUM-1 收窄图片句式（可放本包
R1 或紧随的小包）；②让 PM 就"冲突可读候选窗口外来源"给出明确口径（若要求严格受候选约束，需另立设计项）。

## 证据索引（`evidence/verify/`）

- `three-cases-{before,after}.json`：三例前后（含候选调用、写入差分、来源单元类型、句式探针）
- `repro-{before,after}.json`：复跑开发脚本（embedding 门控形状）
- `impact-{before,after}.json`：54 例两臂逐题记录（`impact_diff.py` 复跑）
- `generality-{before,after}.json`、`generality-synthetic-{before,after}.json`：泛化与负对照
- `trace-spans.json`：N08/C05 的 Span 与 required_spans 比对
- `pytest-*.txt`：各套件原始输出（含 HEAD 对照与预算对齐对照）
- 脚本：`verify3.py`、`generality.py`、`generality_synthetic.py`、`trace_spans.py`
