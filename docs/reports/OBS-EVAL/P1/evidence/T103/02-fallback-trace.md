# T103 证据 02：overshoot 回落、诚实澄清与 trace 降级标记

## A. 为什么是「逐词正文回落」（只读探测 `var/mktkb.sqlite3`，不写）

命令：`$env:PYTHONPATH="backend/src"; .venv\Scripts\python.exe -B %TEMP%\t103_probe.py`（只读 SQLite `mode=ro`，复用 `parse_question` + `retrieve`，不执行服务/模型）。

| case | 模式 | limit=100 total | truncated | 首 100 条内已含目标正文 | 逐词并集后的正文排序 |
| --- | --- | --- | --- | --- | --- |
| Q25 | document | 110 | True | D03/D05/D09 已在 | 不变（D03 2、D05 1、D09 1） |
| Q26 | document | 101 | True | D03/D05/D09 已在 | 不变（D03 5、D05 1、D09 1） |
| Q29 | document | 104 | True | D05/D09/W02 已在 | 不变（D05 2、D09 1、W02 1） |
| Q30 | document | 101 | True | D05/D03 已在 | 不变（D05 2、D03 2） |
| Q34 | document | 281 | True | **D07 不在首 100 条** | **D07 8/8**（词“扫描”total 7 召回小文档） |
| Q35 | document | 110 | True | D08 已在 | 不变（D08 2） |
| Q37 | document | 104 | True | D09/D03/W02 已在 | 不变（D09 1、D03 2、W02 1） |
| Q38 | document | 108 | True | D09/D03/D05 已在 | 不变（D09 1、D03 1、D05 1） |

结论：八题都是 document 模式（无门店/物品记录字段），`limit=20→100` 第二次仍 truncated 即被原分支直接放弃；把 100 条证据交给既有 `_rank_document_units` 已能回答 Q25/Q26/Q29/Q30/Q35/Q37/Q38。Q34 的期望文档 D07 被 281 条宽泛命中挤出首 100，故回落按单检索词再各取一次（仍走同一 `_retrieve`/limit=100），并集后由既有正文排序取 8 条，D07 8/8。未改检索/embedding/排序语义。

## B. 修复后产品行为（离线可复现，无真实模型）

命令：`$env:PYTHONPATH="backend/src"; $env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python.exe -B %TEMP%\t103_product_probe.py`。
脚本把 `var/mktkb.sqlite3` 用 SQLite backup 复制到 `%TEMP%`（源库只读），`rag_qa_enabled=False` 隔离 legacy 路径，注入确定性回显模型（只回显本次证据，不内置答案）。**真实模型/OCR/embedding/rerank 调用 0 次**；`model_calls=8` 全为本地替身。

| case | 修复前 kind / 候选 / 来源 | 修复后 kind / 候选 / 来源 | 修复后关键证据（截断） |
| --- | --- | --- | --- |
| Q25 | clarification / 0 / 0 | **answer / 0 / 8** | D09「填写领用登记表」、D03「填写登记表/负责人确认」 |
| Q26 | clarification / 0 / 0 | **answer / 0 / 8** | D05「登记归还日期」、D03「2.3/2.4」 |
| Q29 | clarification / 0 / 0 | **answer / 0 / 8** | D05「两店负责人确认」 |
| Q30 | clarification / 0 / 0 | **answer / 0 / 8** | D05「核对数量与完好情况」 |
| Q34 | clarification / 0 / 0 | **answer / 0 / 8** | D07「活动日期:2026-11-05」 |
| Q35 | clarification / 0 / 0 | **answer / 0 / 8** | D08「物料通道保持畅通」 |
| Q37 | clarification / 0 / 0 | **answer / 0 / 8** | D09「先填写领用登记表」 |
| Q38 | clarification / 0 / 0 | **answer / 0 / 8** | D09「负责人确认」 |

- 八个目标题均不再出现「符合条件的记录过多」；Q37 正是 ERR-04 原题，候选/来源由真实短事务提交。
- 记录型 overshoot 的诚实澄清（真实命中量 + 候选 + 缩小方式）由强制 truncated 集成用例证明；本轮 40Q 八题均为 document 模式，没有真实记录型 overshoot 样本。

## C. trace 降级标记（数据字段，不改 schema/必需 span/outcome 枚举）

实现：`backend/src/mktkb/conversations/service.py:1465` 写既有 `filter_decisions_json`（tracer finish 保留既有键并并入条件属性）：

```json
{"record_overshoot_fallback":true,"record_overshoot_strategy":"document_term_union","record_overshoot_term_queries":5,"record_overshoot_total":150}
```

- 强制 truncated 集成用例在真实 HTTP + Trace 中读取该字段并断言；同时 `validate_required_spans(...) == []`：`backend/tests/integration/test_p1_t103_record_fallback_http.py:168-171`（document）与 `:188-191`（record）。
- 单元用例断言同一数据字段与 outcome 不变：`backend/tests/unit/test_p1_t103_record_fallback.py:123-127`。
- 未新增 TraceRecord 字段、未改必需 Span 表、未改 outcome 枚举；`backend/tests/observability` 全绿（见证据 03）。
