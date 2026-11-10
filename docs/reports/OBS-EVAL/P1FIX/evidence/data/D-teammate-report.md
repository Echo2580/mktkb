# D 工作流报告：发布放行与当前配置/运行/审批一致性（P1 #59）

状态：**已修复并自测通过**。分支 p1/fix-retrieval，基线 HEAD 3eec866。全程零真实 provider、未读 .env、未碰 var/docs.evidence/GO/账本、未改 gate_v0_*.json。

## 1. 原失败 / 风险（review §7 #59）

旧 `diff_runs` 放行判定（HEAD `report.py:492-508`）只要求：非跨版本 + baseline 已审批 +（可选）当前 gate exit 0。
问题：
- **缺当前 gate 也放行**：`gate=None` 时直接跳过 exit_code 检查（`report.py:494` 条件 `gate is not None`）。
- **只比 gate_version**：配置内容（阈值/min_sample/status）变化不改变 gate_version，旧 gate 结果与旧审批可被继续复用。
- **审批后配置漂移不重核**：`BaselineGate`（`baseline.py:238-301`）快照只含 exit_code/quality_status/gate_status/hard_failures/gate_version/gate_result_sha256/run_id/suite，**没有配置内容哈希**，approval 也不记录。

## 2. 根因

1. 放行证据链不完整：未校验 gate 绑定当前 run、未校验质量层 `gate_config_hash == 当前配置 config_hash`。
2. baseline schema 未把“审批时刻的配置内容哈希”落盘，导致无法直接重核；需从审批绑定的 `gate_result_sha256` 反查具体一份门禁结果（run 目录 `gate.json`）取得当时 `quality.gate_config_hash`。
3. 旧 elif 级联顺序把“缺 gate/旧 gate”当放行，不 fail closed。

## 3. 修改点（都是最小、有针对性；baseline.py/cli.py/gate.py 未改）

- `backend/src/mktkb/evaluation/report.py:15-39`：模块 docstring 写清**放行证据链**（11 条件）与**配置更新规则**（内容哈希变 → 旧 gate 结果/旧审批不得复用，必须重评+重批）。
- `report.py:488-493`：`_canonical_json_sha256`（与 `baseline.gate_result_digest` 同口径）。
- `report.py:496-531`：`_baseline_approved_config_hash`：优先读基线快照 `gate_config_hash`（为后续 schema 预留）；旧 schema 读 `baseline.run_dir/gate.json`，其 canonical JSON SHA-256 必须 == 审批绑定的 `gate_result_sha256`，再取 `quality.gate_config_hash`；缺失/解析失败/摘要不一致 → `baseline_gate_config_unverifiable`（fail closed，不能靠伪造文件解锁）。
- `report.py:535-579`：`_release_blocked_reason` 统一判定，稳定原因码：
  `explicit_cross_version_analysis_only` / `baseline_unapproved` / `baseline_gate_missing` / `baseline_approval_gate_mismatch` / `current_gate_missing` / `current_gate_run_mismatch`（run_id/suite/mode）/ `current_gate_gate_version_mismatch` / `current_gate_exit_<n>` / `current_gate_quality_missing` / `gate_config_drift` / `baseline_gate_config_unverifiable` / `baseline_gate_config_drift` / `comparison_not_release`。
- `report.py:585-645`：`diff_runs` 先解析 config（保留 gate_version 不一致即 raise 的既有语义），再统一判定；**`RunDiff` 与 `to_dict()` 字段结构不变，只新增 `release_blocked_reason` 取值**。
- `report.py:679-...`：`require_release_baseline` docstring 同步证据链（行为不变：False 即拒）。
- `backend/tests/evaluation/test_report.py:54,176-190,243-263,435-...`：合法放行场景补“当前 gate 绑定当前 run + `gate_config_hash` 与默认配置一致 + 写审批证据 `gate.json`”，既有断言全部保留；`make_gate` 增加 `gate_config_hash/gate_version/suite/mode` 参数；新增 `write_gate_json`。
- 新增 `backend/tests/evaluation/test_diff_release_gate.py`（15 用例）：合法放行、跑数结构不变、缺 gate、旧 run 的 gate、suite/mode 不匹配、exit 1、quality=None、gate_version 不匹配、同 gate_version 改阈值内容（旧 gate 结果）、审批后配置漂移、证据缺失、伪造 gate.json、快照缺失、跨版本只分析。

## 4. 验证命令与结果

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
.\.venv\Scripts\python.exe -B -m pytest backend\tests\evaluation\test_report.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\p1fix-d
```
- 基线（改前）`test_report.py`：**20 passed**。
- 改后 8 个文件合并：**224 passed / 0 failed**（17.8s）。
  分文件：test_report 20 / test_diff_release_gate 15（新）/ test_gate 80 / test_gate_quality 29 / test_t112_gate_baseline 13 / test_baseline 25 / test_cli 35 / test_p0_acceptance 7。
- 真实产物只读复核（不写 var）：已审批 baseline `bc6f6f906db1` + 其 run + `gate_v0_2.json` → `release_allowed=True`、`require_release_baseline` 通过（`gate.json` canonical 摘要 == approval `gate_result_sha256` = c9fcbbb6…）；模拟同 gate_version 内容漂移（config_hash 置 0*64）→ `release_allowed=False, baseline_gate_config_drift`。
- test_p0_acceptance #5（CLI：run→gate→approve→diff）端到端仍 `release_allowed=True`，说明修复未阻断合法发布路径。

## 5. 剩余问题 / 风险

1. `BaselineGate`/`BaselineApproval` 仍不记录 `gate_config_hash`（schema 限制，本任务禁改 baseline.py）。旧 baseline 的证据来自 run 目录 `gate.json`（其内容由审批绑定的 `gate_result_sha256` 认证）。若该文件丢失（归档/迁移只带三件套或跨机），合法旧 baseline 会被 fail closed 判为 `baseline_gate_config_unverifiable`——这是有意的安全默认值，但需主人决定是否补 schema。
2. `gate.json` 不在 `baseline.artifact_sha256` 覆盖范围；安全依据是审批摘要而非文件目录完整性。攻击者不能伪造摘要，但可删除文件导致拒放行（拒绝服务而非误放行）。
3. 配置漂移检测只覆盖 gate 配置；run manifest 的 pipeline `config_hash` 不在本任务范围。
4. 未改任何阈值/gate_v0_*.json、未批准 answer/refusal/runtime 阈值；仓库当前基线（approved 配置）内容不变。

## 6. 建议写进最终报告的结论

1. #59 已修复且未放松语义：放行需“当前 gate 绑定当前 run + exit 0 + gate_version 与质量层 gate_config_hash == 当前配置哈希 + 审批时刻配置哈希 == 当前配置哈希 + baseline 已审批且快照绑定”，缺 gate/旧 gate/漂移/跨版本均 fail closed 并给出稳定原因码；`RunDiff` 字段结构不变。
2. 回归 8 文件 224 passed（含新增 15 个反例、26 文件其它不受影响），CLI 端到端审批→diff 仍可合法放行。
3. 真实 P1 已审批 baseline `bc6f6f906db1` 在新逻辑下仍 `release_allowed=True`；同 gate_version 仅改内容立即被 `baseline_gate_config_drift` 拒绝（真实产物验证）。
4. 遗留风险：审批时配置哈希依赖 run 目录 `gate.json`；建议后续在 baseline schema 增加 `gate_config_hash`（schema bump，属 baseline.py 负责人工作），并在归档/恢复流程中把 `gate.json` 纳入必要产物（与 E 工作流联动）。
5. 本工作流未新增生产依赖、未真实调用 provider、未修改 API 字段结构。
