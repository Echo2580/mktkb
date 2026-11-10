# T102 证据 04：范围、口径变化与残余风险

## 改动文件

| 文件 | 说明 | `git diff --numstat` |
| --- | --- | --- |
| `backend/src/mktkb/rag/query.py` | 未知区域词识别/澄清、政策题不继承、话题切换 reset、政策题字段/价格类型/枚举抑制 | +190 / −1 |
| `backend/tests/rag/test_p1_t102_state_inheritance.py` | 新增 18 条查询规划单测 | 新文件 |
| `backend/tests/integration/test_p1_t102_state_inheritance.py` | 新增 2 条产品 HTTP 多轮用例 | 新文件 |
| `fixtures/evaluation/regression.jsonl` | 仅 RG002/RG003 两行 | +2 / −2（仅 2 行变化） |

未改：`conversations/`（intent/service）、`rag/answer.py`、`rag/types.py`、b0/badcase、`gate_v0_1.json`、观察层、其他包文件、`.env`/Holdout。

## 为什么没有改 `answer.py`

根因是 `parse_query` 把上一轮 `store/item` 带进本轮 `state/filters`，导致 `_no_record_text()` 有实体可回显。T102 在 `query.py` 完成 reset 后，政策题不再进入带旧实体的记录拒答分支；产品 HTTP 集成用例断言答案不含「卓刀河店」「马克杯」，无需在答案层加“事后过滤”。保持 `answer.py` 零改动可避免影响 T101 的法规题整段抽取与默认路径。

## RG002/RG003 口径变化（非放宽）

- RG002：`expected_kind` `answer→clarification`；`expected_values`/`expected_sources` 清空（澄清不产生引用）；`forbidden_values` 保留 `店内外侧` 并新增 `滨江店`；`forbidden_sources` E11 row 7 保留。理由：PM 口径选择“未知区域词澄清”，不做区域→门店展开；修复前 local 实际为 `ambiguous`，不是 `answer`。
- RG003：所有期望值/来源/forbidden 均未动，仅更新 `notes`（修复后 local 由 `clarification MISSING_SLOT` 转为 `answer`）。
- 两条均在最终 local run PASS；RG001 仍 PASS；RG004–RG007 失败集合逐条不变。

## 产品层兼容点

`_rag_owns_turn()` 只把“带 identifier 过滤的记录型计划”交回 RAG 直答；RAG 的 clarification 分支原本不会到达产品层。T102 的未知区域澄清计划使用 `filters={'identifier': <区域词>}` 作为**既有入口的识别键**，并在 `answer_question` 的 clarification 分支提前返回——该值不进入检索、不写入 `state.identifier`、不持久化。产品层未改一行；集成用例证明 HTTP 结果确为 clarification。

## 残余风险 / 未做

1. **词表外 `*店` 紧跟上一轮门店**：本包只对「区域形态词」做 reset；`*店` 仍走既有 `UNKNOWN_STORE` 分支（无上一轮门店时拒答）。原因：`test_r5_plan_regressions::test_live_entry_mock_transport_is_labeled_and_counted` 锁定了“未知门店第二轮仍执行 query+rerank”的 P0 live 结构上界成本；改该行为会使既有预算回归失败。该残余风险已在 report §5 记录。
2. **区域形态启发式**：`城西区/城南片区` 可识别；`高度区间/华东大区/开发区/经销商跨区/城东店物料区` 已排除（单测覆盖）。极少数“以区域词开头的店内位置”仍可能被要求澄清；b0/badcase 53 题逐例零变化。
3. **多轮 runner**：`fixtures/evaluation/regression.jsonl` 的 `turns` 仍由 T109 执行；本包用 RAG 全量语料多轮脚本 + 产品 HTTP 集成用例证明。
