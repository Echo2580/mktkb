wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T103 报告：D4 记录路回落语义检索（ERR-04）

## 1. 完成内容
- `backend/src/mktkb/conversations/service.py`：`limit=20→100` 仍 truncated 时不再返回零候选死路。
  - document 型：按单检索词复用既有 `_retrieve`（同入口、同 limit=100、同 revision）扩大证据面，`_rank_document_units` 仍按问题词排序取正文（`:1499`、调用 `:2089`/`:2130`）。
  - record 型：返回真实 `total_candidates` + `_candidate_view` 候选 + 缩小方式，不再声称“记录过多”却无候选（`:1481`、`:2088`/`:2129`）。
  - trace：只写既有 `filter_decisions_json` 数据键 `record_overshoot_fallback/total/strategy/term_queries`（`:1465`）；未改 schema/必需 span/outcome 枚举。
- `frontend/src/features/chat/MessageCard.tsx:135-141`：仅区分本轮 `live` 零候选（“本次回答没有返回可选项…”）与历史加载无候选（保留“该历史消息未保存候选明细”）；未改 API 契约/其他文案。
- 测试：新增 unit 4 条 + integration 2 条（强制 truncated → 回落/诚实澄清 + trace 标记）。
- `fixtures/evaluation/regression.jsonl`：仅 RG004 收口（本地语料无 D09，按实现口径 `no_answer` + `should_refuse=true`，保留 forbidden「该历史消息未保存候选明细」）。
- 证据 4 份：`docs/reports/OBS-EVAL/P1/evidence/T103/01..04`。

## 2. 验收标准自证
1. **无解澄清消失**：八题修复前均 clarification/0 候选/0 来源（证据 01 §A）；修复后离线产品探针均 answer/8 来源且含目标证据（证据 02 §B）。
2. **回落可证明**：强制 truncated 单测 `backend/tests/unit/test_p1_t103_record_fallback.py:39`；真实 HTTP+Trace 集成 `backend/tests/integration/test_p1_t103_record_fallback_http.py:153`（document）与 `:174`（record）。
3. **trace 标记**：集成断言 `filter_decisions_json.record_overshoot_*` 且 `validate_required_spans==[]`（`..._http.py:168-171`、`:188-191`）；`backend/tests/observability` 255 passed。
4. **文案诚实**：本轮零候选与历史缺失分叉（`MessageCard.tsx:135-141`）；`npm run typecheck`/`build` 均 exit 0（证据 03）。
5. **RG004**：local `pass`（`kind=no_answer`，`forbidden_values` 未删）；RG001–RG003 仍 PASS，RG005–RG007 仍 RED 且失败集不变（证据 03）。
6. **回归**：本包 6 passed；`tests/unit` 306、`tests/integration` 353、全量 `tests` 1640 passed，0 failed/0 error。

## 3. 实际运行结果
- 本包：`pytest tests/unit/test_p1_t103_record_fallback.py tests/integration/test_p1_t103_record_fallback_http.py -q` → **6 passed**，3.31s。
- 目录：`tests/unit` **306 passed**（7.36s）；`tests/integration` **353 passed**（281.12s）；`tests/observability` **255 passed**（49.98s）。
- 全量：`pytest tests -q` → **1640 passed**，403.66s，0 failed/0 error；全量前 `FreePhysicalMemory=2.61 GB`；无 flake。
- 前端：`npm run typecheck` exit 0；`npm run build` exit 0（vite 276ms）。
- b0：prefix `pass29/fail3/skipped8`，hard `[]` → 修复后同；逐例 `(status,kind,failed)` **0 差异**（Q31 既有 fail 未动）。
- badcase：prefix `pass9/fail4`，hard `[]` → 修复后同；**0 差异**。
- regression：prefix `pass3/fail4`，hard `['security_leak']` → 修复后 `pass4/fail3`，hard `['security_leak']`；仅 RG004 fail→pass，其余逐条不变。
- product 离线探针：Q25/Q26/Q29/Q30/Q34/Q35/Q37/Q38 修复前 clarification/0/0 → 修复后 **answer/0/8**；真实模型调用 0（`model_calls=8` 为本地回显替身）。
- commit：`p1/T103 record-path fallback + honest clarification`（sha 见交付回复）；改动 3 文件 +87/−5（service）、+5（MessageCard）、1 行 RG004；新增 2 测试文件 + 4 证据 + 本报告。

## 4. 偏离或未做
- RG004 的 `expected_kind` 由 `clarification` 改为 `no_answer`：本地 enterprise 语料无 D09，RAG local 实测诚实 no_answer；产品 legacy 回落断言由本包强制 truncated 用例承担（证据 04 §B）。
- 40Q 八题均为 document 模式；record 型真实 overshoot 无本地样本，只用合成 truncated 覆盖（证据 04 §E）。
- OCR：b0 的 Q34/Q35/Q37/Q38 仍 `skipped_requires_ocr`；产品探针验证的是 var 库已有 D07–D09 文本后的检索/回落分支，未验证真实 OCR 解析链路。
- 前端仅改零候选误归因一处；文案统一留给 T106。未改其他模块/API/b0/badcase/gate/其他前端文件。

## 5. 风险
- 逐词并集只扩大候选、不改排序；宽泛“物料”仍可能把 E01 产品行带入 8 条证据，回答可能偏泛化（不再死路、目标文档在证据内）；逐词回落最多增加 ≤12 次同入口检索，仅 overshoot 触发。
