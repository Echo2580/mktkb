# T105 证据 02：实现与行为矩阵

## A. 代码改动（保留前序 + 本轮修正）

- `backend/src/mktkb/rag/query.py`（+100）：
  - `is_anaphora_field_followup`（:323）：答案层判定“只继承字段的指代追问”；`全部/列出/下一页/第 N 页` 不算。
  - `_anaphora_residual_terms`（:774）：去掉实体/别名/标识后仍剩下的检索词；为空才进入 T105 分支。本轮补滤“前面/刚才/上述/这家…”这类非停用指代词（`ANAPHORA_WORDS` 内的完整 token），避免它们被当成新内容。
  - `_anaphora_field_text`（:792）：无可继承字段时的澄清文案（“请问要查询<对象>的哪项信息？可指定位置、数量、规格、价格等。”）。
  - `parse_query` 分支（:1272-1318）：`anaphora and field_role is None and not is_policy_question` 且残词为空时：
    - 无实体/无字段 → `ANAPHORA_NO_ENTITY` 澄清（“请说明您指的是哪个物品、门店或哪份资料。”）；
    - 有实体但可继承字段数 ≠ 1 → `ANAPHORA_NO_FIELD` 澄清；
    - 恰好 1 个记录字段 → 继承该 `field_role`，并置 `state.enumerate=True` 作为产品层 `_rag_owns_turn` 的既有入口。
  - 澄清计划沿用 T102 的 `_RAG_OWNED_CLARIFICATION_FILTER`（`filters={'identifier': marker}`）让产品层交回 RAG 直答；未改 `conversations/`。
- `backend/src/mktkb/rag/answer.py`（+13/−1，仅在 `_answer_record` :230-234）：
  - 若 `plan.enumerate` 且 `is_anaphora_field_followup(...)`，复制计划并把 `enumerate` 置 False 后再渲染，走单字段答案路径；否则会进 `_enumerate_answer` 输出整条记录。
  - 不改变任何既有枚举/分页计划的渲染，不改正文/政策答案路径。
- 本轮修正（相对前序工作树）：
  1. 删除未使用的 `is_anaphora_question`（死代码）；
  2. `_anaphora_residual_terms` 增加纯指代词过滤（使“刚才那个呢/前面那个呢”也进入 T105 分支，而非落到 legacy 后 not_found）；
  3. `is_anaphora_field_followup` 增加 `_PAGE_NUMBER` 守卫（“该海报第2页”不被误判为单字段追问）；
  4. 新增 2 条测试：多字段上文 → 澄清；HTTP“刚才那个呢” → 只答继承字段。

## B. 行为矩阵（local/offline，产品与 RAG 层一致）

| 上文 | 本轮问题 | 结果 |
| --- | --- | --- |
| 无 | 那个海报呢 | `clarification` / `ANAPHORA_NO_FIELD`，只问“哪项信息”，无 12 字段值 |
| 无实体 | 那个呢 | `clarification` / `ANAPHORA_NO_ENTITY` |
| 问位置 | 那个海报呢、刚才那个呢 | `answer`，仅位置（C区2号货架第一层），无规格/价格/数量/标识 |
| 问数量 | 那个海报呢 | `answer`，仅数量（20） |
| 问参考供价 | 那个海报呢 | `answer`，仅价格（2.6 元） |
| 问规格型号 | 那个海报呢 | `answer`，仅规格（A2 铜版纸 157g） |
| 问两个字段（位置+数量） | 那个海报呢 | `clarification` / `ANAPHORA_NO_FIELD`（没有唯一可继承字段） |
| 显式列出来/全部/第 N 页 | 把那个海报的位置列出来 / 第2页 | 保持枚举/分页，不进入单字段渲染 |
| 政策/流程题 | 那这个流程要提前几天提报 | `is_policy_question` 守卫，不进入 T105 分支（T102 口径） |

## C. 与 T101/T102 的边界

- 新分支位于 `UNKNOWN_REGION` 之后、filters/mode 计算之前；仅在 `field_role is None` 时生效，显式字段追问（电话呢/数量呢）路径不变。
- `is_policy_question` 为真时完全绕过；`conversations/`、`intent.py` 未改一行。
- `answer.py` 只在 `_answer_record` 入口按“指代 + 单字段 + 非显式枚举”翻转渲染开关，`_answer_document`/`_multi_field_answer`/`_enumerate_answer` 未改。
