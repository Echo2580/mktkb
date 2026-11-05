# T102 证据 01：修复前基线（HEAD 9fa8101，detached worktree）

- 分支 `p1/fix-retrieval`；基线 worktree：`git worktree add --detach $TEMP\t102-baseline HEAD`，未切换/新建分支、未 push。
- 所有命令零真实调用：`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`、`PYTHONPATH=<基线>\backend\src`、`python -B -m mktkb.evaluation.cli ...`。
- 业务日期 `2026-10-28`；b0/badcase/regression 数据集与冻结语料未改。

## A. b0 / badcase / regression local（修复前）

| suite | run_id | status_counts | 分数/门禁 |
| --- | --- | --- | --- |
| b0 | `b0-local-20261105T165222428332Z-40b35d15` | pass 29 / fail 3 / skipped_requires_ocr 8 | scored 32/32；`hard_failures=[]`；gate exit 3（min_sample 缺阈值） |
| badcase | `badcase-local-20261105T165227571526Z-1b6dfea7` | pass 9 / fail 4 | scored 13/13；`hard_failures=[]`；gate exit 3 |
| regression | `regression-local-20261105T165325669652Z-5c129b9a` | fail 7 | `hard_failures=['security_leak','pagination_contract']`；gate exit 1 |

regression 逐条（修复前 expected_kind / actual kind）：

| case | actual kind | 失败 checks | 备注 |
| --- | --- | --- | --- |
| RG001 | answer | — | 已 PASS（T101） |
| RG002 | ambiguous | value_hit, source_hit, kind_correct | 单轮“城西区”无门店槽 → 多实体歧义，不是澄清 |
| RG003 | clarification | value_hit, source_hit, kind_correct, pagination_* | “档期特价”价格类型 + 无实体 → MISSING_SLOT |
| RG004–RG007 | no_answer / answer | 与 T107 基线一致 | 本包未触碰 |

## B. 本包产品路径集成用例（修复前 RED）

命令：

```text
cd backend
..\.venv\Scripts\python.exe -B -m pytest tests/integration/test_p1_t102_state_inheritance.py -q
```

结果：**2 failed**（新增用例，修复前按预期 RED）。

- ERR-01 第二轮：`kind=answer`，文本 `城东店的宣传海报的位置：B区1号货架第二层；门店：城东店；物品：宣传海报。`
  —— 静默沿用上一轮城东店，未澄清。
- ERR-02 第二轮：`kind=not_found`，文本 `未在资料中找到“卓刀河店”的“马克杯”记录（该实体没有匹配记录），不能据此编造数值。`
  —— 原样回显用户本轮未提及的实体，且答案不含 21 天。

## C. 修复前代码事实

- `parse_query` 对“城西区…”：`filters={'store':'城东店','item':'宣传海报'}`、`state.store='城东店'`（`backend/src/mktkb/rag/query.py` 旧 `_new_state` 继承路径）。
- 对“档期物料…”（上一轮 `store=卓刀河店,item=马克杯,identifier=QF21`）：`filters={'store':'卓刀河店','item':'马克杯','identifier':'QF21'}`、`enumerate=True`。
