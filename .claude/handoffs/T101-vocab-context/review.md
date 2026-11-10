wb / cn:deepseek-v4.1-flash / reasoning_effort=max
# T101 独立验收 review（ERR-03 词表语境与法规优先）

**结论：PASS**。无 FAIL / BLOCKED / NOT-RUN；仅 1 项非阻断测试夹具瑕疵（见 §4）。

## 1. 环境与只读事实
- 分支 `p1/fix-retrieval`，HEAD `a7282b3`；评审写入前 `git status --short` 空（当前仅新增本 review 与 verify 证据）；未切分支/未 push/未 commit。
- 全量前实测 `FreePhysicalMemory=2.87GB`（≥2GB，未触发 NOT-RUN）；Python 3.12.7（`.venv`）。
- 所有 pytest 均先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，使用 `python -B -m pytest ... -q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`，工作目录项目根。
- `git show --stat a7282b3`：12 文件；源码仅 `conversations/intent.py`、`rag/query.py`、`rag/answer.py`，测试 3 个新文件，`regression.jsonl` 1 行，report + 4 份证据。均在允许路径。

## 2. 必须亲自复跑（全部 PASS）
1. **本包测试 PASS**：`test_p1_t101_intent_vocab.py`、`test_p1_t101_document_answer.py`、`test_p1_t101_vocab_context.py` + `test_chat.py::test_g03_negative_not_found_without_fabrication` → **12 passed in 7.58s**（3 个 T101 文件 11 例 + test_chat 1 例）。
2. **受影响目录 PASS**：`backend/tests/integration` → **349 passed in 277.73s**，0 failed/0 error。
3. **全量 PASS**：`backend/tests` → **1614 passed in 398.84s (0:06:38)**，0 failed/0 error。
4. **b0 / badcase local + gate PASS**：
   - b0：`pass 29 / fail 3 / skipped_requires_ocr 8`，gate `exit 3`、`hard_failures=[]`；失败 `{Q25,Q26,Q31}`。
   - badcase：`pass 9 / fail 4`，gate `exit 3`、`hard_failures=[]`；失败 `{N05,N06,N09,N11}`。
   - 与 P0 已记录基线 `var/eval/runs/p0-b0`、`p0-badcase` 逐例比较：`(status, outcome.kind)` 与失败 checks **diff 均为空**；gate hard_failures 同为 `[]`。该计数也与开发证据 01/02 的修复前/后表一致（仅作对照，不作为 PASS 依据）。
5. **regression local + gate PASS**：RG001 `pass/answer`，`value_hit` 3/3（missing `[]`）、`source_hit` 1/1、`value_forbidden`/`value_no_fabricated`/`kind_correct` 全 pass；回答为 L02 第二十七条整段，引用 `L02 paragraph:38/39`。RG002–RG007 仍 `fail`，失败 checks 与证据 01 记录及本次修复前独立复跑逐条一致（RG002 value_hit/source_hit/kind_correct；RG003 加 pagination_*；RG004 kind_correct/refusal_unexpected；RG005/RG007 kind_correct/refusal_expected；RG006 value_forbidden/kind_correct）。gate `exit 1`、`hard_failures=['security_leak','pagination_contract']`、`scored=7/None`。
   - **修复前对照（独立复跑）**：用 `git archive a7282b3^` 导出旧源码到 `%TEMP%` 运行同套 regression（旧数据集）：RG001 `fail/clarification`，失败 checks 为 value_hit/value_no_fabricated/source_hit/kind_correct；RG002–RG007 与当前失败 checks 逐条相同；旧 gate 同为 `['security_leak','pagination_contract']`。证明 RG001 是 RED→PASS，且门禁未放宽。
6. **只读核对 PASS**：`git diff --numstat a7282b3^ a7282b3` 与 `git show` 显示 `answer.py` +29/−1，`query.py` +66/−1，`intent.py` +45/−3；regression `1/1`。字段级比较：仅 RG001 `reference_answer` 变化；`expected_values`/`expected_sources`/`forbidden_*`/`expected_kind` 全部不变；RG002–RG007 无任何字段变化。

## 3. 重点证伪项
- **E118/E120/E116/E122/E087/E095 不再被 UNRECORDED_FIELD 截断：PASS**。integration `test_affected_questions_are_not_truncated_as_missing_fields` 对 6 题断言 `missing_fields==[]`、无「资料中未记录」、非 clarification，实测通过；`test_e120_answers_effective_date_and_repealed_rules` 实测 `kind=answer`，文本含 `2022年7月1日` 与两项废止规定，来源含「明码标价」。直接调 intent/plan 的 `%TEMP%` 探针：6 题 `missing_fields=()`、`mode=document`（E120 field_role=None；E118/E116/E122=None；E087/E095=price）。
- **窄分支真的窄：PASS**。`answer.py` diff 仅 import、`_document_fallback` 法规分支（`answer.py:617-622`）与 `_best_paragraph`（`:765`）；`_best_paragraph` 只在该分支调用。`%TEMP%` 探针：非法规题多句资料仍返回 `_best_sentence` 单句（`answer.text` 不等于整段；同一 P39 非法规题只返回「第二十七条 本规定自 2022年7月1日起施行。」），法规题返回整段（三值齐备）。`is_regulation_question` 对 b0/badcase 全部 53 题实测 **0 个 True**（含《…通知》类问题），未误判。
- **真实缺字段/价目表保持：PASS**。`test_chat.py::test_g03_negative_not_found_without_fabrication`（含 `test_chat.py:401`「宣传海报的采购价格是多少？」）实测通过；integration `test_purchase_price_without_item_context_still_not_found` 与 `test_generic_price_word_with_item_entity_still_not_found` 均 `not_found`、`missing_fields==['采购价格']`、无来源；b0/badcase 逐例 0 变化（含 price 题）。
- **不得改弱：PASS**。新测试无 `skip`/`xfail`/`pytest.mark`；commit 只新增 3 个测试文件，未删改既有测试断言；RG001 仅补全 `reference_answer`，`expected_values` 等未动；新增断言均为实际行为断言。
- **格式/范围：PASS**。`docs/reports/OBS-EVAL/P1/evidence/T101/` 恰 4 份；report 首行模型说明、五段、40 行；commit 文件均在允许路径；`service.py`、b0/badcase、`gate_v0_1.json`、账本/GO、检索取数/embedding 无改动。

## 4. 非阻断瑕疵
- `backend/tests/unit/test_p1_t101_document_answer.py:26` 的 P39 测试夹具把原文「第15号」写成「第9号」（真实语料 `corpus/enterprise-20261101/legal/…56号.docx` paragraph 39 为第15号）。不影响被验证的整段/单句分支逻辑，集成测试与 local regression 使用真实语料；建议后续修正夹具。
- report §3「本包 11 passed」对应 3 个 T101 文件；验收复跑额外加入 `test_chat` 节点后为 12 passed，非矛盾。
- report §3 记录 integration/全量各出现 1 次既有 flake；本次复跑均未复现（349 passed、1614 passed），按 §11A 不据此返工。

## 5. 证据
- 复跑证据：`docs/reports/OBS-EVAL/P1/evidence/verify/T101/` 下 4 份（pytest、eval run/gate、探针、范围核对）。
