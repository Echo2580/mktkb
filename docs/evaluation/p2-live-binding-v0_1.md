# P2 真实准入绑定契约 v0.1（T206-PRE）

> 状态：**已实现并离线验证**（Mock dry-run，真实调用 0）。适用包：T203 运行器 / T205 评分与门禁。
> 本文件只规定「绑定与失败语义」，不改任何已冻结的分母、阈值、gate 版本与业务 API。

## 0. 为什么需要这份契约

T205 review §3 的两条限制（trace 无评测身份、产物无检索证据 id）与 R2 的 8 条非阻断发现
（①失败无产物 ②错误码只靠消息前缀 ③run_id 缺失可放行 ⑤probe 复跑写仓库）在**真实准入前**
必须补齐。本契约把「身份 / 证据 / 配置摘要 / 失败产物 / 错误码 / run_id」的绑定口径固定下来，
使 ``trace_integrity`` 能在 Mock dry-run 真 PASS，而**缺任何一项仍然 fail closed**。

## 1. 评测身份绑进 trace（trace identity）

六个字段（与冻结 ``TraceRecord`` 同名字段，不新增字段）：

| 字段 | 取值来源（P2） | gate 侧期望值 |
|---|---|---|
| `run_id` | `run_p2` 生成本次 run id（或调用方显式传入） | `run_manifest.run_id` |
| `dataset_version` | `P2RunDataset.identity.dataset_version`（H2 manifest 权威） | 同左 |
| `manifest_sha256` | `P2RunDataset.identity.manifest_sha256` | `run_manifest.corpus_manifest_sha256` |
| `pipeline_version` | `observability.versioning.pipeline_version()`（qa/rag/tokenizer 同一口径） | `run_manifest.pipeline_version` |
| `index_revision` | 灌库/发布完成后的产品 revision（`adapter.product_revision()`） | `run_manifest.index_revision` |
| `config_hash` | 本契约 §3 的**绑定摘要** | `run_manifest.config_hash` |

实现（additive，业务代码零改动）：

- `observability.tracer.trace_identity(**fields)`：在请求上下文的 contextvar 里绑定身份；
  只接受上述六个字段名，值 `str/int` 且非空，未知字段/空值 → `ValueError`；
- `start_trace` 在**创建时快照**该身份；组装 `TraceRecord` 时先落身份、再让业务 `annotate`
  覆盖（业务埋点优先，身份不能伪造未被埋点声明的字段）；
- `ProductEvalAdapter` 在 `create_app` 之后追加一个最外层 HTTP middleware，把绑定好的身份
  放进 contextvar —— 产品路由、业务服务、`main.py` 均未修改；
- **要么全绑、要么不绑**：`bind_trace_identity` 要求六字段齐全，缺一项整体拒绝；运行器在
  gate 身份缺失时**不绑**（记 `binding.missing`），trace 因此仍会 `version_binding` 失败。

证据（Mock dry-run 实测）：`test_mock_dry_run_binds_identity_and_passes_trace_integrity`
把真实 run 产物接进 `build_gate_run` + `evaluate_p2_hard_gates(require_trace=True)`，
`gate_status["trace_integrity"] == "pass"`；未绑身份时同一路径仍然 fail（见 §8）。

## 2. 引用证据 id（citation evidence）

产品响应里的 `sources[].source_id` 就是**来源单元 id**（unit 级）；评测侧在**产品返回之后**
用只读 SQL 把它解析成稳定证据身份，写入该轮的 `product.evidence`：

| 字段 | 含义 |
|---|---|
| `unit_id` | 来源单元 UUID（`source_units.id`，与产品 `source_id` 同一值） |
| `unit_key` / `locator` | 单元业务键与定位（sheet/row/heading/page…） |
| `document_id` / `version_id` / `version_number` | 所属文档与版本身份 |
| `state` / `active` | 版本状态、是否为该文档当前有效版本 |
| `in_run` | 该文档是否属于本次 run 灌入的文档集合 |
| `verified` / `reason` | 是否满足 `locator 非空 ∧ active ∧ published ∧ number≥1 ∧ in_run` |

判定（`p2_scoring.citation_evidence_status`）：

- 只对 `kind == "answer"` 的轮次要求证据；任一轮缺证据、任一引用未 `verified`、
  或整份产物没有作答轮 → `complete = False`（unknown），**不当通过**；
- `complete = True` 才允许调用方把 `citation_evidence_complete=True` 传给
  `evaluate_p2_gate`；判定默认值仍是 `False`；
- H2 聚合路径用 `include_case_ids=False` 输出（不含 case_id，符合"只出聚合"）。

**能力边界（如实）**：本项证明的是「引用落在本轮灌入的、当前有效的来源单元上，且带稳定
unit/locator/版本身份」，不是「引用 ⊆ 模型本轮检索候选集」——后者由产品自身的
`_validate_answer`（引用必须在允许集合内）与 gate 的 `citation_evidence` 硬门禁
（在提供 `retrieved` 时）负责。本包**不新增 API 字段**：`SourceSummary`/`SourceView`
未改，解析在产品库侧只读完成。

## 3. config_hash（确定性绑定摘要）

```text
config_hash = sha256(canonical_json({
  binding_version, dataset_version, manifest_sha256, label_version,
  pipeline_version, index_revision, provider, gate_version, gate_config_hash
}))
```

- `p2_scoring.binding_config_hash`：组件规范化（去空白、键排序、类型收紧）后 canonical JSON
  → 64 位 hex；**同配置同 hash，任一组件变化必变**；
- `provider` 只含身份字段（provider/model/实现名/传输名），**不含调用计数**（否则每跑一次都变）；
- **索引身份**由 `index_revision`（产品 revision）+ `pipeline_version` 组件里的 rag schema /
  index cache / tokenizer 版本共同确定，不另立第二份"索引版本"；
- 缺任一组件（含 `gate_version`/`gate_config_hash`）→ `binding_input_missing`，不 quietly 跳过；
- 写入位置：`run_manifest.binding` + 顶层 `config_hash`、`summary.binding`、
  `gate.json.binding`；`P2GateDecision.binding_config_hash` 记录判定所依据的摘要
  （与 `P2GateDecision.config_hash`＝gate 配置摘要语义不同，不混用）；
- 门禁核对（`evaluate_p2_gate`）：`run_manifest.config_hash` 缺失 → `config_hash_unbound`；
  scorecard 声明的 `config_hash` 与之不一致 → `config_hash_binding_mismatch`（均 unknown 不放行）。

## 4. 失败也写产物

runner 的产物写入改为「先校验、后落盘，校验失败也落盘」：

| 场景 | 结果 |
|---|---|
| 发送后中止（产品 error / 超时 / 取消） | 照旧写 5 件套，`failure` 带 `stage/case_id/turn/item_id/ticket` |
| 产物校验失败（网络分解对不上、缺 detail） | 写 `run_manifest/summary/run_result/gate`（+ holdout 聚合），`status=aborted`、`stop_code=<稳定码>`、`failure.stage=artifact_validation`，然后**抛出**同一稳定码 |
| 校验未通过的网络计数 | `summary.network.available=false` + `code`；`summary.providers=null`；`gate.json.real_sends_allowed=false`（不把未核对计数当实测事实） |

## 5. 稳定错误码

| 码 | 触发点 |
|---|---|
| `provider_network_detail_mismatch` | 顶层出站 ≠ detail 汇总，或 detail 分解之和 ≠ 汇总，或 detail 缺失 |
| `run_id_missing` | `run_p2(run_id=...)` 传入空/非 str；门禁侧 manifest 缺 `run_id` → `run_binding_missing` |
| `binding_input_missing` / `binding_input_invalid` | `binding_config_hash` 组件缺失/为空/类型非法 |
| `artifact_validation_failed` | 预留：产物写入层面的失败（当前校验路径用上面的具体码） |

`P2RunError(ValueError)` 带 `.code`/`.detail`，消息以码开头（既有 `pytest.raises(match=...)` 仍成立）。

## 6. run_id 必填

- `run_p2` 显式给 `run_id` 时必须是**非空 str**，否则在**建 run 目录/发送之前**抛
  `P2RunError("run_id_missing")`；
- 不给则由 runner 生成 `p2run-<16 hex>`，并写入 manifest / 每条 trace / 每条请求行；
- `evaluate_p2_gate`：manifest 缺 `run_id` → `run_binding_missing`（unknown）；
  scorecard 声明了别的 run → 仍为 `run_binding_mismatch`。

## 7. 产物字段（additive）

新增/变化（旧键全部保留，键名不变的语义也不变）：

- `run_manifest.json`：顶层 `suite/dataset_version/dataset_sha256/corpus_manifest_sha256/
  business_date/index_revision/pipeline_version/gate_version/gate_config_hash/label_version/
  created_at/case_count/config_hash/dataset_path/trace_store`（可直接喂 `build_gate_run`）、
  `business_dates`、`binding`、`pipeline.trace.identity_bound`、公开 run 额外写 `dataset.jsonl`；
- `summary.json`：`binding`、`citation_evidence`、`network.available/code`；
- `gate.json`：`binding`、`citation_evidence`、`artifact_validation`、`failure`；
- `cases.jsonl`：每轮 `product.evidence`（仅公开 run；H2 不写逐题行）。

**版本策略**：不升既有 `schema_version`（`p2-run-manifest/v0.1` 等）——只是**新增键**，
旧键名与语义一律不变（additionalProperties 兼容）；依赖新键的消费方必须同时校验
`binding.binding_version`（`p2-binding/v0.1`）。绑定公式的组件集合一旦变化就**必须**升
`P2_BINDING_VERSION`，否则同 hash 会被误当成同一份身份。

## 8. Fail-closed 矩阵

| 缺失/不一致 | 结果 |
|---|---|
| 未绑 trace 身份 | `trace_integrity` = `version_binding` 硬失败 |
| 只绑部分身份 | 整体不绑（`bind_trace_identity` 拒绝），同上 |
| 缺 `gate_version`/`gate_config_hash` | `binding.complete=false`、`trace_identity_bound=false`，门禁 `config_hash_unbound`/`gate_config_unbound` |
| 引用无 unit/locator/未核实 | `citation_evidence_status.complete=false` → `citation_evidence_unavailable` |
| manifest 缺 `run_id` | `run_binding_missing`（unknown） |
| 网络分解不一致 | `provider_network_detail_mismatch`（抛错 + 失败产物） |

## 9. 零真实调用与边界

本包全部为离线：Mock 产品应用 + Mock provider + 隔离目录；真实调用 **0**、未读 `.env`/H1/H2、
未联网、未改 `fixtures/`/`gate.py`/`p2_ingestion.py`/业务 API。真实 live 链（`P2Gate` 预留与结算）
仍归 T206 正式 pilot，不在本契约范围内。
