# T101 证据 02：修复后状态与门禁对照

- 修复点：
  1. `conversations/intent.py`：缺失字段词表拆成明确字段名 + 泛化词；`_missing_field_hits` 让法规/制度题直接返回空，泛化「价格/销售」只有在**同时出现门店与物品**（确有所指记录）时才判缺字段；
  2. `rag/query.py`：新增 `is_regulation_question` / `field_roles_for_question`，法规题与无实体语境的泛化「价格」不再按 record 字段规划（检索/取数逻辑未改），词表由 `GENERIC_FIELD_WORDS` 单一来源供两层共用；
  3. `rag/answer.py`（PM 裁定 A）：`_document_fallback` 对法规题整段引用（`_best_paragraph`），非法规题路径逐字节不变；
  4. `fixtures/evaluation/regression.jsonl`（PM 裁定 A）：仅补全 RG001 `reference_answer` 的两个发布日，未改 expected/forbidden/source/kind。
- 命令同证据 01；全部 offline，无真实 provider 调用。

## A. 意图层（产品路径）修复前后

| 问题 | 修复前 missing_fields | 修复后 missing_fields | 修复后 mode |
| --- | --- | --- | --- |
| E120《明码标价和禁止价格欺诈规定》… | 采购价格 | `()` | document |
| E118 进行价格比较时…被比较价格有什么限制？ | 采购价格 | `()` | document |
| E087 2025 Q4 柠檬茶…有效价格吗？ | 采购价格 | `()` | document |
| E095 柠檬茶 500ml 在 CVS 和 NKA 的价格… | 采购价格 | `()` | document |
| E116 抽奖式有奖销售… | 销售额 | `()` | document |
| E122 违反反不正当竞争法第十一条…有奖销售… | 销售额 | `()` | document |
| 「宣传海报的采购价格是多少？」 | 采购价格 | 采购价格（保持） | document |
| 「城西店本月销售额是多少？」 | 销售额 | 销售额（保持） | document |
| 「滨江店柠檬茶 500ml 的价格是多少？」 | 采购价格 | 采购价格（门店+物品语境，保持） | document |

集成断言（`backend/tests/integration/test_p1_t101_vocab_context.py`，真实 HTTP 上传→worker→发布→提问）：

- 6 道受影响题：`missing_fields == []`，文本无「资料中未记录」，`kind != clarification`；
- E120：`kind=answer`，文本含 `2022年7月1日`、《关于商品和服务实行明码标价的规定》、《禁止价格欺诈行为的规定》，来源含「明码标价」资料；
- 宣传海报采购价格 / 滨江店柠檬茶 500ml 的价格：仍 `not_found` 且 `missing_fields=["采购价格"]`、无来源。

## B. regression local（修复后）

| case | 修复前 | 修复后 | 说明 |
| --- | --- | --- | --- |
| RG001 | fail / clarification（MISSING_SLOT） | **pass / answer** | 提前截断消失；回答为 L02 第二十七条整段（2022-07-01 + 两项废止规定），引用 paragraph:38/39 |
| RG002–RG007 | fail | fail，失败 checks 与修复前逐条一致 | 本包不改 T102–T106 |

- 门禁：`hard_failures=['security_leak', 'pagination_contract']`（与修复前同一集合，分别来自 RG006/T105、RG003/T102），`exit_code=1`，`scored=7/None`，`min_sample_missing` 不变。
- RG001 的 local 转正依赖 PM 裁定 A 的两处授权改动：`rag/answer.py` 法规题整段抽取 + RG001 `reference_answer` 补发布日（证明链见证据 04）。

## C. b0 / badcase local（修复前后逐例一致）

| suite | 修复前 | 修复后（裁定 A 落地后复跑） | 逐例状态/kind |
| --- | --- | --- | --- |
| b0 | pass 29 / fail 3 / skipped 8，hard `[]` | pass 29 / fail 3 / skipped 8，hard `[]` | **0 例变化** |
| badcase | pass 9 / fail 4，hard `[]` | pass 9 / fail 4，hard `[]` | **0 例变化** |

- 对照脚本只读 `cases.jsonl`，比较 `(status, outcome.kind)`；diff 为空。
- 结论：本包未新增任何硬失败，价格类（b0 price stratum）行为不变。

## D. 受影响 local 题（RagIndex.ask 直跑，仅观测，不作为种子）

| 题 | 修复后 kind | expected_values 命中 | 说明 |
| --- | --- | --- | --- |
| E118 | answer | 1/1 | 引用 L02 第十六条段落 |
| E120 | answer（单句） | 0/3 | offline 只取一句；见证据 04 |
| E116 | answer | 1/1（五万元） | 引用 L01（含第十七条段落） |
| E122 | answer（错条） | 0/1 | 检索落到第二十六条，与本包无关 |
| E087 / E095 | clarification（商品/渠道歧义） | — | 不再出现 UNRECORDED_FIELD；歧义澄清属既有行为 |
