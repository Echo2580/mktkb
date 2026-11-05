# T003d 返工 R1（PM 返工单，2026-11-05）

> 依据：`.claude/handoffs/T003d-paths/review.md`（独立验收，隔离副本验收 `b811f9f`）。
> 验收结论：**FAIL，仅 §5.11 一个 MEDIUM 子项**；§5.1–§5.10、授权修改最小性、提交边界、证据卫生、测试非空转、全量回归均 PASS。
> 返工上限：本轮为第 1 轮（R1）。

## 1. 唯一不通过项

**现象**：legacy 解析级早退（未执行 retrieve）后，在 **commit 阶段** revision 复核升级为 `knowledge_changed` 时，实际 Span = `{intent_parse, commit}`；而 `observability/contracts.py` 的 `legacy + knowledge_changed` 行要求 `{intent_parse, retrieve, commit}`，`validate_required_spans` 返回缺失 `['retrieve']`。
**证据**：`docs/reports/OBS-EVAL/P0/evidence/verify/T003d/06-independent-probe.txt`（验收方独立探针，模拟并发发布）。
**为什么算 FAIL**：handoff §5.11 要求"按实际执行、不伪造 Span"；契约行与真实早退形态冲突。

## 2. 修复要求（窄、不改业务逻辑）

**采用验收方建议的 reason-aware 拆分（不降低原约束强度）**：

1. 为 **commit 阶段** revision 升级定义单独的稳定 trace reason（如 `KNOWLEDGE_CHANGED_AT_COMMIT`），与检索后升级的 `KNOWLEDGE_CHANGED` 区分；只影响 trace 的 `reason` 字段，不改变业务分支、响应结构与异常语义。
2. `contracts.py`：`legacy + knowledge_changed` 行保持 `{intent_parse, retrieve, commit}` 为默认；仅当 `reason=KNOWLEDGE_CHANGED_AT_COMMIT`（未执行 retrieve 的 commit 升级形态）时降为 `{intent_parse, commit}`。`validate_required_spans` 按 `record.reason` 应用。
3. 同步更新 `docs/evaluation/trace_schema_v0_1.md` §6.1.2 的 legacy 例外/补充表（两种 knowledge_changed 形态与 reason 取值）。
4. 补回归测试：模拟"解析级早退后 commit 阶段 revision 升级"（不执行 retrieve）→ `outcome=knowledge_changed`、`reason=KNOWLEDGE_CHANGED_AT_COMMIT`、Span `{intent_parse, commit}`、`validate_required_spans == []`；另保留检索阶段 knowledge_changed 用例（要求 retrieve，validate==[]）。
5. 顺手修正验收 LOW 项：`evidence/T003d/10-deliverables-sha256.txt` 补列 `06-test-middleware.diff`；证据/报告按提速策略 C 精简（≤3 份关键证据、只更新相关小节）。

## 3. 验证与提交

- 只跑：`test_contracts.py` + `test_paths_e2e.py` + `test_rag_spans.py`（定向）+ 一次全量（A 策略）；命令输出存 `evidence/T003d/`（覆盖/追加，不堆砌）。
- 全量目标：1266 passed / 0 failed / 0 error（本返工不新增用例时仍为 1266；若新增少量用例则 1266+新增数）。
- `b811f9f` 未 push，允许 `--amend` 保持单 commit；也可追加一个小 commit（二选一，报告中说明）。
- 不 push；不改 `_index.md`、PM handoff/prompts、账本/GO。

## 4. 返工后验收

由全新上下文验收者做**定向复验**（提速 A）：只复核本返工单 §1 的修复 + 受影响回归（`test_contracts/test_paths_e2e/test_rag_spans`）+ 一次全量，不重跑旧基线全量；其余 §5.1–5.10 沿用上一轮 PASS 结论（引用 review.md）。
