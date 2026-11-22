# T302 T301 样本对账

- 生成方式：按 `T301-isolated/scripts` 思路在 pytest `tmp_path` 重建 S01-S19（不在 T301 原目录重跑，不覆盖 T301 证据）。
- 正常链路：FastAPI 上传/发布/问答 + 受控替身模型（`EvidenceEchoGateway`，Mock）；故障缝为 S08 注入 `MODEL_UNAVAILABLE`、S09 注入 `KNOWLEDGE_REVISION_CHANGED`。
- 受控构造：S16/S19（running/expired 未提交中断）、S17/S18（午夜边界）直接写隔离库；S13/S14 用真实离线解析 worker。
- 覆盖与断言：`backend/tests/operations/test_reconciliation.py`（5 个测试函数），统计全部通过 `GET /api/v1/operations/*` 读取。
- 预期值来源：`T301-recomputation.md`，本次**未修改任何预期值**。

| 口径 | 预期值 | 实际值 | 一致性 | 证据（测试） |
| --- | --- | --- | --- | --- |
| 已完成问答量 | 13 | 13 | ✅ | `test_t301_reconciliation` |
| 六类分布 | answer 8 / clarification 1 / not_found 1 / conflict 1 / service_error 1 / knowledge_changed 1 | 同上，逐键相等 | ✅ | `test_t301_reconciliation` |
| 未提交中断单列 | 2（running / expired），不入六类 | 2；六类合计仍为 13 | ✅ | `test_t301_reconciliation`、`test_interrupted_is_listed_separately_not_in_distribution` |
| 非冲突持久引用行 | 13 | 13（未删除会话口径；库内原始 14 行含 S10 已删除会话 1 行） | ✅ | `test_t301_reference_rows_and_dimension_dedup` |
| 文档维去重对 | 6 | 6（各请求 `citation_count` 求和） | ✅ | `test_t301_reconciliation` |
| 版本维去重对 | 6 | 6（各请求详情 `citations` 条数求和） | ✅ | `test_t301_reference_rows_and_dimension_dedup` |
| 待审核版本 | 1 | 1（当前库存口径，窗口回溯不变） | ✅ | `test_t301_reconciliation`、`test_current_inventory_is_window_independent` |
| 生效资料 | 5 | 5 | ✅ | `test_t301_reconciliation` |
| 失败导入 | 1，error_code=`PARSE_INCOMPLETE` | 1，`PARSE_INCOMPLETE` | ✅ | `test_t301_failed_import_and_pending` |
| Trace 覆盖率 | 10/13，status=`partial`（纯重放 1 不计、关闭 1、未记录 2） | covered 10 / total 13 / `partial` | ✅ | `test_t301_reconciliation`、`test_t301_trace_coverage_details` |
| 午夜归属 | S17 → 2026-11-20；S18 → 2026-11-21 | 与预期一致，左闭右开不重不漏 | ✅ | `test_t301_midnight_attribution_and_deleted_exclusion` |
| 已删除会话 | S10 统计与明细双侧排除 | overview 与 requests 列表均无 S10；详情 404 | ✅ | `test_t301_midnight_attribution_and_deleted_exclusion`、`test_deleted_conversation_is_excluded_on_both_sides` |
| D5 冲突 | S05 持久引用行存在（2 行）；`final_citations`/`citation_count` 不含；按文档过滤命中且 `conflict_flag=true` | 2 行存在；citation_count 0、conflict_flag true；文档行 final 0 / related 1 | ✅ | `test_t301_reference_rows_and_dimension_dedup` |
| 统计 = 下钻 | overview 每个计数与对应条件下列表总数逐项相等 | 六类逐键相等；引用求和 6；文档 final 求和 6 | ✅ | `test_t301_reconciliation`、`test_overview_counts_equal_drilldown_totals` |

## 说明

1. **非冲突持久引用行 13 的口径**：库内 `message_sources` 非冲突原始行实际为 14（S10 已删除会话仍保留 1 行持久引用）。T301 的 13 对应“未删除会话”的统计可见行，与 overview/列表的已删除会话双侧排除一致；对账表同时断言原始 14 行、统计可见 13 行、删除会话 1 行。
2. **S05 冲突行**：D5 裁决后提交链路不修，持久行保留 2 行；查询侧 `kind='conflict'` 不入最终引用，来源改由 `conflicts` 块给出。
3. **S15 Trace 关闭**：覆盖率按“无普通执行 Trace”计；在关闭 Trace 的应用上详情 `trace.status=disabled`，在开启 Trace 的查询应用上只能给 `not_recorded`（不伪造覆盖率）。
4. 运行结果：`backend/tests/operations` 69 passed / 0 failed / 0 skipped，退出码 0（`pytest-operations.txt`）。
