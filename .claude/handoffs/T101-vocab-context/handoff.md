# T101 交接单：ERR-03 词表语境与法规优先（P1 第 3 包）

> 基线：分支 `p1/fix-retrieval`（自 `main@083eaef`；T100/T107 已收口）。前置：T107 已提供 `regression.jsonl`（RG001 对应本包）。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 1. 目标（一句话）
修掉"缺失字段词表无条件劫持"：法规/制度题不再因题干含「价格/销售」被判成"采购价格/销售额缺失"而提前截断；真实缺字段问题（如明确问采购价格）与价目表取数行为保持不变。

## 2. 背景（ERR-03，依据 `错误记录-20261104.md` §ERR-20261104-03）
- 现象：问「《明码标价和禁止价格欺诈规定》何时施行？废止了哪两个规定？」→「资料中未记录：采购价格。」，不进入检索。
- 根因：`backend/src/mktkb/conversations/intent.py:34-41` 的 `MISSING_FIELD_SYNONYMS["采购价格"]` 含「价格」；与 `backend/src/mktkb/rag/query.py:35` 的 `FIELD_WORDS["price"]` 含「价格」双登记冲突。
- 提前截断点：`backend/src/mktkb/conversations/service.py:1976-1982`（`not plan.requested_fields and plan.missing_fields` → `UNRECORDED_FIELD`），`intent.py:417` 产出该 missing_fields。
- 标准答案（已发布资料逐字可查，`corpus/enterprise-20261101/legal/…56号.docx`）：施行日期 **2022-07-01**；废止 **2000 年计委令第 8 号《关于商品和服务实行明码标价的规定》** 与 **2001 年计委令第 15 号《禁止价格欺诈行为的规定》**。
- 影响面（`corpus/enterprise-20261101/questions.json` 155 题中约 8 题被命中）：E118/E120/E087/E095（「价格」）；E116/E122（「销售」命中「销售额」）；E145/E146（「负责人」）。修复需带**语境约束**，且法规/制度类问题优先级高于缺失字段判定。

## 3. 输入（先读这些，只看指定范围）
1. `.claude\handoffs\2026-11-04-p1-design.md` §3（T101 行）。
2. `错误记录-20261104.md` §二 ERR-20261104-03（现象/根因/影响面表/修复方向）。
3. `backend/src/mktkb/conversations/intent.py`（重点 `:26-41` 词表、`:364-523` 意图组装、`:417` `_field_hits`）。
4. `backend/src/mktkb/conversations/service.py:1960-1990`（提前截断分支）与 `:1371-1410`（缺字段说明模板，只读理解，不改）。
5. `backend/src/mktkb/rag/query.py:30-40`（`FIELD_WORDS["price"]`，价目表取数侧，只读对照）。
6. 现有测试：`backend/tests/integration/test_s2b_intent_semantics.py`（b_fixture 集成夹具写法）、`backend/tests/integration/test_chat.py:401`（**必须保持**：「宣传海报的采购价格是多少？」→ `not_found`）。
7. `fixtures/evaluation/regression.jsonl` 的 RG001（本包要把它从 RED 转 PASS）；`backend/tests/evaluation/test_regression_suite.py`（fixture 格式参考）。

## 4. 交付物（只准写这些路径）
1. `backend/src/mktkb/conversations/intent.py`（主改）；仅在确有必要时改 `backend/src/mktkb/rag/query.py` 的词表一致性（**不得改取数/检索逻辑**）。
   - **PM 裁定（2026-11-05 23:1x，开发现场提出，允许 A）**：允许在 `backend/src/mktkb/rag/answer.py` 的 `_document_fallback` 增加**极窄**分支——仅当 `is_regulation_question(...)` 且 offline 抽取路径命中时，返回命中子句所在的**完整段落**（而非单句）；非法规题/默认路径**零改动**。理由：RG001/E120 的三值（2022-07-01 + 两项废止规定）在单句抽取下无法同时命中，改弱断言或降级 RG001 均违反"不放宽"纪律。附加要求：① 新分支有单元测试（法规题段落返回 + 非法规题仍单句，逐字节不变）；② report §4 单列该偏离（文件/函数/diff 行数）；③ 附 b0/badcase 修复前后 local run 的 hard_failures 与 case 级 pass/fail 对照，证明零新增硬失败。
2. `backend/tests/` 下新增/最小修改本包测试（建议 `backend/tests/integration/test_p1_t101_vocab_context.py` 或就近）——用集成夹具覆盖 ERR-03 影响面 8 题与"采购价格仍 not_found"。
3. `fixtures/evaluation/regression.jsonl`：按需**追加** T101 相关种子（如 E118/E087/E095 各 1 条，`source_err_id=ERR-20261104-03`、`suite=regression`、`split=dev`、`label_version=regression-p1-2026-11-05`）。**RG001 必须由 RED 转 PASS**：PM 裁定允许把 RG001 的 `reference_answer` 补全为含发布日 2000-10-31 / 2001-11-07 / 施行日 2022-07-01 的完整人工参考答案（**禁止**改 `expected_values`/`expected_sources`/`forbidden_*`/`expected_kind`）；RG002–RG007 一律不动。详见 §9。
4. `docs/reports/OBS-EVAL/P1/evidence/T101/`（≤4 份证据）
5. `.claude/handoffs/T101-vocab-context/report.md`（五段，≤80 行）
6. 1 个 commit（见 §7）

**不要写**：`service.py` 的截断分支/模板（本包不改服务层行为）、其他包文件、b0/badcase、gate_v0_1、docs/evidence、var、账本/GO、`.claude/handoffs` 其他文件。

## 5. 允许 / 禁止
- 允许：改 intent 词表与匹配逻辑（语境约束、法规/制度优先、同义词单一来源）；加/改本包测试；向 regression.jsonl 追加种子；只读读语料/索引/测试。
- 禁止：改业务 API 字段结构、改 service 层模板/截断分支、改检索取数逻辑或 embedding 行为、改 b0/badcase/冻结 fixtures、放宽既有断言、`skip`/`xfail`、真实模型调用、读 `.env`/Holdout、切分支/push、新增生产依赖。

## 6. 验收标准（逐条可判定）
1. **法规题不再被提前截断**：E120（及 E118/E087/E095/E116/E122 代表性用例）经集成夹具走产品路径后，不再返回 `UNRECORDED_FIELD`/「资料中未记录：采购价格」；E120 能检索并给出施行日期 2022-07-01 与两项废止规定（或结构化 facts 命中这些值；以集成断言证明）。
2. **真实缺字段与价目表行为不变**：`test_chat.py:401`「宣传海报的采购价格是多少？」仍 `not_found`；b0 中价格类题目仍按价目表取数（b0 local run 中 price stratum 行为与修复前一致，无新增 fail）。
3. **回归转正**：RG001 在 `mode=local` 下由 RED 转 PASS；新增的 T101 种子同样 PASS（证据含修复前/后状态对照表）。
4. **门禁口径（PM 澄清）**：b0、badcase 两套 local gate **无新增硬失败**（与修复前基线 hard_failures 集合对比）；regression 套件只要求 RG001 与本包新增种子通过，其余 6 条仍 RED 属预期（不得为此放宽断言/改数据集）。
5. **回归测试**：本包测试 + `backend/tests/integration` 受影响目录 + 全量 `backend/tests` 0 failed / 0 error（§11A：各 1 次；全量前看 `FreePhysicalMemory`，当前 2.8GB；<2GB 标 NOT-RUN 并说明；遇既有 flake 按记录隔离复跑 1 次）。
6. 证据 ≤4 份、report 五段、1 commit、只改允许文件。

## 7. 提交要求
- 分支 `p1/fix-retrieval`；1 个 commit，消息：`p1/T101 intent vocab context + regulation priority`；不 push/不 amend 历史。
- 提交前 `git status --short` 只含允许路径；report 记录 commit 信息（sha 写交付回复即可）。

## 8. 报告格式（五段，≤80 行）
1) 完成内容；2) 验收标准自证（每条 ≤2 行，带命令/`文件:行`）；3) 实际运行结果（本包 / integration 目录 / 全量 + b0/badcase/regression 修复前后对照 + commit sha + stat）；4) 偏离或未做；5) 风险（一句话）。

## 9. PM 裁定记录（2026-11-05 23:2x，开发方第二次现场提出）

**裁定：A（授权两处最小改动）**。背景：只改 intent/query 时 RG001 在 local 下不可达——① RG001 `reference_answer` 漏了原文发布日（2000-10-31 / 2001-11-07），scorer 数值白名单由 reference/expected/question 派生，逐字引用原文会多出 31/11 被判"编造"；② offline `_document_fallback` 单句抽取无法同时命中 3 个 `expected_values`。

授权范围与条件：
1. `rag/answer.py` `_document_fallback`：沿用 §4 第一次裁定的窄分支（仅 `is_regulation_question` + offline 命中时返回命中子句所在完整段落；非法规题/默认路径逐字节不变；需单测）。
2. `fixtures/evaluation/regression.jsonl` RG001：允许把 `reference_answer` **补全**为含发布日 2000-10-31 / 2001-11-07、施行日 2022-07-01 与两项废止规定的完整人工参考答案；**禁止**改 `expected_values`/`expected_sources`/`forbidden_*`/`expected_kind`，**禁止**动 RG002–RG007。报告 §4 单列"数据补全（非放宽）"并写依据（P0 设计：`reference_answer` 是人工参考答案；scorer 数值白名单派生自它）。
3. 证明链：① RG001 local **PASS**（value_hit + source_hit 全中）；② b0/badcase 修复前后 `hard_failures` 集合与 case 级 pass/fail 一致（零新增硬失败，否则回滚 answer.py）；③ 证据给出"逐字引用 p39 完整两句 → `value_no_fabricated` 通过"的实测；④ regression 其余 6 条仍 RED。
4. 收口：本包只允许改 `conversations/intent.py`、必要的 `rag/query.py` 词表、`rag/answer.py` 窄分支、本包测试、`fixtures/evaluation/regression.jsonl`（仅 RG001 `reference_answer` + 可选 T101 追加种子）；1 个 commit（未 push 可 amend，不得制造第二个同义 commit）。

**拒绝**：B（RG001 记"不可达"）与 C（改 `expected_values`）——前者使验收标准 3 落空，后者属放宽断言。
