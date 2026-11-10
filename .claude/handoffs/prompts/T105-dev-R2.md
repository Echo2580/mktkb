角色：开发助手（**返工轮 R2**，第 2 次返工），不是验收者。任务 **T105（D6 指代/字段错配）R2 返工**。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`。
工作目录：`D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；当前 HEAD `fecdfcc`（PM 簿记）；**上一轮 R1 交付 `fc60c57`**，工作树应 clean。

## 第一步（按序读）
1. `.claude\handoffs\T105-anaphora-field\rework-R2.md`（**本轮返工单：C3/C4/C5 系列/C6/C7 判据、期望、边界**）
2. 同目录 `review-R2.md`（独立验收 FAIL；根因与代码行）、`report.md`（R1 自述，注意 §6）、`handoff.md`（§4 允许文件）、`review.md`（上一轮 FAIL 背景）
3. `docs\reports\OBS-EVAL\P1\evidence\verify\T105-R2\`（01/03 逐场景与谓词级根因；04 命令口径）
4. `git diff fc60c57^..fc60c57 -- backend`（R1 改动，确认两处新分支）

## 第二步：实现（最小改动，只改 query.py/answer.py + 本包测试）
核心：R1 的 `anaphora_new_content` 与 `elif explicit_record_entity and is_anaphora_field_followup(...)` 对政策/法规追问排除不完整，导致：
- C5 系列「那个海报的价格欺诈规定是什么/相关规定/适用的价格欺诈规定」（上文问位置或规格）→ 返回继承字段答案（错误）；
- C3「那个海报的档期物料要提前多少天提报需求」、C6「那个海报的审批流程是什么」→ 被压成 not_found，而单独问可从正文答 21 天/流程；
- C4 法规施行日期 → not_found「未在资料中找到…记录」（不实）。
要求：政策/法规题（`is_policy_question`/`is_regulation_question`）不得进入 `ANAPHORA_NEW_CONTENT` 或继承单字段分支；必要时重置继承的 field_role/实体，交回既有政策/法规/正文路径（T101 法规优先、T102 政策题不继承实体必须保持）。补 HTTP 用例覆盖「实体+指代+政策/法规」组合（C5 系列 + C3/C6）。
**保持**：B1（枚举后第2页→page=2）与 B2 点名项（规格→单字段；打印材质/陈列要求→not_found 35 字 0 泄露；位置/数量/价格单字段）不得回退；不得抢正文/政策/法规既有路径。
禁止：改 `conversations/`、`intent.py`、fixtures/b0/badcase/gate；skip/xfail/放宽断言；若必须改禁止文件→停手报 PM。

## 第三步：验证（全部实际执行，留证据）
按 `rework-R2.md` §4：本包 2 文件 / rag / integration / observability / 全量（0 failed/0 error；内存 <2GB 轮询；flake 隔离复跑 1 次）/ b0+badcase 对 `var/eval/runs/p0-b0`、`p0-badcase`（`case_diffs=0`、gate hard `[]`）/ regression 对 `17c0e63`（仅 RG006 fail→pass、RG005/RG007 不变、无新 hard 名）/ T101+T102 定向 + 新增组合用例。命令口径见 handoff §10 与验证证据 04；同一时间只跑一套 pytest。

## 第四步：交付
- 1 个新 commit：`p1/T105 R2 fix anaphora policy/regulation interception`；不 push/不 amend。
- `report.md` 追加「R2 返工」段：C3/C4/C5 系列/C6/C7 修复前后对照（文本长度/字段/关键值）、根因与最小改动、运行数字、残余；**更正 §6 把该组合记为「观察（不阻塞）」的错误**；证据 03/04 追加 R2 段（不新增文件）。
- 回复 ≤10 行摘要：commit、各场景修复前后证据、测试数字、偏离、风险。
