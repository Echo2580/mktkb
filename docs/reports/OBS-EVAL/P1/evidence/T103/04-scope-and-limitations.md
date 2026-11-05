# T103 证据 04：范围、口径变化与残余限制

## A. 改动文件（只含允许路径）

| 文件 | 说明 | `git diff --numstat` |
| --- | --- | --- |
| `backend/src/mktkb/conversations/service.py` | overshoot 回落 + 记录型诚实澄清 + trace 数据字段标记 | +87 / −5 |
| `frontend/src/features/chat/MessageCard.tsx` | 仅区分「本轮零候选」与「历史未保存」文案 | +5 / −0 |
| `backend/tests/unit/test_p1_t103_record_fallback.py` | 新增 4 条强制 truncated / trace 单测 | 新文件 |
| `backend/tests/integration/test_p1_t103_record_fallback_http.py` | 新增 2 条真实 HTTP + Trace 强制 truncated 用例 | 新文件 |
| `fixtures/evaluation/regression.jsonl` | 仅 RG004 一行 | +1 / −1 |
| `docs/reports/OBS-EVAL/P1/evidence/T103/` | 本目录 4 份证据 | 新文件 |

未改：业务 API 字段/响应结构、`rag/*`、检索服务、`intent.py`、其他后端模块、其他前端文件、b0/badcase、`docs/evaluation/gate_v0_1.json`、观察层 schema/必需 span/outcome 枚举、`.claude/handoffs` 其他文件。

## B. RG004 口径变化（非放宽）

- `expected_kind`：`clarification → no_answer`；`should_refuse` `false → true` 并补 `refusal_reason`；`forbidden_values` **原样保留** `["该历史消息未保存候选明细"]`。
- 理由：本地评测语料 `corpus/enterprise-20261101` 未收录 D09 物料领用通知（T107/RG004 notes 已声明），`run --mode local` 走 RAG 内核，实际输出诚实 `no_answer`（`资料“物料领用通知”未收录，未使用其它资料替代。`），修复前失败 checks 为 `kind_correct,refusal_unexpected`。按实现口径收口后 local PASS，且禁止值仍守住“不得声称历史未保存”。
- 产品 legacy 路径的“过多少 → 回落/命中量+缩小方式”不由 RG004 的本地 RAG 行承担，而由本包两条强制 truncated 集成用例与三条单测承担（证据 02 §C）。未把 RG004 改弱为只测文案：本地语料不可达 D09 是既有事实，强行要求 answer 会变成不可复现的断言。
- RG001–RG003 仍 PASS；RG005–RG007 仍 RED 且失败 check 集合逐条不变；gate hard failure 名称仍只有 RG006 的 `security_leak`。

## C. 前端范围

- 只改 `MessageCard.tsx` 的 clarification 零候选分支：`live`（本轮真实响应）显示“本次回答没有返回可选项；请按上方提示补充门店、物品或更具体的条件后重新提问。”；无 `live` 的历史加载仍显示“该历史消息未保存候选明细”。
- 未改 API 字段/类型、候选渲染、其他文案；文案统一留给 T106。

## D. OCR / 本地可达性

- b0 的 Q34/Q35/Q37/Q38 在离线评测中仍是 `skipped_requires_ocr`（本地不解析/不触发 OCR），本包未改 OCR。
- 证据 02 的产品离线探针使用 `var/mktkb.sqlite3`（历史本地库已含 D07–D09 的文本单元）验证的是**非 OCR 检索/回落分支**：强制 truncated 后能取到 D07/D08/D09。没有验证真实 OCR 解析链路，也不声称 OCR 质量。
- Q25/Q26 在 b0 local 的 value/source fail 源于 enterprise 语料不含 D03/D05，与本包回落无关；Q31 既有 local fail 未动。

## E. 残余风险

1. document 型回落把首 100 条 + 逐词命中的并集交给既有正文排序；宽泛词（如“物料”）仍可能把 E01 产品行带进 8 条证据，真实模型可能给出偏泛化的回答——本包只保证不再死路且证据包含目标文档，不保证回答排序最优。
2. 逐词回落最多增加 `len(terms)` 次（≤12）同入口检索，仅 overshoot 触发；大语料下会增加该异常路径延迟。
3. 记录型真实 overshoot 样本未在本地 40Q 中出现，只用合成强制 truncated 用例覆盖；真实大表记录题的 false-ambiguity 仍需后续语料验证。
4. trace 标记寄存在 `filter_decisions_json` 数据键（`record_overshoot_*`），未新增 schema 字段；若后续 gate 要求专用字段需另立任务。
