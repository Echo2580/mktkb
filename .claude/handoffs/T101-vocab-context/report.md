wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T101 报告：ERR-03 词表语境与法规优先（P1 第 3 包）

## 1. 完成内容

- `backend/src/mktkb/conversations/intent.py`：`MISSING_FIELD_SYNONYMS` 拆出 `MISSING_FIELD_GENERIC_WORDS`（与 `rag.query.GENERIC_FIELD_WORDS` 同源单登记）；新增 `_missing_field_hits`：法规/制度题直接不判缺失字段，泛化「价格/销售」只在**门店+物品**（确有所指记录）且无更明确字段说法时才判缺字段；`parse_question` 与裸补槽的上一轮判定都走该函数。
- `backend/src/mktkb/rag/query.py`：新增 `REGULATION_NOUNS`/`CLAUSE_REF_PATTERN`/`GENERIC_FIELD_WORDS`/`is_regulation_question`/`field_roles_for_question`；`parse_query` 只替换字段识别入口（法规题、无实体语境的泛化「价格」不按 record 字段规划），检索/取数/embedding/分块未动。
- `backend/src/mktkb/rag/answer.py`（PM 裁定 A）：`_document_fallback` 增加法规题窄分支 + `_best_paragraph`（按问题词覆盖度选命中段落，整段逐字引用）；非法规题/默认路径逐字节不变。
- `fixtures/evaluation/regression.jsonl`（PM 裁定 A）：仅补全 RG001 `reference_answer`（补 2000-10-31 / 2001-11-07 发布日与 2022-07-01 施行日），`expected_values`/`expected_sources`/`forbidden_*`/`expected_kind` 未动，RG002–RG007 未动。
- 测试：`backend/tests/integration/test_p1_t101_vocab_context.py`（真实 HTTP 上传→worker→发布→提问，覆盖 6 道受影响题、E120 三值+来源、真实缺字段保持）；`backend/tests/unit/test_p1_t101_intent_vocab.py`（意图层语境/法规优先/词表边界）；`backend/tests/unit/test_p1_t101_document_answer.py`（法规题整段、非法规题单句逐字节不变）。
- 证据：`docs/reports/OBS-EVAL/P1/evidence/T101/`（01 修复前、02 修复后与门禁、03 测试、04 范围与裁定 A 证明链）。

## 2. 验收标准自证

1. 法规题不再提前截断：集成用例 `test_affected_questions_are_not_truncated_as_missing_fields` 对 E118/E120/E087/E095/E116/E122 断言 `missing_fields==[]` 且文本无「资料中未记录」；E120 `kind=answer`、文本含 `2022年7月1日` 与两项废止规定、来源含「明码标价」（`test_e120_answers_effective_date_and_repealed_rules`）。
2. 真实缺字段/价目表不变：`tests/integration/test_chat.py:401`「宣传海报的采购价格是多少？」仍 `not_found`（`test_g03_negative_not_found_without_fabrication` 通过）；b0 40 例与 badcase 13 例修复前后 `(status, outcome.kind)` 逐例相同（证据 02 §C）。
3. **回归转正**：RG001 local 由 `clarification`（MISSING_SLOT）→ `pass/answer`；`value_hit`/`source_hit` 全中，回答为 L02 第二十七条整段（`2022年7月1日` + 两项废止规定），引用 `paragraph:38/39`（证据 02）。
4. 门禁口径：b0/badcase `hard_failures` 修复前后均为 `[]`；regression 硬失败仍为 `['security_leak','pagination_contract']`（RG006/T105、RG003/T102），与修复前同一集合；RG002–RG007 仍 RED（未放宽）。
5. 测试：本包 1 次、`backend/tests/integration` 1 次、全量 `backend/tests` 1 次，结果见 §3。

## 3. 实际运行结果

- 本包：`cd backend; python -B -m pytest tests/unit/test_p1_t101_intent_vocab.py tests/unit/test_p1_t101_document_answer.py tests/integration/test_p1_t101_vocab_context.py -q` → **11 passed**。
- integration 目录：`python -B -m pytest tests/integration -q` → 首次 **349 passed**（287.92s）；裁定 A 后复跑 **348 passed + 1 failed（`test_g08_short_budget_cancels_inflight_model_call` 时序 flake，隔离复跑 1 passed）**，0 error。
- 全量：`python -B -m pytest tests -q` → **1613 passed, 1 failed（既有 flake `test_lifecycle.py::test_concurrent_publish_and_global_revision_cas[v05]`，隔离复跑该文件 2 passed，按 §11A 记录、不返工），0 error**（421.86s；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`，运行前 FreePhysicalMemory 3.0GB）。
- regression local 修复前/后：`7 fail` → `1 pass(RG001) + 6 fail`；RG001 `clarification→pass`，其余 6 条失败 checks 逐条不变；gate `scored=7/None`、`hard_failures=['security_leak','pagination_contract']`、`min_sample_missing` 均不变。
- b0：`pass 29 / fail 3 / skipped 8`、hard `[]` → 修复后完全一致；badcase：`pass 9 / fail 4`、hard `[]` → 完全一致（裁定 A 落地后复跑）。
- 命令均为 `PYTHONPATH=backend/src`、`.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run/gate`（offline，零真实调用）。
- commit：`p1/T101 intent vocab context + regulation priority`（sha 见交付回复）；改动 3 个源码文件 + 3 个测试文件 + RG001 参考答 + 4 份证据 + 本报告。

## 4. 偏离或未做

- 按 PM 裁定 A 落地两处最小改动：① `rag/answer.py::_document_fallback`（+`_best_paragraph`，`git diff --numstat` = +29/−1）仅对 `is_regulation_question` 的 offline 抽取整段引用，默认路径零改动（单测逐字节对照）；② RG001 `reference_answer` **数据补全（非放宽）**：依据 P0 设计 `reference_answer` 是人工参考答案、scorer 数字白名单派生自它，补的是原文发布日 2000-10-31 / 2001-11-07（原文逐字可查），`expected_values`/`expected_sources`/`forbidden_*`/`expected_kind` 均未动。
- 未向 `regression.jsonl` 追加种子：新增 local 种子同样绕开 intent.py，无法证明本包修复点（E116 修复前 local 已能答），故改用产品路径集成断言。
- 未改：`service.py` 截断分支/模板、b0/badcase、`gate_v0_1.json`、账本/GO、业务 API 字段、检索取数/embedding、`.env`/Holdout；未切分支/push；无新增生产依赖。

## 5. 风险

- `is_regulation_question` 依“法规名词/第 X 条/《…规定》标题”判别，极少数“按规定…”的记录题会被当作正文题（只影响字段识别，不删数据、不编答案）；b0/badcase 53 题逐例对照 0 变化。
