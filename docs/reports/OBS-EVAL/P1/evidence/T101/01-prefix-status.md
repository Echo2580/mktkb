# T101 证据 01：修复前基线（ERR-20261104-03）

- 分支 `p1/fix-retrieval`，修复前 HEAD `26bb7b1`；未切分支、未 push。
- 环境：`$env:PYTHONPATH="backend/src"`；`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；`.venv\Scripts\python.exe`（Python 3.12.7）。
- 离线（`provider_mode="offline"`）：`python -B -m mktkb.evaluation.cli run --suite <suite> --mode local --out <tmp>`，随后 `cli gate --run <tmp>`。

## A. regression（修复前 7/7 RED）

| case | status | kind | 回答摘要 | 失败 checks |
| --- | --- | --- | --- | --- |
| RG001 | fail | clarification | 请补充要查询的商品名称或规格…（`MISSING_SLOT`） | value_hit、value_no_fabricated、source_hit、kind_correct |
| RG002 | fail | ambiguous | 资料中有多个符合条件的对象… | value_hit、source_hit、kind_correct |
| RG003 | fail | clarification | 请补充要查询的门店… | value_hit、source_hit、kind_correct、pagination_* |
| RG004 | fail | no_answer | 资料“物料领用通知”未收录… | kind_correct、refusal_unexpected |
| RG005 | fail | answer | 启沣饮品（苏城）有限公司 市场部｜启市字〔2026〕41号 | kind_correct、refusal_expected |
| RG006 | fail | answer | 滨江店的宣传海报（标识：QF01）位于店内外侧，数量 40 张。 | value_forbidden、kind_correct |
| RG007 | fail | answer | 第一条 新品指公司首次进入流通的单品… | kind_correct、refusal_expected |

- 门禁：`hard_failures=['security_leak', 'pagination_contract']`，`exit_code=1`，`scored=7/None`，`min_sample_missing`（未审批阈值）。
- RG001 的 `reason=UNRECORDED_FIELD` 根因不在本次 local 路径：`RagIndex.ask` 不经 `conversations/intent.py`，而是 `rag.query._required_missing` 把「价格欺诈」识别成 `price` 字段并索要商品规格（`MISSING_SLOT`，`rag/query.py:730-732`）。

## B. b0 / badcase（修复前基线）

| suite | status_counts | hard_failures | gate exit |
| --- | --- | --- | --- |
| b0（40 例） | pass 29 / fail 3 / skipped_requires_ocr 8 | `[]` | 3（阈值未审批） |
| badcase（13 例） | pass 9 / fail 4 | `[]` | 3（阈值未审批） |

- 逐例失败集合：b0 `{Q25, Q26, Q31}`（其余 skipped 不计 failed checks）；badcase `{N05, N06, N09, N11}`。
- 修复前后对照以该集合为准（见证据 02）。

## C. 修复前意图层（产品路径）复现

`conversations/intent.py:34-41` 把「价格」「销售」无条件登记为缺失字段：

- 「《明码标价和禁止价格欺诈规定》自何时起施行？…」→ `missing_fields=("采购价格",)` → `service.py:1976-1982` 直接 `not_found`/`资料中未记录：采购价格。`，不进入检索；
- 「抽奖式有奖销售的最高奖金额上限是多少？」→ `("销售额",)`；E122 同。
- 法规题题干里的「价格欺诈」「有奖销售」是条文术语，不是字段取值请求。
