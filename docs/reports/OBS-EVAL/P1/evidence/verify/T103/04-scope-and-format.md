# T103 独立验收证据 04：范围、前端、不误伤与格式

## A. 交付范围（`git show --stat 43b7976`）

```text
10 files changed, 633 insertions(+), 6 deletions(-)
backend/src/mktkb/conversations/service.py                  +87 / -5
frontend/src/features/chat/MessageCard.tsx                   +5 / -0
backend/tests/unit/test_p1_t103_record_fallback.py         +152 (新)
backend/tests/integration/test_p1_t103_record_fallback_http.py +191 (新)
fixtures/evaluation/regression.jsonl                          +1 / -1
docs/reports/OBS-EVAL/P1/evidence/T103/01..04               （4 份证据）
.claude/handoffs/T103-record-fallback/report.md             （41 行）
```

- 全部落在 handoff §4 允许路径；未触碰 b0/badcase、`docs/evaluation/gate_v0_1.json`、budget/GO/账本、`.env`、Holdout、其他代码。
- 新增测试无 `skip`/`xfail`；无既有测试被删除或断言被放宽（commit 仅 2 个新增测试文件）。`git show 43b7976 --format= | Select-String "skip|xfail|pytest.mark"` 仅命中 report/证据中的说明文字。

## B. 前端（`npm run typecheck` / `npm run build`）

- `frontend`：`npm run typecheck` exit 0（3.6s）；`npm run build` exit 0（vite 8.3.5，40 modules，255ms）。构建产物 `dist/` 被 gitignore，`git status --short` 仍为空。
- `MessageCard.tsx:135-141`：clarification 零候选时，`live`（本轮响应）显示「本次回答没有返回可选项…」；历史加载分支（`:141-144`）保留原文案。`ChatPage.tsx:183,193,343` 以 `message_id` 把 live 结果绑定到消息，历史消息无该条目，分叉可达。
- 未改 API 字段/响应结构：`backend/src/mktkb/conversations/schemas.py`、路由均无 diff；探针响应字段仍为 `kind/text/revision/sources/candidates/conflicts/missing_fields/pagination/error_code/retryable`。

## C. 不误伤

- b0/badcase 逐例 `(status,kind,reason,failed,path)` 对 P0 基线 `case_diffs=0`（证据 03 §A）。
- 独立 base vs current 探针：4 个普通题（N1 海报位置、N3 法规施行日期、N4 海报数量、N5 废止规定）的 `kind/text/sources` 逐字相同；仅 overshoot 题（8 目标 + N2）从 clarification 变为 answer（证据 02 §A）。
- `filter_decisions_json` 未破坏 trace：三套 gate 的 `trace_integrity` 均 pass；observability 255 passed；探针与集成用例 `validate_required_spans==[]`。

## D. 残余风险（非验收失败项）

1. document 回落把原本的零候选澄清变为 answer；回显探针显示 Q25/Q30/Q35 等 8 条证据会带入 E01/W06 等泛化正文，真实模型可能偏泛化（report §5 已声明；本包只保证不死路且目标来源在证据内）。
2. 逐词并集仍按 `limit=100` 截断；若某词命中 >100（Q34 的“日期”为 264），目标仍可能被挤出——Q34 靠“扫描”total=7 才召回 D07，换语料不保证。
3. record overshoot 的生产可达性未证明：产品默认 `rag_qa_enabled=True` 时记录型检索受 rag 候选约束，可能到不了 >100；本人用 `rag_qa_enabled=False` + 120 组合成数据证明分支，开发方也承认无真实记录型 overshoot 样本。
4. `regression.jsonl` RG004 的 `forbidden_values` 只有前端文案「该历史消息未保存候选明细」，未包含实际旧错文「符合条件的记录过多」；`expected_kind=no_answer` 仍能拦住旧 clarification，但 dataset 层禁止值偏弱。
5. 开发集成用例 `_force_truncated` 对每次 `_retrieve` 都返回同一 target（`..._http.py:118-144`），只证明分支进入；target 被首 100 挤出的场景由本人探针 B/C 补齐。

## E. NOT-RUN（按约束）

- 真实模型/embedding/rerank/OCR：禁止，未运行（探针 socket 非回环连接 0；provider 身份 qa=None/ocr=None/model=EchoGateway）。
- Holdout：禁止，未读。
- 真实 OCR 解析链路（D07–D09）：本地不可用；b0 Q34/Q35/Q37/Q38 仍 `skipped_requires_ocr`，产品探针只用 `var` 库已有文本验证非 OCR 检索/回落分支。
- T109 多轮 runner：不属本包。
