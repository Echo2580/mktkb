# T102 证据 02：修复后状态与门禁对照

- 分支 `p1/fix-retrieval`；工作区代码为 T102 交付版本（query.py +190/−1）。
- 命令均在仓库根目录：`PYTHONPATH=backend/src`、`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`、`python -B -m mktkb.evaluation.cli run/gate`；零真实调用。

## A. regression local（最终）

- run_id `regression-local-20261105T172225153287Z-776d02c5`；`status_counts={'pass':3,'fail':4}`；scored 7。
- 通过：RG001、**RG002（clarification）**、**RG003（answer）**；RG004–RG007 失败集合与修复前一致。
- gate：exit 1，`hard_failures=['security_leak']`。
  - 修复前为 `['security_leak','pagination_contract']`；`pagination_contract` 是 RG003 旧 MISSING_SLOT/enumerate 的症状，本包修复后消失（收紧，不是放宽）。
- RG002 实际文本：`资料中没有收录“城西区”这个门店/区域，请补充准确的门店名称后再查询。`
  - 不含 `滨江店`、不含 `店内外侧`；无来源；`kind=clarification`。
- RG003 实际文本：`根据资料，档期物料须提前 21 天提报。`
  - 含 `21`；不含 `卓刀河店`、`马克杯`；来源 W02（`paragraph:15`）。

## B. b0 / badcase（最终）

| suite | run_id | status_counts | gate | 与修复前逐例对照 |
| --- | --- | --- | --- | --- |
| b0 | `b0-local-20261105T172155900415Z-3879686c` | pass 29 / fail 3 / skipped_requires_ocr 8 | exit 3；`hard_failures=[]` | `case diffs=0`、`trace diffs=0`（path/outcome/reason 全同） |
| badcase | `badcase-local-20261105T172200749885Z-236fda64` | pass 9 / fail 4 | exit 3；`hard_failures=[]` | `case diffs=0`、`trace diffs=0` |

对照方法：基线 worktree（HEAD 9fa8101）与当前工作区各跑一次 local run，按 `(case_id,status,kind,reason,path)` 与 trace 表 `(case_id,path,outcome_kind,reason,status)` 逐例比较；仅 trace_id/time 随机字段不同。

## C. 全量语料上的多轮复现（RAG 直答，非 runner 单轮）

在 `corpus/enterprise-20261101` 全量 49 份语料索引上，用同一 conversation 依次 `RagIndex.ask`：

```json
{
  "RG002": [
    {"q": "滨江店的宣传海报在哪里？", "kind": "answer", "text": "根据资料，滨江店的宣传海报的位置：店内外侧。"},
    {"q": "城西区的宣传海报在哪？", "kind": "clarification", "reason": "UNKNOWN_REGION",
     "text": "资料中没有收录“城西区”这个门店/区域，请补充准确的门店名称后再查询。"}
  ],
  "RG003": [
    {"q": "卓刀河店的马克杯（标识：QF21）放在哪里？", "kind": "answer", "text": "根据资料，卓刀河店的马克杯的位置：赠品暂存架。"},
    {"q": "档期物料要提前多少天提报需求？给出所有内容", "kind": "answer", "text": "根据资料，档期物料须提前 21 天提报。"}
  ]
}
```

- RG002 第二轮不再出现 `滨江店`/`店内外侧`；RG003 第二轮含 `21 天` 且无 `卓刀河店`/`马克杯`。
- 多轮完整 runner 复现仍依赖 T109；本包以上述 RAG 多轮 + 产品 HTTP 集成用例双重证明。

## D. 产品路径多轮（HTTP）

`backend/tests/integration/test_p1_t102_state_inheritance.py`（上传→worker→发布→提问，模型为证据回显替身）：

- ERR-01：先“城东店的宣传海报在哪里？”→ `answer` + `B区1号货架第二层`；再“城西区的宣传海报在哪？”→ `clarification`，文本无 `城东店`、无 `B区1号货架第二层`。
- ERR-02：先“卓刀河店的马克杯（标识：QF21）放在哪里？”→ `not_found`；再“档期物料要提前多少天提报需求？给出所有内容”→ `answer`，含 `21`，无 `卓刀河店`/`马克杯`。
- 结果：`2 passed`（完整套件结果见证据 03）。
