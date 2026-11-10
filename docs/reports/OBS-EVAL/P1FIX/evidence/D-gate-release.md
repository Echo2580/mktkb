# P1FIX-D 证据：发布放行与当前 run / 当前配置 / 审批证据的一致性

> 依据：`docs/reports/OBS-EVAL/P1/review.md` §7 #59、`p1-report.md` §5。本项只改放行判定，
> 不修改任何 gate 阈值、不修改 `gate_v0_*.json`、不降低门槛；`RunDiff`/`to_dict()` 字段结构不变。

## 1. 原风险（可复现）

修复前 `evaluation/report.py::diff_runs` 的放行判定只做四件事：跨版本→False、`gate.exit_code != 0`→False、
`baseline.approval is None`→False、`comparison != release`→False；否则 `release_allowed=True`。漏洞：

1. `gate=None`（未提供当前门禁结果）时仍可能 `release_allowed=True`；
2. 不校验 gate 是否绑定**当前 run**（旧 run 的 gate 结果可复用）；
3. 只比 `gate_version` 字符串，**同 gate_version 改阈值内容**不会拒绝；
4. 不重核 baseline 审批时刻的配置内容哈希（审批后漂移仍可放行）；
5. baseline 缺 gate 快照/审批与快照不一致的路径没有显式原因码。

反例测试（新增 `backend/tests/evaluation/test_diff_release_gate.py`，15 用例）覆盖：
同 gate_version 改阈值、旧 run 的 gate、缺 gate、gate/审批缺失、审批后配置漂移、跨版本比较；
合法场景（已审批 + 当前 gate 绑定当前 run + 配置哈希一致 + 非跨版本）仍 `release_allowed=True`。

## 2. 修改（`backend/src/mktkb/evaluation/report.py`）

- 新增 `_baseline_approved_config_hash()`：旧 schema 的 baseline gate 快照没有 config 哈希，
  从 `baseline.run_dir/gate.json` 重核——其 canonical JSON 的 SHA-256 必须等于审批绑定的
  `gate_result_sha256`，再取 `quality.gate_config_hash`；文件缺失/被改 → fail closed
  （`baseline_gate_config_unverifiable`）。
- 新增 `_release_blocked_reason()`，放行证据链顺序判定，稳定原因码包括：
  `explicit_cross_version_analysis_only` / `baseline_unapproved` / `baseline_gate_missing` /
  `baseline_approval_gate_mismatch` / `current_gate_missing` / `current_gate_run_mismatch` /
  `current_gate_gate_version_mismatch` / `current_gate_exit_<n>` / `current_gate_quality_missing` /
  `gate_config_drift` / `gate_config_drift`（当前 gate 与配置）/ `baseline_gate_config_drift` /
  `comparison_not_release`。
- `diff_runs` 统一调用该判定；`require_release_baseline` 文档同步。
- 模块 docstring 写明**配置更新后的规则**：配置内容（阈值/min_sample/status 等任意字节）一变，
  `config_hash` 就变；旧 gate 结果与旧审批只证明“旧配置下通过”，必须重新 gate 评估并重新审批，
  即使 `gate_version` 没变。

## 3. 修复后验证

### 3.1 反例/合法场景单测

`pytest backend/tests/evaluation/test_diff_release_gate.py backend/tests/evaluation/test_report.py -q`
→ 全部通过（test_diff_release_gate 15 + test_report 20；完整数字见 `08-tests-and-evals.md`）。

### 3.2 真实 P1 产物只读复核（`evidence/data/D-verify-release-chain.json`）

用真实 `baseline bc6f6f906db1` + 其 live run + `gate_v0_2.json`（只读 var/**）：

| 场景 | release_allowed | 原因码 |
| --- | --- | --- |
| 合法一致（审批/gate/run/配置哈希全一致，gate exit 0） | **True** | null |
| 同 gate_version 改阈值内容（Recall absolute_min 0.855→0.9） | **False** | `gate_config_drift` |
| 旧 run 的 gate 结果（run_id 不匹配） | **False** | `current_gate_run_mismatch` |
| 缺失当前 gate（gate=None） | **False** | `current_gate_missing` |

### 3.3 合法放行路径不回归

- `test_p0_acceptance.py`（CLI approve→diff 端到端）仍通过；
- `test_t112_gate_baseline.py`（approved/unapproved、baseline 身份/审批/list）仍通过；
- `test_report.py` 合法场景断言保留（仅按新证据链补齐“当前 gate + gate.json 审批证据”输入）。

## 4. 剩余问题 / 设计说明（如实）

- 旧 schema 的 baseline 快照无 `gate_config_hash` 字段，放行时依赖 `baseline.run_dir/gate.json`
  作为审批证据；该文件缺失/被篡改时**拒绝放行**（有意的 fail closed）。本次未改
  `baseline.py` schema（E 工作流占用；且改 schema 会触发 baseline 格式版本升级）；后续若做
  schema bump，可把 `gate_config_hash` 直接写进 `BaselineGate` 并从 report 直接读取。
- 跨 pipeline_version 比较仍固定 `release_allowed=False`（只分析），未放宽。
- 未批准任何 answer/refusal/runtime 阈值；`gate_v0_2.json` 未被本次修改。
