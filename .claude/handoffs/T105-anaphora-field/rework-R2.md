# T105 返工单 R2（PM，2026-11-07 01:3x）

> 依据：独立验收 `review-R2.md`（**FAIL**：B1 已修复；B2 因 R1 新分支扩大拦截未收口）+ `docs/reports/OBS-EVAL/P1/evidence/verify/T105-R2/`（01-verdict、02-probe、03-probe-results、04-test-eval-runs）。轮次 **R2/3**（第 2 次返工；上限 3）。
> 基线：R1 交付 `fc60c57`（其上 `fecdfcc` 等 PM 簿记）；本轮为 **1 个新 commit**，**不 amend 历史**。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 1. 未过条款（B2 §5-2「扩大拦截」）—— 必须修

R1 新增两处分支对政策/法规追问排除不完整（`backend/src/mktkb/rag/query.py:1336-1352`）：
- `anaphora_new_content` 只排除 `is_regulation_question`，**未排除 `is_policy_question`**；
- `elif explicit_record_entity and is_anaphora_field_followup(question, state.field_role)` **无政策/法规守卫**；继承的 `state.field_role` 使法规追问被按单字段渲染。

### 验收将按下列场景判定（同一 conversation；上文 `城西店的宣传海报在哪里？`，C5d 为上文问规格后）

| # | 追问 | 当前错误实际 | 期望 |
| --- | --- | --- | --- |
| C5 | 那个海报的价格欺诈规定是什么？ | answer 27 字 = 继承位置 | **不得返回继承字段**（位置/规格等）；按政策/法规题处理：从法规正文作答（对齐单独问 861 字含 2022-07-01/废止规定）或诚实 no_answer；不得 576 字整条倾倒 |
| C5b | 那个海报的相关规定是什么？ | answer 27 字 = 位置 | 同上 |
| C5c | 那个海报适用的价格欺诈规定是什么？ | answer 27 字 = 位置 | 同上 |
| C5d | 上文问规格 → 那个海报的价格欺诈规定是什么？ | answer 29 字 = 规格 | 同上（不得随上文继承字段变化） |
| C3 | 那个海报的档期物料要提前多少天提报需求？ | not_found 35 字 | 从 W02 正文答出 21 天（对齐单独问 D4 518 字），不得压制 |
| C6 | 那个海报的审批流程是什么？ | not_found 35 字 | 从正文作答，不得压制为未记录 |
| C4 | 那个海报的《明码标价和禁止价格欺诈规定》自何时起施行？ | not_found 42 字「未在资料中找到…记录」 | 按法规题作答（日期 2022-07-01 等）或至少不得压成不实的「未找到记录」 |
| C7 | 那个海报的盘点时间是什么？ | not_found 42 字「未在资料中找到…记录」 | **P2**（记录存在、仅缺日期字段）：文案不得称「未找到记录」，尽量准确；不阻塞 PASS |

### 必须保持（回归）
- B1（枚举后 `那个海报的第2页` → page=2）与 B2 点名项（`规格型号`→29 字单字段；`打印材质`/`陈列要求`→not_found 35 字 0 泄露；位置/数量/价格单字段）。
- 不误伤控制组：单独 `档期物料要提前多少天提报需求？`（518 字含 21 天）、单独 T101 法规题（861 字含 2022-07-01 + 废止规定）、`那个流程要提前几天提报`（139 字）、无上文 `那个海报呢`（澄清）、T101/T102 定向、b0/badcase、regression 全部不变。

## 2. 修复方向（最小；最终设计自定但须在 report 说明理由）

- 政策/法规题（`is_policy_question` / `is_regulation_question`）不得进入 `ANAPHORA_NEW_CONTENT` 或「继承单字段」分支；必要时重置继承的 `field_role`/实体，交回既有政策/法规/正文路径（保持 T101 法规优先、T102 政策题不继承实体）。
- 只改 `query.py`、`answer.py`（仅必要、最小，report 单列）+ `backend/tests/` 本包测试；**禁止改 `conversations/`、`intent.py`、fixtures/b0/badcase/gate**；若必须改禁止文件 → 停手报 PM。
- 补 HTTP 用例覆盖 C5 系列 + C3/C6（「实体+指代+政策/法规」组合）；不得 skip/xfail/放宽断言。
- 注意 R2 探针另用三树对照（`17c0e63`/`2306aaa`/当前）证伪；修复后「不得比基线更差」：C5 系列不得出现继承字段答案或整条倾倒；C3/C6 不得被压制。

## 3. 边界（继承 rework-R1 §2）
允许：`query.py`、`answer.py`（仅必要）、本包测试、`report.md`（追加 R2 段并更正 §6 观察项）、证据 `03-test-runs.md`/`04-scope-and-limitations.md` 追加 R2 段（不新增文件，仍 ≤4）。禁止：其余路径、`.env`/Holdout、真实调用、新增生产依赖、push/amend 历史。

## 4. 必须运行的检查（与 R1 相同口径）
本包 2 文件 / `backend/tests/rag` / `integration` / `observability` / 全量（0 failed/0 error；内存 <2GB 轮询；既有 flake 隔离复跑 1 次）/ b0+badcase 对 P0（`case_diffs=0`、gate hard `[]`）/ regression 对 `17c0e63`（仅 RG006 fail→pass、RG005/RG007 不变、无新 hard 名）/ T101+T102 定向 + 新增 HTTP 组合用例。

## 5. 交付
- 1 个新 commit：`p1/T105 R2 fix anaphora policy/regulation interception`；不 push / 不 amend。
- `report.md` 追加「R2 返工」段：C3/C4/C5 系列/C6/C7 修复前后对照（含文本长度/字段/关键值）、根因与最小改动、全部运行数字、残余；**更正 §6 把「政策题+实体+字段词+指代」记为「观察（不阻塞）」的错误**；证据 03/04 追加 R2 段。
- 回复 ≤10 行交接摘要（commit、各场景修复证据、测试数字、偏离、风险）。
