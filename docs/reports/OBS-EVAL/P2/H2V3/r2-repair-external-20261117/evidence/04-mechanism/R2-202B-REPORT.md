# R2-202B：C25/C29 同形身份的端到端证明与反例

日期 2026-11-17 · 范围：`backend/tests/evaluation/test_r2_202b_entity_identity_e2e.py`（新增）
· `backend/src` **未改动**（本报告 §10）。

## 1. 结论（当前工作树）

| 断言 | 结果 | 计数 |
|---|---|---|
| `direct_rag_answer.facts[].entity_key` 与 `db_projection.units[fact.source_unit_id].entity_key` 逐字节相等 | **true** | 1/1 |
| fact 类型段 == unit `entity_type`（两侧均为 `item`） | **true** | 1/1 |
| `cross_entity`（`p2_hard_evidence` 公开入口，v0.2 scope 合同路径） | **passed** | 1/1 |
| `cross_entity`（`p2_evidence_rescore_axes` 公开入口） | **passed** | 1/1 |

两侧键形态均为 `item|id:<归一化标识>`；不再是历史 C25/C29 的“unit `item|id:<值>` vs fact `item|<值>`（`type_bare_id`）”。

分类 reason：两个入口均为 `frozen_targets_match_ok`（各自 `PASS_REASONS["cross_entity"]`）。

## 2. 同形合成场景（虚构实体）

两份合成 XLSX（`openpyxl` 现场生成，仅虚构实体）：

- 物品位置表：表头 `标识/门店/物品/位置`；一条**有标识**物品行 + 两条**无标识**同店同物位置行。
- 合作店家信息：表头 `标识/店家/联系人/电话`；一条**另一门店**记录（不参与目标问题）。

提问形如“`<门店>`的`<物品>`（编号 `<标识>`）放在哪里？”。问题显式带标识，产品 `_rag_owns_turn`
把该轮交给 RAG 内核直答（`plan.mode=record`、`identifier` 在 filters），因此产生
`direct_rag_answer` 事实（`field_role=location`），而不是模型自由措辞分支。

链路是真实产品链路 + 评测捕获，不是直调 `build_entity_key`：

`ProductEvalAdapter.start/ingest/open_conversation/ask_turn`（真实上传/解析/发布/检索/答案）
→ `EvidenceCaptureConfig` + `EvidenceWriter`（加密 turn envelope）
→ `read_encrypted_evidence` 严格读回 → 两个评测公开入口分类。

## 3. 核心断言

新增测试：

`backend/tests/evaluation/test_r2_202b_entity_identity_e2e.py::test_same_shape_fact_and_unit_keys_are_byte_equal_and_cross_entity_passes`

- `fact_count = 1`；`fact_key == unit_key` 按 UTF-8 字节比较为 true；
- `unit.entity_type = "item"`；`fact_key.split("|")[0] = "item"`；
- 两侧键都含 `|id:`；
- `p2_hard_evidence.classify_case_evidence(..., scope_contract=...)` → `cross_entity = passed`；
- `p2_evidence_rescore_axes.rescore_axes_case(...)` → `new_axes["cross_entity"]["state"] = passed`。

axes 视图由 envelope 自身字段按公开 dataclass 构造：`db_projection.units` → `UnitView`/
`EntityIdentityView`，`capture.events` 的使用层 → `layers`，`direct_rag_answer.facts` →
`EntityFactView`；不读取、不复制任何旧 verdict，也不把分类结果反写进视图。

## 4. 反例（全部 fail-closed，均通过）

只改捕获 envelope 的输入层（投影/事实/引用），不改分类器与产品代码；改动后先过
`validate_turn_evidence`（反例 a）或保持标题/绑定不变。

| 反例 | 变异 | `p2_hard_evidence` | `p2_evidence_rescore_axes` |
|---|---|---|---|
| a1 有身份但不匹配目标（RAG 事实层） | `direct_rag_answer.facts` 追加另一实体事实，且该事实键与它自己的 backing unit 键一致 | `violation / other_entity_used` | `violation / other_entity_used` |
| a2 纯引用层 | 同一外实体只进 `cited_unit_ids`（不发送模型、不产生事实） | `violation / citation_entity_mismatch` | `violation / citation_entity_mismatch` |
| b 半身份（只有 type / 只有 key） | 目标投影行分别清空 `entity_key` / `entity_type`（2 个变体） | `unknown / entity_identity_unresolved` ×2 | `unknown / entity_identity_unresolved` ×2 |
| c 使用层 unit 解析不到 | 从 `db_projection.units` 删除目标行，fact 仍指向该 id | `unknown / entity_identity_unresolved` | `unknown / entity_identity_unresolved`（审计 `entity_identity_missing`） |
| d 重复 unit_id 行 | 投影追加同一目标行 | `unknown / entity_identity_unresolved`，审计含 `…db_projection.units.duplicate` | **N/A**：axes 视图是按 `unit_id` 的映射，重复行不可表示；重复门只在 hard v0.2（见 §9） |
| e 无标识同店同物多行 | 两条无标识同店同物行 | 不涉及分类；断言两侧键 | 同左 |

反例 e 的计数：来源侧 2 条同店同物无标识行，RAG 记录块侧 2 条；两侧各 2 个键，
`|doc:` 与 `|unit:` 均出现，行间键互不相等；逐行 UTF-8 字节相等 2/2。
两侧分别取产品自己的持久化字段：`retrieval_unit_index.entity_key`（评测单位侧同源）与
`rag_chunks.entity_key`（`_fact` 写 `Fact.entity_key` 的直接来源）；不是测试里另算的键。

## 5. 敏感性对照（R0 补丁是否真的在起作用）

`monkeypatch.setattr(mktkb.rag.chunking, "_entity", _legacy_entity)` 在运行时还原 HEAD 版
名称复合键（不动文件）；同一合成场景重新走真实产品链路 + 捕获：

- `fact_key == unit_key` → **false**（0/1）；
- fact 键 `|` 数 = 2（旧 `item|<store>|<item>` 名称复合形态），unit 键仍 `item|id:…`；
- `p2_hard_evidence` → `unknown / entity_identity_unresolved`；
- `p2_evidence_rescore_axes` → `unknown / entity_identity_unresolved`，审计码 `entity_identity_missing`。

结论：同形场景的 passed 不是测试构造太弱，而是当前 `build_entity_key` 单点派生在起作用。

## 6. 历史 unknown 的差异归因（判据未变）

历史 C25/C29（R2 run_index=2）的固定码：

- unit 侧 `item|id:<归一化值>`（`tail_tag=id`），fact 侧 `item|<值>`（`tail_tag=none`，
  `fact_shape_code=type_bare_id`）；
- 类型段相同（都是 `item`）、标识段不同 0；`key_mismatch_count=1`、`shape_diff_count=1`；
- fact 的 backing unit 可解析、无缺行、无重复行、fact 有 key 且有 source_unit_id。

当前工作树同一形态得到两侧逐字节相同的键；评测两处判据仍是**逐字符串相等**，未改成
`(type,id)` 元组比较：

- `backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py:2030`
- `backend/src/mktkb/evaluation/p2_hard_evidence.py:2529`

因此这是**键形态分叉的消除**，不是判据放宽或变更。C29 另有 `target_ref_no_match`
（注解 target_refs 解析路径），本证明未覆盖该独立分支（见 §9）。

## 7. 命令与退出码

所有命令在 `backend/` 下运行，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`，
`--basetemp=<仓库外临时目录>`（捕获根守卫要求证据根在仓库外），`-p no:cacheprovider`。

新增节点（7 个）：

```text
..\.venv\Scripts\python.exe -X utf8 -m pytest tests\evaluation\test_r2_202b_entity_identity_e2e.py -v -p no:cacheprovider --basetemp=<仓库外临时目录> --no-header
```

- 退出码 **0**；**7 passed**。
- 节点：核心 1、反例 a/b/c/d/e 5、敏感性 1（见 §8 文件内节点名）。

明确列出的既有节点：

```text
..\.venv\Scripts\python.exe -X utf8 -m pytest tests\unit\test_entity_key_parity.py tests\evaluation\test_p2_capture_entity_readiness_e2e.py tests\evaluation\test_r1_108_compat_v06.py tests\evaluation\test_p2_cross_entity_scope_v02.py -q -p no:cacheprovider --basetemp=<仓库外临时目录> --no-header
```

- 退出码 **0**；**74 passed**。

未跑全量 pytest（按任务约束）。

## 8. 新增测试节点

`backend/tests/evaluation/test_r2_202b_entity_identity_e2e.py`

- `test_same_shape_fact_and_unit_keys_are_byte_equal_and_cross_entity_passes`
- `test_counterexample_a_other_identified_unit_still_violates`
- `test_counterexample_b_half_identity_still_unknown`
- `test_counterexample_c_unresolvable_used_unit_still_unknown`
- `test_counterexample_d_duplicate_projection_unit_still_unknown`
- `test_counterexample_e_unidentified_same_name_rows_stay_distinct`
- `test_sensitivity_legacy_rag_entity_shape_returns_unknown`

## 9. 零出站守卫与 NOT-RUN

零出站：

- 每个用例沿用仓库既有 `t09_network_guard`（`pytestmark = pytest.mark.usefixtures(...)`）；
- 核心用例额外断言 `t09_network_guard.snapshot()["external"] == []`；
- 模型走 `MockChatBackend` 的 `httpx.MockTransport`，不产生真实传输；
- 本文件不启动子进程；子进程离线守卫由既有 `test_p2_capture_entity_readiness_e2e.py`
  （`sitecustomize` + socket 日志 + 禁止导入）在 §7 的 74 passed 中覆盖，本次运行未出现外部尝试。

NOT-RUN / 未覆盖：

1. 未跑全量 pytest；未跑真实 H2V3 语料（禁读私有材料）。
2. 未复现 C29 的 `target_ref_no_match` 注解 `target_refs` 解析分支；本证明用直接
   `targets` 合同，只证明“身份相等”机制，不声称 C29 的 ref 解析已修。
3. 反例 d 的 axes 路径：`AxesCaseView` 以 `unit_id` 为映射键，重复投影行在视图层不可表示；
   重复门（`db_projection.units.duplicate`）只在 `p2_hard_evidence` v0.2 路径验证。
   若未来 axes 适配器直接消费原始投影，需要另加重复行门（本次未改判据/未改产品）。
4. 未验证真实语料上的排序/分组副作用；合成场景未触发。

## 10. 产品改动状态

`backend/src` **未被 R2-202B 改动**。工作树中与本机制相关、但在本任务开始前已存在的改动：

- `?? backend/src/mktkb/entity_identity.py`（R0 新增）
- `M backend/src/mktkb/rag/chunking.py`（R0 最小 hunk）
- `M backend/src/mktkb/retrieval/index.py`（R0 最小 hunk）
- `M backend/src/mktkb/rag/facts.py`（既有其他修复，未被本任务触碰）

本任务只新增：`backend/tests/evaluation/test_r2_202b_entity_identity_e2e.py` 与本报告。
未生成 `R2-202B-src-diff.patch.txt`（无产品改动）。
