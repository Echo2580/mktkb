wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T102 报告：组 A 状态继承（ERR-01/ERR-02/D5，P1 第 4 包）

## 1. 完成内容

- `backend/src/mktkb/rag/query.py`（+190/−1）：新增 `POLICY_WORDS`/`is_policy_question`（:93、:309）、`_unknown_region_tokens`（:656）；`parse_query` 增加未知区域识别与 reset（:943、:1193）、政策题无实体时的价格类型/字段/枚举抑制（:960、:1009）、话题切换 reset（:1018）。
- 未知区域词（城西区、城南片区）按 PM 口径**澄清**，不做区域→门店展开；澄清计划同时清空 `state.store/stores`，不再继承上一轮门店。区域词识别排除「高度区间/华东大区/开发区/经销商跨区/城东店物料区」等。
- 政策/制度/流程题（无显式实体、无记录字段）不继承上一轮 store/item/identifier；「给所有内容」不再把政策事实题送进按标签排序的枚举分支。
- `backend/tests/rag/test_p1_t102_state_inheritance.py`（18 条单测）、`backend/tests/integration/test_p1_t102_state_inheritance.py`（2 条 HTTP 多轮）。
- `fixtures/evaluation/regression.jsonl`：仅 RG002（`expected_kind=clarification`、清空 values/sources、forbidden 增补 `滨江店`）与 RG003（仅 notes）两行。
- `rag/answer.py` 未改：reset 后旧实体不再进入 `_no_record_text()`，集成用例已证明不回显，无需答案层事后过滤。

## 2. 验收标准自证

1. ERR-01：`backend/tests/integration/test_p1_t102_state_inheritance.py::test_err01_unknown_region_does_not_reuse_previous_store` 断言第二轮 `kind=clarification`、无 `城东店`/`B区1号货架第二层`；全量语料多轮脚本输出见证据 02 §C。
2. ERR-02：同文件 `test_err02_policy_question_does_not_inherit_entities` 断言 `kind=answer`、含 `21`、无 `卓刀河店`/`马克杯`；RG003 local 实际文本「根据资料，档期物料须提前 21 天提报。」
3. 误伤防护：`tests/rag` 326 passed（含 `test_query_state.py` 话题切换/分页）、`tests/integration` 351 passed（含 `test_s2b_intent_semantics.py` 裸门店/换物品、`test_chat.py:440` g04 上下文）。
4. trace 不破坏：`tests/observability` 255 passed；b0/badcase 修复前后 `case diffs=0`、`trace diffs=0`（path/outcome/reason 全同）。
5. regression：RG001/RG002/RG003 PASS；RG004–RG007 失败集合逐条不变；gate `hard_failures` 由 `['security_leak','pagination_contract']` 收紧为 `['security_leak']`。
6. 回归与预算：本包 20 passed；rag 326；integration 351；全量 1634 passed（详见 §3）。

## 3. 实际运行结果

- 本包：`cd backend; ..\.venv\Scripts\python.exe -B -m pytest tests/rag/test_p1_t102_state_inheritance.py tests/integration/test_p1_t102_state_inheritance.py -q` → **20 passed**（5.17s）。
- `tests/rag`：`cd backend; ..\.venv\Scripts\python.exe -B -m pytest tests/rag -q` → **326 passed**（22.53s）。
- `tests/integration`：首次 350 passed + 1 failed（既有 flake `test_g08_short_budget_cancels_inflight_model_call`，0.2s 预算时序；隔离复跑 **1 passed**）；最终整套重跑 **351 passed**（289.20s）。
- `tests/observability`：**255 passed**（20.49s）。
- 全量 `backend/tests`：**1634 passed**（438.56s，0 failed/0 error；全量前 `FreePhysicalMemory=2.63GB`）。
- b0：修复前 pass29/fail3/skipped8、hard `[]` → 修复后**同数同例**，run `b0-local-20261105T172155900415Z-3879686c`。
- badcase：修复前 pass9/fail4、hard `[]` → 修复后**同数同例**，run `badcase-local-20261105T172200749885Z-236fda64`。
- regression：修复前 7 fail（RG002 ambiguous、RG003 clarification，gate hard 含 `pagination_contract`）→ 修复后 3 pass（RG001/RG002/RG003）+ 4 fail；run `regression-local-20261105T172225153287Z-776d02c5`，gate hard `['security_leak']`。
- 命令均 `PYTHONPATH=backend/src`、`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`、`python -B -m mktkb.evaluation.cli run/gate`（offline，零真实调用）。
- 证据：`docs/reports/OBS-EVAL/P1/evidence/T102/01-prefix-status.md`～`04-scope-and-limitations.md`（4 份）。
- commit：`p1/T102 state inheritance + topic-switch reset`（sha 见交付回复）；改动 2 个源码/数据文件 + 2 个测试文件 + 4 份证据 + 本报告。

## 4. 偏离或未做

- **RG002 口径变化**：`expected_kind` `answer→clarification`、清空 `expected_values/expected_sources`、`forbidden_values` 增补 `滨江店`（保留 `店内外侧` 与 E11 row 7 forbidden source）。这是 PM 澄清口径的落地，不是放宽；修复前 local 实际 kind 是 `ambiguous`，原 `answer` 本来不可达。
- **`_rag_owns_turn` 兼容点**：产品层只把带 identifier 过滤的记录型计划交回 RAG；未知区域澄清计划用 `filters={'identifier': <区域词>}` 作为识别键（`query.py:207`、:1204），在 clarification 分支提前返回，不检索、不写入 `state.identifier`、不持久化；未改 `conversations/` 一行。
- **未改 `answer.py`**：理由见 §1；T101 法规题整段抽取与默认路径零影响。
- **词表外 `*店` 紧跟上一轮门店**：本包未改其 reset，仍走既有 `UNKNOWN_STORE` 分支（无上一轮门店时拒答）。原因：`test_r5_plan_regressions::test_live_entry_mock_transport_is_labeled_and_counted` 锁定该轮仍执行 query+rerank 的 P0 live 成本上界；改动会使既有预算回归失败。
- 未改：`conversations/`、b0/badcase、`gate_v0_1.json`、观察层、其他包文件、`.env`/Holdout；未切分支/push/amend；无新增生产依赖。

## 5. 风险

- 区域词是形态启发式，极少数“以区域词开头的店内位置”（如「物料区的海报」）可能被要求澄清；b0/badcase 53 题逐例零变化、rag 326 条回归通过，风险限定在未收录区域/位置措辞。
