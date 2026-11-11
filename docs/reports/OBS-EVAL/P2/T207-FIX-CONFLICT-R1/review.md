# P2-T207-FIX-CONFLICT-R1 独立验收（收窄图片拦截 + 复核兜底，只读复核）

**结论：接收（任务 1–7 全部 PASS）。** 本包闭环了上一轮验收的 MEDIUM-1 与两项 LOW：N08 仍按范围外拒答、
C05/C06 仍 conflict、54 例逐题 0 变化、5 类反例恢复既有正常路径、OperationalError 不再冒泡 500。
附 2 项 MEDIUM 残留风险（"≤4 字短修饰"启发式的误拒/漏拒两面）与 1 项 LOW，均**不阻断 T207 定点重测**，
但会影响未见说法/H2 的可用性，建议另立小包收口。

- 验收目录：`D:/GPT项目/市场部AI知识库`，分支 `codex/p2-e2e`。开始时 HEAD=`b4b9b72`；
  验收过程中并行包 H2SCORE-R1 于 **12:52:59** 提交 `3bc8347`。本包两个产品文件的 blob/sha256 在该提交前后
  **不变**（`intent.py 4cfcf7791c27e1ce…`、`service.py 41512464d7948a29…`），故结论不受影响；
  提交后的最终复跑仍 7 passed（见 §5/§6）。
- 零真实调用；只写本目录 `review.md` 与 `evidence/verify/`；未改 `evaluation/**`、fixtures、账本/预算/GO；
  未 commit（`git diff --cached` 为空，HEAD 的两笔提交分别是并行包 FIX-SCORE 与 H2SCORE-R1）。
- 全部数字可用本目录脚本复算：`impact_diff.py`、`matrix.py`、`opfallback.py`、`rule_boundary.py`、
  `netguard.py`；两臂构造与哈希见 `arms.json`，R1 前后补丁见 `r1-delta.patch`
  （仓库根执行 `git apply -R <该补丁>` 即得 R1 前的两个产品文件；我只做了 `--check` 验证，未改工作区）。

| 任务 | 判定 | 一句话证据 |
| --- | --- | --- |
| 1 范围/合规 | **PASS** | R1 delta 只动两个产品文件（+40/−12、+4/−2），copy.py 与上一包测试哈希未动，无 skip/xfail、无 commit、零出站 |
| 2 核心回归 | **PASS** | N08 not_found（文案逐字不变、strict pass）；C05/C06 conflict 两值两来源；54 例 `changed_ids=[]`；Q39/Q40 answer |
| 3 反例矩阵 | **PASS** | 修复前 5/5 误拒；修复后 4 类 answer + 无实体 clarification；5 条正例 rule=True 且 HTTP 全拒答 |
| 4 OperationalError 兜底 | **PASS** | R1 前 500 → R1 后 200+answer+conflicts=[]（探针=1）；安全异常 AccessDenied 仍 403，未被吞 |
| 5 锁定有效性 | **PASS** | 回退两个产品文件后新测试 **3/3 失败**（上一包 4 项仍过）；恢复后 7 passed |
| 6 回归 | **PASS** | integration 425、unit 361/1（s2h 环境漂移，HEAD 同样失败，对齐 40 后 362）、acceptance+p0 77、定向 86 |
| 7 限制评估 | **PASS（有残留结论）** | 误拒/漏拒两面均量化；不阻断 T207 定点重测，H2/未见说法有影响（见 §7） |

## 0. 复跑方法（两臂只差两个产品文件）

- `arm_before` = 当前 `backend/src` 的完整副本，仅把 `conversations/intent.py`、`conversations/service.py`
  换成 **R1 前版本**。这两个文件的 sha256 前 16 = `76123b492ae7c294` / `51f481062e40f416`，与上一轮
  FIX-CONFLICT 独立验收记录的 R1 前哈希**逐字一致**（来源可追溯，不是我反推的近似版本）。
- `arm_after` = 当前 `backend/src` 的完整副本。逐文件比对两臂：只有这两个文件不同（`arms.json`）。
- 全部脚本在导入 `mktkb` 前锁死非回环 `AF_INET/AF_INET6` 的 `connect/connect_ex/create_connection`；
  文档不写盘、模型/OCR 是受控替身（b0 `EvidenceEchoGateway` + `OCRTranscriptStandIn`）。
- 运行示例（在仓库根）：
  `.venv/Scripts/python.exe docs/reports/OBS-EVAL/P2/T207-FIX-CONFLICT-R1/evidence/verify/impact_diff.py --src=<arm>/src --out=<json>`
  （`matrix.py`/`opfallback.py`/`rule_boundary.py` 同形；pytest 在 `backend/` 下运行）。

## 1. 范围与合规：PASS

| 检查 | 结果 |
| --- | --- |
| R1 净改动 | `intent.py +40/−12`（净 +28）、`service.py +4/−2`（净 +2）；`copy.py` sha16 `cfabcc3a3a4ff258` 未动；上一包测试 `f858cd1a30bef651` 未动；新增测试 `370c01db347d3f9a`（3 个 test，无 skip/xfail） |
| 改动内容 | 仅 `intent.py` 的图片句式收窄（`_IMAGE_MODIFIER_CHARS=4`、短修饰引用、删除裸"图里/图中"）与 `service.py` 的 docstring/except；delta 全文见 `evidence/verify/r1-delta.patch` |
| 未碰禁止面 | `git status --porcelain -- fixtures` 为空；`docs/evidence` 被 .gitignore，按 mtime 核对：`budget.json 01:42`、`live-ledger.jsonl 11:13`、`P2-LIVE-GO*.json 11:14`（均早于本包工作起点 12:37），且 12:00 后无任何 `docs/evidence/**/*.json` 变更 |
| 无 skip/xfail | 新测试 3 个 `def test_`；grep `skip|xfail` 为 False |
| 无 commit | 本包未提交；HEAD 两笔提交均属并行包（FIX-SCORE 12:02、H2SCORE-R1 12:52） |
| 零真实出站 | 新测试挂 `t09_network_guard`；我的脚本 `blocked_attempts=[]`、loopback 仅 asyncio 自管道（`impact-after: 221`、matrix 58、opfallback 25 次）；模型/OCR 全为进程内替身；未读 .env |

归属说明：工作区里 `evaluation/p2_runner.py`、`p2_score_run.py`、`p2_scoring.py`、`scorers.py`、
`docs/evaluation/*`、`tests/evaluation/test_p2_holdout_scorecard.py` 的改动带 **T207-FIX-H2SCORE** 标记，
且其中前两者已进入 H2SCORE-R1 的提交 `3bc8347`；`.claude/handoffs/_index.md`、`T207/PM/*` 是经理文档。
均不属本包，未纳入验收。

## 2. 核心回归：PASS

| 例 | 修复前（arm_before） | 修复后（arm_after） |
| --- | --- | --- |
| N08 | `not_found`，status/strict `pass/pass`，文案见下 | `not_found`，status/strict `pass/pass`，**文案与本包前逐字相同** |
| C05 | `conflict`，`位置:[B区1号货架第二层, D区暂存柜]`，来源 V03#v2 + V01#v1 | 同左（逐字相同） |
| C06 | `conflict`，`电话:[010-00000001, 010-00000099]`，来源 D02#v1 + V02#v1 | 同左（逐字相同） |
| Q39 / Q40 | `answer`（D10+V03） | `answer`（D10+V03，文本相同） |

- N08 文案（前后一致，无 `照片中/已定位/未标记物品位于`，b0 forbid 判定 pass）：
  "照片、图片不做实物识别：系统只读取已发布的文字与表格资料，不读取用户提供的照片，也不能识别照片里的实物；
  该问题属于首版范围外，无法据此判断物品的位置。……"
- **54 例逐题差分（独立两臂）**：Q01–Q40/N01–N08/C01–C06，比较字段
  `kind/text/sources(document_name,version,status,locator)/conflicts/candidates/status/strict_status/problems`
  → `changed_ids = []`（`impact-compare.json`）。不是只读开发方的 impact 文件：两臂都是我自己跑出来的。
- **交叉印证**（两条独立来源，均一致）：
  ① 与上一轮验收的 `impact-after.json`（R1 前口径）逐题比对：`differing_ids=[]`；
  ② 与开发方 `impact-diff.json` 的 after 列比对：去掉"同一文档多来源单元重复"后 `differing_ids=[]`。
- 零出站：两臂 54 例均无 `blocked_attempts`；模型调用均为进程内 Echo 替身。

## 3. 反例矩阵：PASS（5 类反例 + 正例边界）

同一产品 HTTP 入口（D01/D03/D07/D09 已发布；D07/D09 走受控 OCR 转录；`matrix-{before,after}.json`）：

| 问题 | R1 前 | R1 后 |
| --- | --- | --- |
| 组织架构图中市场部向谁汇报？ | rule=True → `not_found`（图片拒答） | rule=False → **`answer`**（D07） |
| 流程图里第三步是谁审批？ | rule=True → `not_found` | rule=False → **`answer`**（D07） |
| 根据物料领用通知图片要求先填写什么？ | rule=True → `not_found` | rule=False → **`answer`**（D09/D03/D07） |
| 从物料位置表截图中能看出城东店的宣传海报放在哪？ | rule=True → `not_found` | rule=False → **`answer`**（D01） |
| 从物料位置表截图里能看出什么？（无实体） | rule=True → `not_found` | rule=False → **`clarification`**（候选 城东店/城西店，既有补槽路径） |

- **正例仍拒**：`根据货架照片…`、`看这张图…`、`照片里…`、`从这张截图看…`、`看看货架照片…`
  5/5 rule=True；这 5 条我都走了 HTTP，全部 `not_found` + 拒答文案（`refusal_marker=True`）。
  其中 `看看货架照片…` 在 R1 前是 rule=False → `service_error`，R1 后改为拒答（收窄的额外收益）。
- 反例的 "answer" 依赖资料内容（如 D07 的审批意见），只锁定"不被图片规则拦截"，不锁定检索质量。

## 4. OperationalError 兜底：PASS

形状：B0 + `V03→D01(V2)` 同槽 + 独立 V01，rag 候选裁到只剩表格行（14→9，等价 live 单 embedding 的后果），
使"同实体复核"成为 conflict 的唯一开关；探针 `candidate_ids=None & mode=record` 记数（`opfallback-*.json`）：

| 臂 | R1 前 | R1 后 |
| --- | --- | --- |
| A 不注入（形状有效性） | `conflict`，两值 `B区1号货架第二层/D区暂存柜`，probe=1 | 同左，probe=1 |
| B 复核抛 `OperationalError("database is locked")` | **HTTP 500 `INTERNAL_ERROR`** | **HTTP 200 + `answer`（仅 `B区1号货架第二层`）+ `conflicts=[]`**，probe=1 |
| C 复核抛安全异常 `AccessDenied` | HTTP 403 `FORBIDDEN`（未吞） | HTTP 403 `FORBIDDEN`（未吞） |

- 代码面：`service.py:661` 的 except 只列 4 类（`KnowledgeRevisionChanged/IndexNotReady/QueryRejected/OperationalError`），
  无 `except Exception`、无 bare except；`OperationalError` 来自 `sqlalchemy.exc`（`service.py:24`）。
- 语义面：复核失败只放弃本次复核，不披露冲突、不把原证据作废（B 仍给 answer，且给的是**单值**）——fail-closed 成立。
- **捕获面**：它捕获**所有** `OperationalError`，而同文件 `_commit_result:1649` 的先例只对 `locked/busy` 重试、其余上抛。
  复核是增量只读路径，吞掉其它 OperationalError 仍属"放弃增强"，不会掩盖主路径错误；但口径不完全等同先例（LOW，见风险表）。

## 5. 锁定有效性：PASS

把工作区两个产品文件临时换回 R1 前版本（测试文件不换），跑两个 t207 文件：

```
3 failed, 4 passed, 1 warning in 8.34s
FAILED test_published_document_image_phrases_use_normal_answer_path
FAILED test_image_source_question_boundaries
FAILED test_conflict_recheck_db_error_is_fail_closed_not_500
```

- 同一次运行上一包 `test_t207_fix_conflict.py` 4 项仍通过 → 失败可归给 R1 的收窄/兜底，不是既有断言坏了。
- 其中 `test_conflict_recheck_db_error…` 在 R1 前正是 **500**（与 §4 的 B 臂独立互证）。
- 换回后 sha256 与换前逐字一致；随后（并行包提交后）最终复跑 `7 passed in 8.23s`（`pytest-t207-final.txt`）。

## 6. 回归：PASS（1 failed 确认为既有环境漂移）

| 套件 | 结果 |
| --- | --- |
| `tests/integration` | **425 passed**，384.62s（跨过并行包提交，产品文件未变） |
| `tests/unit`（最终树） | **361 passed / 1 failed**（`test_s2h_r3_official_profile.py::test_official_profile_accepted_by_both_entries_and_worst_case_is_2103552`） |
| 同测试用 **HEAD 源码**跑（`-o pythonpath=<HEAD-src>`） | **1 failed / 13 passed** → 与 R1 无关、HEAD 同样失败 |
| 全 unit 且 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=40` | **362 passed** → 预算口径对齐即全绿 |
| `tests/acceptance` + `tests/evaluation/test_p0_acceptance.py` | **77 passed**，78.91s |
| `p2_public_controls` + `test_chat` + `t106_copy` + 两个 t207 + `t103_record_fallback` | **86 passed**，54.15s |

s2h 归一：报错为"共享预算总上限必须等于当前项目上限 **10.0** 元（当前 **40.0**）"；`budget.json.limit_cny=40`
是经理 2026-11-11 01:28 的 P2 提额（mtime 01:42），代码常量 `TOTAL_LIMIT_CNY=10.0`；本包未碰账本/预算/GO。
HEAD-src 与预算对齐两条独立证据都指向"环境漂移"，不是本包回归。

## 7. 限制与残留风险：结论

"≤4 字短修饰"仍是**字面启发式**，不是语义判定，因此有两个方向的残留（`rule-boundary-*.json`）：

1. **仍会误拒（短资料名 + 图名）**：`从位置表截图里能看出什么？`、`根据领用通知图片要求先填写什么？`
   在 R1 后仍 rule=True → HTTP `not_found`（拒答）。这两句指的若是已发布资料（《物品位置表》《物料领用通知》），
   就是误拒。报告 §8 已如实声明 `从位置表截图里…` 这一型，**未提** `领用通知`（4 字）这一型。
2. **新引入的误拒**（报告未声明）：`看通知图片要求先填写什么？` R1 前 rule=False → `answer`（D09/D03），
   R1 后 rule=True → `not_found`。原因是新增 `_IMAGE_VIEW_GAP_PATTERN`（`intent.py:147`：`看`+≤4 字+图名）
   把"看+短资料名+图名"也算图片输入。该句语义两可（也可读成"看通知图片"），但相对 R1 前是**行为回退**。
3. **会漏拒（长修饰/远距离）**：`根据这张随手拍的照片告诉我货架在哪`、`从最新一版货架照片里看，促销贴纸在哪`
   在 R1 前被拒，R1 后 rule=False → 前者走 `clarification`（"请补充要查询的门店或物品"），
   后者走正常路径并得到稳定的 `service_error`（200，模型输出校验拒绝，不是拒答）。
   `看一下这张物料位置表截图…`、`看这张仓库平面图照片…` 两臂都漏。
   **这正是 N08 要消除的失败模式的"未见说法"版本**：产品没有图片通道，但澄清文案会暗示"补槽后可以回答图片问题"。

对两处下游的影响：

- **T207 定点重测**：**不阻断**。冻结 54 例 0 变化，N08 的原句/文案/status 逐字不变，C05/C06 仍 conflict；
  定点重测用的是冻结题面，不会踩到上述未见说法。
- **H2/未见说法可用性**：有影响。① 若 H2 题面出现"短资料名+图名"（如"位置表截图"），会被误拒成 not_found；
  ② 若出现长修饰的图片引用，会退回澄清/普通错误路径，丢掉"范围外"的明确拒答。H2 是生成题，无法预知措辞，
  建议把这两类写进 H2 的已知边界或另立收口小包（例如用已发布资料名词典排除"资料名+图名"、用"图名前无实义修饰"
  替代固定字数；这属于设计变更，不应塞进本 R1）。

## 风险清单（不阻断接收）

| 级别 | 风险 | 证据 | 建议 |
| --- | --- | --- | --- |
| MEDIUM | 短修饰启发式残留误拒：`从位置表截图里…`、`根据领用通知图片…` 仍被当图片输入 | `matrix-after.residual_boundary`：rule=True → `not_found` | 报告已声明第一型；发布方确认可接受，或在下一小包用资料名词典收口 |
| MEDIUM | 收窄导致漏拒：长修饰图片题退回 `clarification`/`service_error`，重开"补槽暗示"面 | `matrix-after.residual_boundary`：`根据这张随手拍的照片…` → clarification；`从最新一版货架照片里…` → service_error | 不是本轮阻断项；建议 H2 前评估，必要时补句式 |
| LOW | 新增 `看+≤4字+图名` 规则引入新误拒（`看通知图片…` 由 answer 变 not_found） | `matrix-before/after` 对照 | 报告 §8 补一句；下一小包再权衡 |
| LOW | 复核兜底捕获**所有** OperationalError（先例只重试 locked/busy） | `service.py:661` vs `:1649` | 可接受（增量只读路径、fail-closed；安全异常实测 403 未被吞） |
| 遗留 | "冲突可读候选窗外来源"（引用⊄候选）仍待发布方口径 | 上一轮 MEDIUM，本包未动 | 不属 R1 范围，PM 另行决策 |

## 最终建议

**接收。** 任务 1–7 全部 PASS；R1 的两个改动都只做"收窄 + 兜底"，没有扩大产品行为面：
54 例 0 变化、N08/C05/C06 逐字稳定、5 类反例恢复既有路径、正例仍拒、OperationalError 由 500 变 200+answer+空冲突、
新测试在 R1 前源码上 3/3 失败、恢复后全绿。合并/合入前建议：① 把本 review 的两项 MEDIUM 残留写进 T207 报告
§8（尤其"漏拒"一面，报告目前只写了误拒）；② H2 前确认 H2 题面是否含"位置表截图/照片"这类短名图片引用；
③ 定点 live 重测按计划执行（本轮零真实调用，不替代 live 验收）。

## 证据索引（`evidence/verify/`）

| 文件 | 内容 |
| --- | --- |
| `arms.json` / `r1-delta.patch` | 两臂构造、文件哈希、R1 前后补丁（+40/−12、+4/−2） |
| `impact-{before,after}.json` / `impact-compare.json` | 54 例两臂逐题记录与差分（changed_ids=[]，含 N08/C05/C06/Q39/Q40 明细与两条交叉印证） |
| `matrix-{before,after}.json` | 5 类反例 + 5 条正例（rule/HTTP）+ 残留边界（`residual_boundary`） |
| `opfallback-{before,after}.json` | A/B/C 三臂：conflict / OperationalError / AccessDenied，探针计数与 conflicts |
| `rule-boundary-{before,after}.json` | 字面启发式的误拒/漏拒清单（含报告未提的两条） |
| `pytest-*.txt` | 原始输出：integration、unit（final/limit-aligned）、acceptance、targeted、t207（targeted/final/R1 前源码）、s2h on HEAD-src |
| `impact_diff.py` `matrix.py` `opfallback.py` `rule_boundary.py` `netguard.py` | 可复算脚本（零出站锁） |
| `scope.txt` | fixtures/账本/暂存区/HEAD/测试计数等范围检查原始输出 |
