# T102 独立验收证据 04：范围、格式与只读核对

- 分支 `p1/fix-retrieval`（未切换/新建），HEAD `85d9ffc`（单 commit `p1/T102 state inheritance + topic-switch reset`）；未 push/commit/amend。
- 本人未修改任何交付物；`git status --short` = clean；只写入本目录 4 份证据 + `review.md`。

## A. commit 范围（`git show --stat 85d9ffc`）

```text
 .claude/handoffs/T102-state-inheritance/report.md          | 47 +
 backend/src/mktkb/rag/query.py                             | 191 +++++++++++++++++++-
 backend/tests/integration/test_p1_t102_state_inheritance.py| 113 +
 backend/tests/rag/test_p1_t102_state_inheritance.py         | 144 +
 docs/reports/OBS-EVAL/P1/evidence/T102/01..04               | 4 files
 fixtures/evaluation/regression.jsonl                        | 4 +-
 9 files changed, 648 insertions(+), 3 deletions(-)
```

- `query.py` = **+190 / −1**；`answer.py`、`rag/types.py`、`conversations/`、`qa/` 均零改动：

```text
git diff --name-only 9fa8101 85d9ffc -- backend/src/mktkb/rag/answer.py \
  backend/src/mktkb/conversations backend/src/mktkb/qa
→ (empty)
```

## B. regression.jsonl 只读核对

```text
git show 85d9ffc -- fixtures/evaluation/regression.jsonl
→ 仅 RG002 一行（expected_kind answer→clarification；values/sources 清空；forbidden +滨江店）
→ 仅 RG003 一行（仅 notes）
→ RG001、RG004–RG007 字节未动
```

RG002 的 `forbidden_values` 保留 `店内外侧`、新增 `滨江店`，`forbidden_sources` E11 row 7 保留；非放宽。

## C. 无 skip/xfail/删断言

- 两个新测试文件无 `pytest.mark.skip/xfail`；18 单测 + 2 集成 = 20 passed。
- 既有测试文件在 85d9ffc 中零修改（`git show --name-status` 仅新增 2 个测试文件）。
- 全量 1634 passed、0 skipped（pytest 汇总无 skip 行）。

## D. 代码最小性（只读审阅）

- `POLICY_WORDS`/`is_policy_question` 被 `field_roles_for_question`、价格类型抑制、枚举抑制、topic_switch 四处使用；`_unknown_region_tokens` 被 `parse_query` 与单测使用；`_BAD_REGION_*`/`_REGION_LEADINS`/`_REGION_FOLLOWERS` 均参与判定，未发现死代码或重复函数。
- 唯一耦合点 `_RAG_OWNED_CLARIFICATION_FILTER="identifier"`（query.py:207、:1204）为复用 `_rag_owns_turn` 既有入口；证据 03 §C4 已核实不检索、不持久化；`conversations/service.py` 未改。
- `is_policy_question` 复用 `is_regulation_question`，不新造法规判别。

## E. report / 证据格式

- `report.md` 首行 = `wb / cn:deepseek-v4.1-flash / reasoning_effort=max`；五段（§1 完成内容、§2 自证、§3 运行结果、§4 偏离/未做、§5 风险）；47 行（≤80）。
- 交付证据 `docs/reports/OBS-EVAL/P1/evidence/T102/` 4 份（≤4）；本次验收证据 4 份（≤4）。
- 未读 `.env`/Holdout；未改 budget/GO/账本/b0/badcase/gate_v0_1；未真实调用模型/embedding/rerank/OCR。

## F. 未做 / 限制

- regression 的 `turns` 多轮仍由 T109 执行；本包以独立 HTTP 多轮 + RAG 多轮证明（证据 03）。
- 区域词是形态启发式（残余风险见证据 03 §C）；未知 `*店` 的 RAG 直答继承仍存在（产品层已拒答）。
- b0/badcase/regression 的 trace 对照为本人在 `cases.jsonl`/`traces.sqlite3` 上的字段投影，不覆盖 span 内部属性（时间/耗时等易变值）。
