# R0-CAPTURE-KEYS：`retrieval_observed.candidate_unit_keys`（候选单元身份采集）

日期：2026-11-16　范围：**离线实现 + 测试，未发真实请求**　结论：**已交付，无需改冻结件**

## 1. 结论
- `retrieval_observed` 新增两枚**可选**键（不新增码表、不升 schema 版本）：

| 键 | 类型 | 语义 |
| --- | --- | --- |
| `candidate_unit_keys` | `list[str]` | 该次候选上界各单元的 `unit_key`（形如 `sheet:<表>:row:<行号>` 的标识符，非正文/值/实体名） |
| `candidate_unit_keys_truncated` | `bool` | 上面列表是否因 32 上限被截断 |

- 只在 `scope == "rag_candidate_upper_bound"` 的发射点携带；`legacy_retrieve_*` 不建键。
- 解析复用既有 `RagIndex.get_unit`（不新建第二条 DB 查询链路）；解析不到的 unit 跳过（不报错/不占位）；排序去重后上限 32。
- 纯观测：不改检索计划/结果集；`capture_enabled()` 关闭时不解析、不发事件、不建键。

## 2. 改动清单（逐文件:行）
| 文件 | 行 | 改动 |
| --- | --- | --- |
| `backend/src/mktkb/observability/evaluation_capture.py` | 173-177 | 登记 `candidate_unit_keys: _Field(_LIST_STR, required=False)`、`candidate_unit_keys_truncated: _Field(_BOOL, required=False)`；`_ENUM_VALUES` 零新增 |
| `backend/src/mktkb/qa/service.py` | 118-121 | `CANDIDATE_UPPER_BOUND_SCOPE` / `MAX_CANDIDATE_UNIT_KEYS=32` |
| 同上 | 124-142 | `_candidate_unit_keys`：`index.get_unit(unit_id).unit_key`，跳过缺行、排序去重，返回 `(前32, 是否截断)` |
| 同上 | 145-156 | `_candidate_unit_key_fields(scope, ...)`：非 upper_bound 一律返回 `{}`（scope 门唯一落点） |
| 同上 | 664-690 | 上界发射点先算 `identity_fields`（异常兜底为空），与 `unit_ids`/丢弃原因码在**同一次** `emit_capture_event` 发出 |
| `backend/tests/evaluation/test_r0_13_candidate_unit_keys.py` | 新增 | 28 用例：协议/旧 envelope/scope 门/身份对齐/32 截断/空集/关闭观测/行为不变/冻结闭包 |
| `backend/tests/evaluation/test_r0_12_candidate_drop_reason.py` | 566-573 | 仅更新该用例的事件键集 pin：旧 6 键 + 丢弃三键 + 新增身份两键 |

## 3. 兼容性论证
1. 可选键缺省时 `clean_event_payload` 直接 `continue`，不合成：旧 payload 清洗逐键逐值不变（用例 pin）。
2. 不升版：`CAPTURE_SCHEMA_VERSION` 仍 `mktkb.eval-capture/v0.1`；两键不入 `_ENUM_VALUES`（不是枚举）。
3. 冻结件零改动：`p2_hard_evidence` / `p2_empty_scope_proof` 从共享 `EVENT_FIELDS`/`clean_event_payload` 读白名单；旧 envelope 结论不变，带合法新键仍 `empty_use_scope_ok`，非法类型 fail-closed。
4. 语义不变：`unit_ids`/`candidate`/`truncated`/`empty`/三枚丢弃原因键与事件条数逐值不变；`diag` 机制未动。

## 4. 红 → 绿
- **红（实现前，同一命令）**：**23 failed / 5 passed**。代表错误：`assert 'candidate_unit_keys' in {6 键}`；`candidate_unit_keys_must_be_list` 未出现（缺键被当未知字段拒）；真实事件读不到该键。
- **绿（实现后）**：**28 passed**（无 skip/xfail）。

## 5. 测试统计
| 批次 | 结果 |
| --- | --- |
| 新用例 `evaluation/test_r0_13_candidate_unit_keys.py` | **28 passed** |
| `tests/observability` + `tests/rag` + `unit/test_conversations.py` + `test_p2_empty_scope_proof.py` + `test_r0_12` + 本单 | **1129 passed / 2 failed**（均为下述已知失效） |
| 更新后 `test_r0_12` + 本单 | **102 passed** |
| 冻结消费面（仓库外 basetemp）：`test_p2_capture_contract_v02` + `test_p2_evidence_capture` + `test_p2_evidence_io` + `test_p2_evidence_snapshot_v03` | **62 passed** |
| 已知失效（单独复跑确认，与本单无关） | `test_s4_stage_limit` `40 == 20.0`；`test_paths_e2e` `'rag' == 'legacy'` |

命令：`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"; .\.venv\Scripts\python.exe -B -m pytest <路径> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\capkeys`。离线闸门 `t09_network_guard` + 正对照（`getaddrinfo("api.deepseek.com")` 被拦 `T09-D1`，自证后清账）：真实出站 0。

## 6. 行为不变自证 / 冻结件
- 同一合成输入，开/关观测两次 `candidate_unit_ids_for_intent` 返回的候选 id 集合逐值相同，事件 `unit_ids == sorted(ids)`；关闭观测时 0 次 emit、0 次 `RagIndex.get_unit` 调用（计数用例）。
- 身份解析失败逐 unit 吞掉，只在成功发射时产生只读查询，不影响返回值。**未改冻结件**（`evaluation/p2_*.py`、`docs/evaluation/*`、`fixtures/`、账本、预算、旧证据、case-plan 零改动）；未读私有材料、未安装依赖、未发真实请求、未做任何 git 写操作。
