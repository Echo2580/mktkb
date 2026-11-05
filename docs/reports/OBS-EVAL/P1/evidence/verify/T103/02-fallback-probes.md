# T103 独立验收证据 02：overshoot 回落、真实检索与 trace 降级标记

方法：只把 `report.md` 当线索；以下全部为本人自建探针（`%TEMP%\t103_probe_*.py`），源库只读副本，零真实模型/embedding/rerank/OCR。

## A. 基线 vs 当前（产品 legacy 路径，`var/mktkb.sqlite3` 只读副本 + 回显替身）

- 基线 = `git archive 43b7976^`（父提交 `cbc40f8`）的独立源码树；当前 = 工作树。同一探针、同一 DB 副本、同一离线回显模型。
- 探针：`rag_qa_enabled=False`、`trace_enabled=True`、注入 `EchoGateway`（只回显本次证据）；`socket.connect` 守卫记录连接。
- 结果（13 题 = 8 目标 + 1 额外 overshoot + 4 普通题）：

```text
目标八题（Q25/Q26/Q29/Q30/Q34/Q35/Q37/Q38）+ N2（档期物料…）：
  baseline 全部 clarification「符合条件的记录过多，请缩小查询条件后重试。」/ 0 候选 / 0 来源
  current  全部 answer，0 候选，来源 8 条，无禁用文本
普通题 N1（滨江店海报位置）/N3（法规施行日期）/N4（海报数量）/N5（废止规定）：
  baseline 与 current 的 kind/text/sources 逐字相同（4/4），无 behavior diff
```

- 当前八题关键来源：Q25 {D03,D04,D05,D07,D09,E01}、Q26 {D03,D05,D09,X03}、Q29 {D03,D05,D09,E01,W02}、Q30 {D03,D05,E01,W06}、Q34 {D07}、Q35 {D08,E01}、Q37 {D03,D09,E01,P03,W02}、Q38 {D03,D05,D09,E01,P03,W02}；均含目标 D03/D05/D07/D08/D09。
- `non_loopback_network_attempts=[]`；`model_calls` 全部为本地 `EchoGateway`、purpose 仅 `answer`；`provider_identity={qa:None, ocr:None, model:EchoGateway, rag_qa_enabled:False}`。

## B. 真实语料下的检索取证（只读副本，`probe-retrieval`）

八题在 limit=20 与 limit=100 均 `truncated=True`（旧代码在此直接返回零候选）。逐题总命中：110/101/104/101/**281**/110/104/108。

最关键 Q34（目标 D07）：

```text
limit=100 total=281 truncated=true returned=100
首 100 条文档 = {D04:4, D09:1, E02:59, E03:33, 明码标价…:3}；target_in_first100 = []
逐词：扫描 total=7 (D07)、活动 total=17 (含 D07)、申请 total=11 (含 D07)、日期 total=264 (truncated)
并集 merged_units=118；既有 _rank_document_units top8 = D07×8；target_in_ranked=[D07]
```

- 证明 document 回落不是换皮：目标 D07 确实被 broad 首 100 挤出，逐词并集把它带回，并由既有正文排序取到。
- 其余七题目标本就在 broad 首 100，旧分支却整批丢弃；当前不再丢弃（来源含目标）。

## C. 强制 overshoot 的产品路径（合成语料，`probe-synthetic`）

- **document**：真实上传 `filler.docx`（10 单元，只含“物料”）与 `target.docx`（“领取活动物料前，请填写领用登记表…”）；包一层 `service._retrieve`，让 broad 多词请求（limit=20/100）都**排除 target** 且 `truncated=True`，单检索词仍走真实检索。
  - 结果：`kind=answer`；文本含「领取活动物料前，请填写领用登记表」；来源首条为 `target.docx`（`target_in_answer_sources=true`）。
  - broad 调用记录：`returned=11, target_present_before_force=true`（随后被强制排除），故 target 只可能由逐词回落带回。
  - trace：`{"record_overshoot_fallback":true,"record_overshoot_strategy":"document_term_union","record_overshoot_term_queries":4,"record_overshoot_total":11}`；`validate_required_spans==[]`；spans=`intent_parse,retrieve,retrieve,model_answer,answer_validate,commit`。
- **record**：真实上传 120 行/120 个物品组（同一门店），**不 monkeypatch**：
  - `kind=clarification`；文本「匹配到 120 条候选记录，超过单次检索上限 100 条；已列出前 8 条候选，请补充门店、物品或标识等条件缩小范围。」；`candidates=8`；无禁用文本。
  - trace：`{"record_overshoot_fallback":true,"record_overshoot_strategy":"record_candidates","record_overshoot_total":120}`；`validate_required_spans==[]`。
  - 模型调用 0（记录路在澄清前返回）。

## D. trace 标记与必需 span

- 当前产品探针中，9 个 overshoot 题全部有 `filter_decisions_json.record_overshoot_*`；4 个普通题 `filter_decisions_json={}`（未误标）。
- 所有探针与 `backend/tests/integration/test_p1_t103_record_fallback_http.py` 的 `validate_required_spans(...) == []` 均成立；`backend/tests/observability` 255 passed。
- 仅使用既有 `filter_decisions_json` 数据键，未新增 TraceRecord 字段/必需 span/outcome 枚举（`service.py:1465-1478`）。

## E. 对开发测试的独立质疑

- 开发集成用例的 `_force_truncated` 对每次 `_retrieve` 都返回同一个 target 单元（`..._http.py:118-144`），只能证明分支被进入，不能证明“target 不在首 100 时能被回落带回”。本证据 A/B/C 用真实检索与强制排除补齐了这一点。
