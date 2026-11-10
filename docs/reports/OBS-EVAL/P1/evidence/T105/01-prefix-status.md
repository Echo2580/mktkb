# T105 证据 01：起始状态与基线（接续轮）

- 时间：2026-11-06 08:0x–08:4x（Asia/Shanghai）；分支 `p1/fix-retrieval`，本轮起点/基线 worktree 均为 `17c0e63`（`chore(p1): expand resume prompt…`，仅文档提交，未改代码）。
- 工作树承接前序失败 subagent 的未提交成果：`backend/src/mktkb/rag/query.py`（+100）、`answer.py`（+13/−1）、新增 `backend/tests/rag/test_p1_t105_anaphora_field.py`、`backend/tests/integration/test_p1_t105_anaphora_field.py`；本轮保留并修正，未重做。
- 所有评测/测试均为 offline：`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`、`python -B`；零真实模型 / embedding / rerank / OCR 调用；未读 `.env` / Holdout。
- 基线行为（`git worktree add --detach $TEMP\t105-baseline 17c0e63`，运行后已清理）：
  - `regression` local：`regression-local-20261106T001846178302Z-e584b08e`，pass 4 / fail 3，gate exit 1，hard `['security_leak']`。
  - RG006 实际 `kind=answer`，文本 `根据资料，滨江店的宣传海报（标识：QF01）位于店内外侧，数量 40 张。`（W11 正文摘要，答了未问的标识/位置/数量），失败 checks `value_forbidden,kind_correct`。
  - 直接 RAG 层探针（前序 `.claude/handoffs/_scratch/T105/`）：无上文 `那个海报呢` 在修复前返回 W11/记录摘要；有上文且 `field_role=None` 时走整条记录渲染。
- P0 基线（`var/eval/runs/p0-b0`、`p0-badcase`，修复前可比口径）：b0 pass 29 / fail 3 / skipped_requires_ocr 8、hard `[]`；badcase pass 9 / fail 4、hard `[]`。
- 本轮修改前 `backend/tests/rag` 已含前序 8 条 T105 单测；PM 快速复跑记录为 13 passed（8 单测 + 5 HTTP 多轮，本轮新增 2 条后为 15）。
