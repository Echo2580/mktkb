# R0 修复：统一两套 `entity_key` 派生（cross_entity `entity_identity_unresolved`）

日期 2026-11-16 · 范围：`backend/src/mktkb/{entity_identity.py, retrieval/index.py, rag/chunking.py}` + 测试
## 1. 结论
`cross_entity` 对 C02/C21/C27 判 `entity_identity_unresolved` 的根因：**同一条 `SourceUnit` 在两条链上各派生一次实体键，
键形态不同**。现在两侧共同调用 `mktkb/entity_identity.py:build_entity_key`，同一记录得到逐字相同的键；答案文本逐字节
不变（7/7 问法 `text_sha256` 相同）；检索侧写入 DB 的键值一字节未变（无需重建索引）。
## 2. 复核：分叉点与权威形态
| 链 | 位置 | 旧键形态 | 消费方 |
|---|---|---|---|
| 来源/单位侧 | `retrieval/index.py:84` `analyze_fields`（旧键 123-126） | `item\|id:p01` / `item\|北门店\|立牌\|doc:<uuid>\|unit:<uuid>` | `retrieval_unit_index.entity_key`（`retrieval/models.py:76`）→ 评测 `db_projection.units` |
| 产品事实侧 | `rag/chunking.py:252` `_entity`（旧 item/store 分支 264-271） | `item\|城东店\|宣传海报`（无 doc/unit 后缀） | `rag_chunks.entity_key` → `answer.py:1071` `Fact.entity_key` → `direct_rag_answer.facts[]` |

分叉点是**键形态**，不是归一化：两侧归一化本来就同一函数（`rag/chunking.py:97` `normalize_field` → `retrieval/tokenize.py:54`）。
**权威形态 = 检索侧**（`<type>|id:<norm 标识>`；无标识退 `<name>|doc:<doc>|unit:<unit>`），三条依据：
1. 记录级稳定身份只有来源侧具备：`retrieval/index.py:93-94` “没有标识时不跨行/跨资料拼字段，键含资料与单元身份，只会成为独立候选”（`tests/unit/test_retrieval.py:102-107` 锁定）；纯名复合不能区分同店同物的多行记录。
2. 该形态已固化为产品契约：`retrieval/service.py:270-273` `_has_identifier` 按 `"|id:"` 决定能否跨资料合并；`verify_cache.py:80` 把 `entity_key` 计入缓存摘要——改形态要重建索引并改合并语义。
3. 冻结评测的合同 target 就是 id 型：`Q1A-EVAL-REPAIR/v3-author/authoring-report.md:45`、`…/v3-author/independent-review.md:53`（36/36 形如 `item|id:`）；`H2V3/axes-v2/axes-v2-report.md:190` 已记录本缺陷（“两套词法”），`Q1A-EVAL-REPAIR/c1-1/p3/independent-review.md:102` R-04 同源；`p2_evidence_axes_adapter_v2.py:1417-1487` 亦把名称型当 canonical、`id:` 型单列键空间。
## 3. 改法（最小、全局一致）
新增 `backend/src/mktkb/entity_identity.py`（64 行，纯函数、无 IO、不按资料/题面/业务数据分支）：`is_identifier_header`
（标识列唯一判据）、`identifier_value`（首个带值标识列）、`build_entity_key`（有标识→`<type>|id:<norm>`，否则→`<name_key>|doc:<doc>|unit:<unit>`）。
- `retrieval/index.py:124` 改调 `build_entity_key`；`ID_HEADERS`（40）、`_is_id_header`（69）改为委托同一判据。输出逐字节不变（§5 用真实建库对比验证）。
- `rag/chunking.py:270/278/288` item、store 两分支改调同一函数（`_entity` 增 `unit_id` 形参，唯一调用点 349）。`product`/`record`/`document` 三型**不动**：检索侧不产出这三型（`analyze_fields` 只有 item/store），无第二条链可对齐；且 `record|<标识>` 现等于适配层 canonical（`p2_evidence_axes_adapter_v2.py:1439-1443`），改它会把可判变不可判。
- 净增：`entity_identity.py` **+64**；`retrieval/index.py` +11/−6=**+5**；`rag/chunking.py` 我的 hunk +30/−4=**+26**（该文件另有另一助手既有 `field_role` 增量 +28/−0，未触碰）；`tests/unit/test_entity_key_parity.py` **+111**；`tests/rag/test_chunking.py` +2/−1=**+1**。源码净增 **+95**，测试净增 **+112**。
## 4. 红 → 绿
`backend/tests/unit/test_entity_key_parity.py`（7 例：两侧同键、无标识同键、店家同键、归一化共享、不同标识不等、同名不同单元不等、重复派生幂等）。
- 红（改前）`5 failed, 2 passed`，典型 `assert 'item|id:p01' == 'item|城东店|宣传海报'`；绿（改后）**7 passed**。
- 反例两版都通过：`item|id:p01` vs `item|id:p02` 不等；同名无标识但 unit 不同 → 不等（防归一化过度合并）。
- 独立反事实：把 rag 键临时还原成名称型（`backend/.pytest-tmp/entity-key-capture/legacy_keys_plugin.py`）后 `test_p2_capture_entity_readiness_e2e` 立即回到改前结论 → 差异只来自键形态。
## 5. 行为中立自证（同一组合成问法，改前/改后逐字节）
合成库：物品位置表（标识 P01-P04）、合作店家信息（S01/S02）、无标识位置表（北门店同名 2 行 + 南门店 1 行）。`text`/`kind`/`reason`
全同，7/7 `text_sha256` 相同：`9209feef8002`/`021515163e3a`/`bf47f07aaa28`/`42f740b5932e`/`70f3ff9b5c57`/`366555f19e5b`/`c0a5171729c7`，
依次为：城东店宣传海报在哪、城西店展架位置、城东店合作状态、城东城西电话、城东海报+展架位置、北门店立牌（无标识 2 行）、南门店立牌。
键侧（同库，uuid 归一化比对）：改前两侧 `(label,key)` 交集 **0/9**，改后 **9/9 完全相同**；`retrieval_unit_index` 键集合改前=改后
（逐条相同，仅建库 uuid 变化）。样例：`城东店的宣传海报` rag `item|城东店|宣传海报` → `item|id:p01`（=检索侧）；`北门店的立牌`
rag `item|北门店|立牌`（2 行同键）→ `…|doc:<uuid>|unit:<uuid>`（逐行可区分）。取证件：`backend/.pytest-tmp/entity-key-capture/capture-{before,after}.json`。
## 6. 测试统计（`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`，`-B -p no:cacheprovider`）
| 套件 | 结果 |
|---|---|
| `tests/rag`（全量） | **445 passed, 1 failed** = 既有失效 `test_s4_stage_limit.py`（预算 40 vs 20，任务书已声明忽略） |
| `tests/unit/test_retrieval.py`、`integration/test_visible_index.py`、`integration/test_v3_safety_fix_e2e.py`、`rag/test_t207_security_precedence_synthetic.py`、`unit/test_t207_v8_safety_contract_synthetic.py` | 全部 passed |
| 上述 5 项 + parity + `rag/test_chunking.py` 合并 | **65 passed** |
| `tests/unit`（全量，额外自查） | **404 passed, 1 failed** = `test_s2h_r3_official_profile`（同一预算 40 vs 20 环境冲突） |
| `tests/evaluation/{capture_entity_readiness, eval_tool_repair, axes_adapter_v2}`（额外自查） | **60 passed**（须用仓库外 `--basetemp`，否则证据根守卫报 `evidence_root_inside_forbidden`） |
## 7. 风险
1. **评测状态位变化（预期内）**：`tests/evaluation/test_p2_capture_entity_readiness_e2e.py` 原断言 `cross_entity` = `[passed, unknown, unknown, violation]` 且要求 `results[2].missing_codes` 含 `entity_identity_unresolved`——这正是本缺陷。改后为 `[passed, unknown, passed, violation]`，我改了该文件 2 行断言（+2/−2，带 R0 注释）。**该文件在工作树中未被 git 跟踪**，若属 p2 侧在改，请 p2 负责人确认/覆盖。数据面：fact 分支由 unknown 转 passed（本例 fact 来自目标实体，判定正确）；若 fact 来源单元确属他实体，同一处落 `other_entity_used`（fail-closed，与单位分支同口径）。
2. **无标识多行记录的分组**：rag 键由“名复合”变“名+doc+unit”，同店同物无标识的多行不再共享分组键。合成库第 6 问改前后均为 `clarification`（歧义原本由上层产生），文本未变；若未来出现“同店同物无标识、须合并成 1 个实体作答”的语料，行为会与改前不同（且与检索侧“不合并”口径一致）。唯一可能的排序/分组影响面，真实语料未复核。
3. **枚举顺序**：`rag/retrieval.py:559` 枚举排序第二键含 `entity_key`，仅当多条记录 label 相同（同店同物）时次序可能变化；合成库未触发，真实语料未验证。
4. **未统一的实体类型**：若某行同时有门店+物品+品名，rag 判 `product`、检索判 `item`，实体**类型**仍不同 → 该题仍 unknown。既有类型判定差异，非键形态问题；改动会牵动 label/filters 与答案渲染，未做。
## 8. 未验证项
- 真实 H2V3 语料上的 C02/C21/C27 未重跑（禁读私有材料、不跑私有 harness）；轴侧只在合成 e2e + 反事实插件上验证。
- 未 `git add/commit`；未动 `.env`/fixtures/账本/预算/旧证据/case-plan；`backend/src/mktkb/evaluation/p2_*.py` 一字未改。
