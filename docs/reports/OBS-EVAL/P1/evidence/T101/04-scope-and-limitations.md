# T101 证据 04：范围、PM 裁定 A 与 RG001 转正证明链

## A. 改动文件（PM 裁定 A 授权后）

| 文件 | 改动 |
| --- | --- |
| `backend/src/mktkb/conversations/intent.py` | 缺失字段判定拆明确词/泛化词；`_missing_field_hits` 法规优先 + 门店+物品语境；`MISSING_FIELD_GENERIC_WORDS` 复用 rag 词表 |
| `backend/src/mktkb/rag/query.py` | 新增 `REGULATION_NOUNS`/`CLAUSE_REF_PATTERN`/`GENERIC_FIELD_WORDS`/`is_regulation_question`/`field_roles_for_question`；`parse_query` 只改字段识别，检索/取数/embedding 未动 |
| `backend/src/mktkb/rag/answer.py` | `_document_fallback` + `_best_paragraph`：仅 `is_regulation_question` 的 offline 抽取整段引用；非法规题/默认路径逐字节不变 |
| `fixtures/evaluation/regression.jsonl` | 仅补全 RG001 `reference_answer`（发布日 2000-10-31 / 2001-11-07、施行日 2022-07-01 + 两项废止规定）；`expected_values`/`expected_sources`/`forbidden_*`/`expected_kind` 未动；RG002–RG007 未动 |
| `backend/tests/{unit,integration}/test_p1_t101_*.py` | 3 个测试文件（意图层 5 例、整段抽取 2 例、产品路径 4 例） |
| `docs/reports/OBS-EVAL/P1/evidence/T101/` | 本目录 4 份证据 |

- 未改：`service.py`、b0/badcase、`gate_v0_1.json`、账本/GO、业务 API 字段、检索取数/embedding；未新增依赖、未真实调用、未读 `.env`/Holdout、未切分支/未 push。

## B. 为什么需要裁定 A（两条独立原因）

1. **单句抽取**：`rag.answer._document_fallback` 的 offline 分支只取 `_best_sentence` 的**一句**。L02 `paragraph:39` 原文是同一段的两句：
   - “第二十七条 本规定自 2022年7月1日起施行。”
   - “2000年10月31日…《关于商品和服务实行明码标价的规定》、2001年11月7日…《禁止价格欺诈行为的规定》同时废止。”
   任何单句都缺 3 个 `expected_values` 中的至少一个。
2. **参考答数字白名单缺口**：`scorers._gold_number_keys` 只允许 `reference_answer`/`expected_values`/题干/业务日期里的数字；原 `reference_answer` 漏了原文发布日 2000-10-31 / 2001-11-07，逐字引用 p39 会多出 `31`、`11` → `value_no_fabricated` 判“编造”。

## C. 落地后的证明链（PM 裁定 A 第 3 条）

### ① RG001 local PASS

```text
$env:PYTHONPATH="backend/src"
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite regression --mode local --out <tmp>
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run <tmp>
```

```text
RG001 pass answer | fails: []
text: 根据资料，第二十七条 本规定自 2022年7月1日起施行。2000年10月31日…《关于商品和服务实行明码标价的规定》、
      2001年11月7日…《禁止价格欺诈行为的规定》同时废止。
citations: [('paragraph:38','L02'), ('paragraph:39','L02')]
```

- `value_hit`/`source_hit` 全中；`kind_correct`/`refusal_expected`/`pagination_*` 均通过。
- 其余 6 条仍 RED，失败 checks 与修复前逐条一致：RG002 `value_hit/source_hit/kind_correct`；RG003 加 `pagination_*`；RG004 `kind_correct/refusal_unexpected`；RG005/RG007 `kind_correct/refusal_expected`；RG006 `value_forbidden/kind_correct`。

### ② b0/badcase 零新增硬失败、case 级不变

| suite | 修复前 | 裁定 A 后 | 逐例 `(status, kind)` |
| --- | --- | --- | --- |
| b0 | pass 29 / fail 3 / skipped 8；hard `[]`；exit 3 | 同左 | **0 变化** |
| badcase | pass 9 / fail 4；hard `[]`；exit 3 | 同左 | **0 变化** |

### ③ 逐字引用 p39 → `value_no_fabricated` 通过（实测）

```text
RG001 reference_answer: 自 2022 年 7 月 1 日起施行；同时废止 2000 年 10 月 31 日…第 8 号发布的《关于商品和服务实行明码标价的规定》和 2001 年 11 月 7 日…第 15 号发布的《禁止价格欺诈行为的规定》。
allowed: ['1','10','11','15','2000','2001','2022','2026','28','31','7','8']
p39 extra numbers: []
p39 value hits: [True, True, True]
```

### ④ 非法规题路径逐字节不变（单测）

`backend/tests/unit/test_p1_t101_document_answer.py::test_non_regulation_question_keeps_single_sentence`：

```python
expected_sentence = _best_sentence(question, evidence)
assert answer.text == f"根据资料，{expected_sentence}"
assert P39 not in answer.text
```

法规题对照：`test_regulation_question_returns_whole_clause_paragraph` 断言整段（含两处废止规定）与 `paragraph:39` 引用。

## D. 残余风险

- `is_regulation_question` 以法规名词/条款引用/书名号标题判别，极少数“按规定…”的记录题会被当作正文题（只影响字段识别，不删数据、不编答案）；b0/badcase 53 题逐例对照 0 变化。
