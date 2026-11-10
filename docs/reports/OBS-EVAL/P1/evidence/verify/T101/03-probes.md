# T101 独立探针证据 03：窄分支、意图/规划、法规判别

- 探针文件：`%TEMP%\probe_t101.py`（未写入仓库）；`PYTHONPATH=backend/src`；只读调用 `_document_fallback` / `_best_sentence` / `_best_paragraph` 与 `intent.parse_question` / `rag.query.parse_query`。
- 证据 A 的夹具含两条多句资料；证据 B/C 使用真实 L02 paragraph 39 文本（第15号）。

## A. 非法规题多句资料 → 仍单句

```text
question=滨江店的宣传海报在哪里？
is_regulation_question=False
best_sentence='滨江店的宣传海报位于入口堆头旁，数量 40 张。'
best_paragraph='滨江店的宣传海报位于入口堆头旁，数量 40 张。城西店的宣传海报位于店内货架，数量 20 张。'
answer.text='根据资料，滨江店的宣传海报位于入口堆头旁，数量 40 张。'
equals whole paragraph? False
```

## B. 法规题 → 整段（三值齐备）

```text
question=《明码标价和禁止价格欺诈规定》自何时起施行？同时废止了哪两个规定？
is_regulation_question=True
best_paragraph='第二十七条 本规定自 2022年7月1日起施行。2000年10月31日…第8号发布的《关于商品和服务实行明码标价的规定》、2001年11月7日…第15号发布的《禁止价格欺诈行为的规定》同时废止。'
answer.text='根据资料，' + 上述整段
contains 3 values: True
```

## C. 同一 P39 上的非法规题 → 仍单句（非整段）

```text
question=2022年3月22日通过了什么？
is_regulation_question=False
answer.text='根据资料，第二十七条 本规定自 2022年7月1日起施行。'
P39 whole? False
```

## D. 六道受影响题的 intent/plan（空实体词典）

```text
E118 missing=() requested=() mode=document field_role=None
E120 missing=() requested=() mode=document field_role=None
E087 missing=() requested=() mode=document field_role=price
E095 missing=() requested=() mode=document field_role=price
E116 missing=() requested=() mode=document field_role=None
E122 missing=() requested=() mode=document field_role=None
```

对照真实缺字段：

```text
宣传海报的采购价格是多少？ missing=('采购价格',) field_role=price
滨江店柠檬茶 500ml 的价格是多少？ missing=('采购价格',) field_role=price
```

## E. `is_regulation_question` 对 b0/badcase 全量问题

```text
b0 count 40 regulation_true 0
badcase count 13 regulation_true 0
```

即 53 题（含 `《…通知》` 类）均未被误判为法规题。

## F. 只读源码定位

- `backend/src/mktkb/rag/answer.py:617-622`：`_document_fallback` 仅在 `is_regulation_question(plan.question)` 时替换为 `_best_paragraph`；默认路径未改。
- `backend/src/mktkb/rag/answer.py:765`：`_best_paragraph` 定义，仅被上述分支调用。
- `backend/src/mktkb/rag/query.py:239`：`is_regulation_question`；`:253` `field_roles_for_question`；`:839` `parse_query` 的字段识别入口。
- `backend/src/mktkb/conversations/intent.py:294`：`_missing_field_hits`；`:453` `parse_question` 调用；`:50` `MISSING_FIELD_GENERIC_WORDS`。
- 新增单测夹具瑕疵：`backend/tests/unit/test_p1_t101_document_answer.py:26` 将第15号写成第9号；不影响分支行为，真实语料/集成/local 使用第15号。
