# C1-P2 空使用集闭包证明：独立替代实现 + 合成差分证据

- 角色：普通开发（C1-P2）；不是验收、不是经理。
- 日期：2026-11-14；分支 `codex/p2-e2e`；HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`。
- 范围：只做「请求使用集为空」判定的独立替代实现、合成测试与差分证据；零真实调用。
- 本报告不写 T207 合格、不写 release/阈值/基线批准、不写 P2 完成、不写 C1-2 可跑。

## 0. 边界与未做的事

- 只用合成数据；未读真实 H2 题面/标签/答案/私有密文/key/`.env`/保管会话。
- 未修改 `p2_hard_evidence.py`、`p2_evidence_capture.py`、`p2_evidence_io.py`、
  Q1a-1/1b 模块与契约、旧卡/账本/GO、30 题/标签/阈值。
- 未 stage/commit/push；未新建 worktree/切分支；除本包新增文件外未改既有文件。
- 未把新模块接入 `p2_evidence_rescore.py` / `p2_evidence_rescore_axes.py`（消费侧适配
  不在本包范围；接入需要另一次受控改动与验收）。
- 没有真实 H2 逐回合读数；因此不能给出「36 回合里会有多少回合由 unknown 转 proven」的
  数字。本包只证明**判定能力与差分关系**，不声称真实收益。

## 1. 产物

| 类型 | 路径 |
|---|---|
| 替代实现 | `backend/src/mktkb/evaluation/p2_empty_scope_proof.py` |
| 合成测试 | `backend/tests/evaluation/test_p2_empty_scope_proof.py` |
| 本报告 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/dev-report.md` |
| 证据目录 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/evidence/` |

证据目录内容：

- `pytest-collect.txt`、`pytest.txt`：collect 与运行原始输出。
- `differential_probe.py`、`differential.json`：72 例合成语料的逐例差分结果。
- `zero_call_probe.py`、`zero-call.json`：socket/DNS/provider/frozen 模块计数与正对照。
- `frozen_probe.py`、`frozen-sha.json`：C 冻结 12 对象逐字节核对。
- `protected_compare.py`、`protected-after.json`、`protected-compare.json`：保护件
  前后 hash 与 git/untracked 状态对比。

### 1.1 证据文件 SHA256（本报告写入前实测）

| 文件 | 字节 | SHA256 |
|---|---:|---|
| `backend/src/mktkb/evaluation/p2_empty_scope_proof.py` | 35240 | `1f503d16d91d3423da969a659c2f97fe811e9c2af859158585ecee16878f28ea` |
| `backend/tests/evaluation/test_p2_empty_scope_proof.py` | 50710 | `a2b20218ccf1178482fdb66b8d6bcedaf8a46eb3e4f85af1d0eac4fcf89685a1` |
| `evidence/pytest-collect.txt` | 18124 | `b1cbb5ce4e8840b5bb2b5a47ad0af69a2e1b666d5f450eaedafd3988cebc1e90` |
| `evidence/pytest.txt` | 1310 | `7fdefd44ae878db319140e74dd37ec2e7089aba82ff1c9beb4c1247997d01a90` |
| `evidence/differential.json` | 50641 | `0528591da48152036d72c7f866c8e6a9ed0d509350a3f357be597f2967c21016` |
| `evidence/zero-call.json` | 704 | `55183cca68eebbe159a8ea65c0973c7083849922e89205d811f40910cb1ea7f9` |
| `evidence/frozen-sha.json` | 4254 | `192c2c799f26bb8dca77ae396c719de0fdb30983bdec29fa390f9d98b252d8f1` |
| `evidence/protected-after.json` | 41989 | `84c97dec512933375610d07e6daa2118f3e268320225f745bc0b602dad9c4cae` |
| `evidence/protected-compare.json` | 3242 | `f1fe89b7d850ca6320134bff27c1efe523eb33adfdf135442e0361066d795a9b` |
| `evidence/differential_probe.py` | 5372 | `99aa8d5999e068c1db5a64fd7e7a4cbfc45778da2b34ea99691021a7a8ae4dae` |
| `evidence/zero_call_probe.py` | 5874 | `d29a3fa1e9799465c2beb3ae4260002b9c01c17864241685548cce6cd78ac4b3` |
| `evidence/frozen_probe.py` | 2874 | `fc810e01e3c193976ba2acd29665245ec2864263726a4165d0f81f6f3ae0d0b6` |
| `evidence/protected_compare.py` | 14365 | `eaab612b3c40ac8b00c14bd048b048111017fb44a04a17480e51d3bf06aab1c2` |

> 并行 C1-P1/经理在本会话期间追加的 6 个公开产物不在上表；它们由 `protected-compare.json`
> 的 `concurrent_entries_excluded` 记录，未计入本包写入。

## 2. 契约/说明（模块语义）

### 2.1 API

```python
prove_empty_use_scope(evidence) -> EmptyScopeProof
empty_use_scope_proof(evidence) -> tuple[bool, str]   # 兼容冻结原语的 (bool, reason) 形状
```

`EmptyScopeProof` 字段：`proven`、`code`、`shape`、`branch`、`retrieval`、`outcome`、
`outcome_class`、`detail`、`usage_layers`、`candidate_sources`。

固定码：

- proven：`empty_use_scope_ok`。
- not proven：**统一** `empty_set_not_proven`（按任务要求 fail-closed；更细诊断在
  `shape` / `detail`，不回显原始文本/ID）。

### 2.2 使用层 vs 候选层

本实现把「已使用来源集合」限定为真正进入以下任一层的来源：

1. `model_input.evidence[].source_id`（模型实际收到的证据）；
2. `model_output.source_ids`（模型自报引用）；
3. `direct_rag_answer.facts[].source_unit_id` 与 `cited_unit_ids`；
4. `answer_result.source_ids` / `commit_observed.source_ids`（最终引用）；
5. `projection.message_sources`（DB 结果消息来源）；
6. `entity_inheritance.source_unit_id`（保守计为使用）。

以下**不是**本回合的使用层，单独归为候选层：

- `retrieval_observed.unit_ids`（检索候选/检索证据上限）；
- `query_state_*` 与 `projection.query_states[].state_json.candidates`
  （会话级检索候选，供后续回合使用）。

这是与冻结原语的核心语义差异：冻结原语把候选层也当作使用层，候选非空即不可证明；
本实现只有在**所有使用层显式为空**时才证明。候选层非空但使用层为空，属于
「检索有结果但未被使用」，可以证明。

### 2.3 形状

`branch`：`legacy_no_model` / `legacy_model_answer` / `rag_direct` / `unknown`。

`retrieval`：`retrieval_absent` / `retrieval_empty` / `retrieval_candidates_unused` /
`unknown`。

`outcome_class`：`refusal` / `clarification` / `knowledge_changed` / `factual` /
`unknown`。

`shape` 默认是 `branch/retrieval/outcome` 组合；若缺口发生在某些维度已知之前/之后，
保留已知维度，`detail` 给出精确缺口（例如 `model_events_missing`、
`branch_evidence_missing`、`template_identity_unverified`）。所有未证明形状的
`code` 始终是 `empty_set_not_proven`。

### 2.4 无检索的正证据

`legacy_no_model` 且没有 `retrieval_observed` 时，只有 v0.3 `runtime_snapshot` 明确给出：

```json
{"retrieval_use": {"availability": "complete", "reason": null,
  "candidate_observation": {"availability": "not_observed",
                            "reason": "no_retrieval_observed"},
  "candidates": []}}
```

才认为「本轮确实没有检索」是可证明的；否则按 `model_events_missing` fail-closed。
`legacy_model_answer` 与 `rag_direct` 的“无检索”不需要该标记（模型/直接回答分支本身
已有空证据路径）。

### 2.5 独立性

新模块不 import `p2_hard_evidence` / `p2_evidence_capture` / `p2_evidence_io`；
只 import 产品事件契约 `mktkb.observability.evaluation_capture` 与产品文案
`mktkb.copy`。冻结原语只在**测试**里只读 import 做差分对照。事件/投影/模板常量按
契约声明在本模块内（版本 `p2-empty-scope-proof/v0.1`），不调用冻结证明逻辑。

## 3. 覆盖形状与合成语料

72 例合成 envelope，覆盖任务要求的 7 类形状：

| 要求形状 | 代表用例 | 本实现读数 |
|---|---|---|
| 无检索 | `legacy_model_answer_no_retrieval`、`rag_direct_empty`、`no_retrieval_positive_snapshot_legacy_no_model` | 前两例 proven；后者需 v0.3 正标记；无标记时 fail-closed |
| 检索为空 | `legacy_no_model_retrieval_empty`、`legacy_model_answer_retrieval_empty` | proven |
| 检索有结果但未被使用 | `retrieval_candidates_unused_legacy_model`、`retrieval_candidates_unused_rag`、`retrieval_candidates_unused_with_unresolved` | proven |
| 多轮中部分轮空 | `multi_turn_partial_empty`（历史消息 + 历史 query_state 候选 + 本回合未使用候选） | proven |
| 拒答分支 | `retrieval_candidates_unused_no_answer`、`factual_answer_kind` 反例 | 无事实模板 + 空使用 → proven；事实型 kind 不胜任 → fail-closed |
| 带 clarification 的分支 | `clarification_template_base`、`clarification_template_suffix`、`retrieval_candidates_unused_clarification` | 基础模板与“可选：…”后缀均 proven |
| `model_events` 缺失 | `legacy_no_model_no_retrieval_no_marker`、`model_input_without_output`、`model_output_without_input` | 全部 fail-closed（`empty_set_not_proven`） |

分布（`differential.json`）：

- `branch`：`legacy_no_model` 23、`legacy_model_answer` 13、`rag_direct` 5、`unknown` 31。
- `retrieval`：`retrieval_empty` 14、`retrieval_candidates_unused` 8、
  `retrieval_absent` 3、`unknown` 47。
- `outcome_class`：`refusal` 19、`clarification` 3、`knowledge_changed` 2、
  `factual` 1、`unknown` 47。
- 不同 `shape` 标签 22 个。

## 4. 与 C 冻结原语的差分

同一批 72 例合成输入，逐例比较 **proven 布尔结论**：

| 类别 | 例数 | 说明 |
|---|---:|---|
| 结论一致且 both proven | 12 | 冻结原语可证明的标准空集形状 |
| 结论一致且 both not proven | 48 | 缺字段、非空使用、模板不匹配、分支矩阵错误等 |
| 本实现 proven / 冻结 not proven | 11 | **固定码 + 理由**（下表） |
| 本实现 not proven / 冻结 proven | 1 | 本实现更严（实体继承），**固定码 + 理由** |
| 未编码的不一致 | **0** | 不允许静默放过 |

扩展固定码（本实现 proven、冻结 not proven）：

| 固定码 | 例数 | 冻结原语为何不可用 |
|---|---:|---|
| `frozen_retrieval_candidates_are_usage` | 7 | 冻结原语把 `retrieval_observed.unit_ids` / `projection.units` 当使用层；候选非空即不可证明 |
| `frozen_query_state_candidates_are_usage` | 2 | 冻结原语把会话级 `query_states[].state_json.candidates` 当使用层；多轮历史候选非空即不可证明 |
| `frozen_requires_retrieval_marker_for_legacy_no_model` | 2 | 冻结原语要求 legacy 无模型分支必须有 `retrieval_observed`；v0.3 已显式声明 `no_retrieval_observed` 时仍返回 `model_events_missing` |

更严固定码（本实现 not proven、冻结 proven）：

| 固定码 | 例数 | 理由 |
|---|---:|---|
| `frozen_does_not_track_entity_inheritance` | 1 | 冻结原语不把 `entity_inheritance.source_unit_id` 计入使用层；本实现按保守口径计为使用，只可能更严，不会产生假 proven |

差分前后 `p2_hard_evidence.py` 实测
`fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b`，
`frozen_module_unchanged = true`。

## 5. 测试结果

- collect：**88 tests collected**（`pytest-collect.txt`）。
- run：**88 passed，1 warning**（`pytest.txt`；warning 是既有 `fastapi.testclient` 的
  `StarletteDeprecationWarning`）。
- exit：**0**。
- 运行命令（在 `backend/` 下）：
  `$env:MKTKB_NO_DOTENV="1"; $env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONIOENCODING="utf-8";`
  `..\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_p2_empty_scope_proof.py -q -p no:cacheprovider --basetemp .pytest-tmp/c1p2`

测试覆盖：7 类形状、差分逐例、固定码 fail-closed、模板/空白/后缀、候选层与使用层
分离、实体继承更严、未知投影行键、坏事件类型、sentinel 不回显、netguard external=0、
独立子进程不加载 provider/frozen 模块。

## 6. 保护件与冻结

`protected-compare.json` 的 `verdict = unchanged`，`difference_count = 0`：

| 组 | 项数 | 不一致 |
|---|---:|---:|
| 15 tracked modified | 15 | 0 |
| C 冻结 12 | 12 | 0 |
| Q1a-1 protected | 38 | 0 |
| 只读参考 | 2 | 0 |
| R2 protected 28 文件 | 28 | 0 |

- 公开外部树 `r1_evidence_tree`、`not_run_evidence_tree`：逐文件 hash 映射与总字节
  相等，重算 tree hash 与基线相等。
- 私密/保管外部项（`old_run_tree`、`holdout_root`、`custody_annotations`、
  `contract_ciphertext`、`r1_private_detail`）：**本包未重读**，只引用 R2 基线
  hash；`recomputed = false`，理由为保管边界。需要保管角色复核时另起只读复核。
- untracked 树：路径集合 2084/2084 相等，0 missing、0 added；所有非本包文件
  `mtime <= 会话开始`；未重算内容 hash（untracked 树可能含 H2 敏感产物，普通开发
  不读字节）。本包新增文件全部在 `c1-1/p2/` 前缀下。
- 并行 C1-P1/经理产物 6 个（contract v2、annotation v2、manager receipt、taskbook 等）
  在会话开始后出现；对比时作为 concurrent 排除，不计入本包写入。
- git：HEAD/分支不变；`tracked_modified` 15 条路径与基线逐条相同；`staged = 0`；
  `foreign_untracked_entries = 205` 与基线相同；`commits_created = 0`。
- `p2_hard_evidence.py` SHA 前后均为
  `fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b`。

## 7. 零调用

`zero-call.json`：

- 同一进程内先做正对照：`socket.create_connection(("203.0.113.1", 9))` 被 socket
  guard 拦截（`positive_control.blocked = true`），证明守卫有效；随后清零计数。
- 72 个合成 proof 运行后：external network attempts **0**、socket connect **0**、
  create_connection **0**、DNS **0**、httpx transport **0**、provider modules loaded
  **0**、provider calls **0**、real calls **0**。
- 冻结 `p2_evidence_capture` / `p2_evidence_io` 模块加载 **0**；冻结原语在探针中
  仅以 stub 占位避免加载，差分测试本身使用真实冻结原语（见 §4）。
- 探针用 stub `mktkb` 包避免 `mktkb/__init__` 触发 `main`/providers import；
  pytest 进程本身若 import `mktkb` 会加载 provider 模块，但未实例化/未调用，
  `t09_network_guard` 仍断言 external=0。这里的“provider modules loaded 0”只指
  隔离探针路径，不指整个 pytest 进程的模块导入图。

## 8. 残余与未决

| id | 内容 |
|---|---|
| R-C1P2-01 | 新模块未接入 `p2_evidence_rescore.py` / `p2_evidence_rescore_axes.py`；消费侧适配不在本包范围。接入需另一次受控改动与验收。 |
| R-C1P2-02 | 没有真实 H2 逐回合读数；不能给出 36 回合中 unknown→proven 的实际数量。冻结原语的 2/36 实测仍是唯一真实读数。 |
| R-C1P2-03 | 所有 not proven 统一码 `empty_set_not_proven`；`model_events_missing` 等细分只在 `shape`/`detail`。若 C1-2 要保留冻结原语的细分 reason，需要薄适配（未做，避免改消费侧）。 |
| R-C1P2-04 | 实体继承按使用处理，比冻结原语更严；合成差分中 1 例属于此方向。 |
| R-C1P2-05 | 私密/保管外部项未重读；只引用 R2 基线 hash，未在本会话重算。 |
| R-C1P2-06 | 并行 C1-P1/经理产物 6 个在会话开始后出现，已在对比中作为 concurrent 排除；若 P1 继续追加产物，对比需重跑。 |
| R-C1P2-07 | 本模块按 v0.1 契约常量声明事件/投影/模板表；若采集契约升级，需要新版本号与重新差分。 |
| R-C1P2-08 | `runtime_snapshot` 只用于“无检索”正证据；使用层以 events/projection 为准（与冻结原语同源）。未额外做 snapshot 使用层的交叉校验。 |

## 9. 不主张

- 不主张 T207 合格、P2 完成、release/阈值/基线批准。
- 不主张真实 H2 上 29 个 unknown 会下降多少；本包只给合成判定能力与差分证据。
- 不主张新模块已经替代冻结原语在生产消费路径中生效；它目前是独立对象。
- 不主张 11 例扩展在真实证据上一定成立；它们依赖“候选层不是使用层”的语义定义，
  该定义已在 §2.2 明确，并由合成差分逐例编码。
