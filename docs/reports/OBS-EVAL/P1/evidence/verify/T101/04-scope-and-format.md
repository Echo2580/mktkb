# T101 独立核对证据 04：范围、数据与格式

## A. commit / 改动范围

```text
git rev-parse --abbrev-ref HEAD  -> p1/fix-retrieval
git log -1 --oneline             -> a7282b3 p1/T101 intent vocab context + regulation priority
git status --short               -> （空）
git show --stat a7282b3          -> 12 files changed, 801 insertions(+), 6 deletions(-)
```

文件清单（均在本包允许路径）：

```text
.claude/handoffs/T101-vocab-context/report.md
backend/src/mktkb/conversations/intent.py            +45/-3
backend/src/mktkb/rag/answer.py                      +29/-1
backend/src/mktkb/rag/query.py                       +66/-1
backend/tests/integration/test_p1_t101_vocab_context.py
backend/tests/unit/test_p1_t101_document_answer.py
backend/tests/unit/test_p1_t101_intent_vocab.py
docs/reports/OBS-EVAL/P1/evidence/T101/01-prefix-status.md
docs/reports/OBS-EVAL/P1/evidence/T101/02-post-status.md
docs/reports/OBS-EVAL/P1/evidence/T101/03-test-runs.md
docs/reports/OBS-EVAL/P1/evidence/T101/04-scope-and-limitations.md
fixtures/evaluation/regression.jsonl                  +1/-1
```

未改：`service.py`、b0/badcase 数据集、`gate_v0_1.json`、账本/GO、业务 API 字段、检索取数/embedding。

## B. regression.jsonl 字段级 diff

对 `a7282b3^` 与 `a7282b3` 的 7 条 JSON 逐字段比较：

```text
RG001 changed keys: ['reference_answer']
  expected_values same: True
  expected_sources same: True
  forbidden_values same: True
  forbidden_sources same: True
  expected_kind same: True
  expected_values subset of new reference: True
RG002 changed keys: []
RG003 changed keys: []
RG004 changed keys: []
RG005 changed keys: []
RG006 changed keys: []
RG007 changed keys: []
```

`reference_answer` 旧值已含「2000 年计委令第 8 号」「2001 年计委令第 15 号」及 2022-07-01；新值仅补原文发布日 2000-10-31 / 2001-11-07（真实语料 paragraph 39 逐字可查）与「同时废止」，属 PM 裁定 A 的数据补全，不是改期望值。

## C. 未改弱 / 断言真实性

- `git show --name-only a7282b3 -- backend/tests` 仅 3 个新测试文件；既有测试文件未改，无删除断言。
- 新测试文件无 `skip` / `xfail` / `pytest.mark`（`Select-String` 空）。
- 新测试断言覆盖：意图层法规优先/泛化词语境/明确字段保持；整段抽取与非法规单句；真实产品路径 6 题不截断、E120 三值+来源、真实缺字段 not_found。
- `backend/tests/integration/test_chat.py:401` 的「宣传海报的采购价格是多少？」用例由 `test_g03_negative_not_found_without_fabrication` 实际执行并通过。

## D. 报告 / 证据格式

```text
report.md 行数: 40（≤80）
report.md 首行: wb / cn:deepseek-v4.1-flash / reasoning_effort=max
report.md 段落: 1 完成内容 / 2 验收标准自证 / 3 实际运行结果 / 4 偏离或未做 / 5 风险
docs/reports/OBS-EVAL/P1/evidence/T101/: 4 份（≤4）
```

## E. 非阻断瑕疵

- `backend/tests/unit/test_p1_t101_document_answer.py:26` 的测试夹具 P39 将「第15号」写成「第9号」；该测试只验证整段/单句分支，集成测试与 local regression 使用真实语料第15号，故不影响验收结论，建议修正。
- report §3 的「本包 11 passed」是 3 个 T101 测试文件；验收复跑加入 `test_chat` g03 节点后为 12 passed，非矛盾。
- 开发方记录的 2 个既有 flake 在本次 integration/全量复跑中均未出现；按 §11A 不返工。
