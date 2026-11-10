# P1FIX-E 证据：baseline 可移植性（归档 / 校验 / 恢复）与隔离验证

> 依据：`docs/reports/OBS-EVAL/P1/review.md` §6、`p1-report.md` §5（`var/eval/**` gitignored，
> fresh clone 不可见）。不修改 `var/**` 原产物、不自动上传/提交任何敏感数据、不包含 Holdout 明细。

## 1. 原问题

`var/eval/baselines/bc6f6f906db1`（baseline.json+approval.json）与其 run
（`var/eval/runs/b0-live-20261109T111828086143Z-0efd058b` 的 `run_manifest.json/cases.jsonl/summary.json/gate.json`）
均在 gitignored `var/eval/**`；fresh clone 无 `baseline list`、无法复核审批/身份/产物，旧 baseline
不可移植，也不能被独立验收者直接复跑。

## 2. 修改（新增命令，不动既有语义）

| 文件 | 修改 |
| --- | --- |
| `backend/src/mktkb/evaluation/baseline.py` | 新增 `archive_baseline / verify_archive / restore_baseline` 与 `BaselineArchiveError`、`archive_manifest.json`（schema `mktkb.baseline.archive.v0.1`）；fail closed。 |
| `backend/src/mktkb/evaluation/cli.py` | 新增 `baseline archive/verify/restore` 子命令与 `--help`；失败 exit 3、只打印 `ERROR:`。 |
| `backend/tests/evaluation/test_baseline_portability.py` | 新增 21 用例（tmp_path 隔离）。 |
| `docs/evaluation/baseline-portability-2026-11-10.md` | 新增：必要产物/版本/哈希/批准关系/流程/反例/边界。 |

归档内容（6 文件）：`baseline.json`、`approval.json`、`run_manifest.json`、`cases.jsonl`、
`summary.json`、`gate.json`；**不打包** `traces.sqlite3*`、`index/`、`gate_proposal.json`、
`holdout_audit.json`。`suite=holdout` 或 manifest 带 holdout 标记
（`holdout_details` / `holdout_labels_sha256`）的 run **整体拒绝归档**。
`restore` 只重写 `baseline.json.run_dir` 到新位置，identity/approval/artifact 摘要/gate 快照逐键不变；
目标目录已存在一律拒绝，不覆盖旧证据。

## 3. 隔离验证（真实 `bc6f6f906db1`，源只读）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli baseline archive --baseline bc6f6f906db1 `
  --root var\eval\baselines --out .claude\handoffs\_scratch\p1fix\E-demo\archive
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli baseline verify --archive .claude\handoffs\_scratch\p1fix\E-demo\archive
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli baseline restore --archive .claude\handoffs\_scratch\p1fix\E-demo\archive `
  --root .claude\handoffs\_scratch\p1fix\E-demo\eval\baselines
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli baseline list --root .claude\handoffs\_scratch\p1fix\E-demo\eval\baselines
```

实测输出（2026-11-10）：

```text
archive baseline_id=bc6f6f906db1 run_id=b0-live-20261109T111828086143Z-0efd058b suite=b0 files=6 approved=yes
archive ok baseline_id=bc6f6f906db1 run_id=... files=6 approved=yes schema=mktkb.baseline.archive.v0.1
restored baseline_id=bc6f6f906db1 ... approved=yes files=6
baseline_id=bc6f6f906db1 run_id=... suite=b0 pipeline_version=08166b113481 approved=yes
```

- `load_baseline` + `Baseline.load_run()` 在恢复根通过（cases=40，身份/三件套摘要复核）；
- 恢复后 baseline.json 仅 `run_dir` 变化（1714→1753 字节），其余键逐键断言不变；
- 源 `var/eval/baselines/bc6f6f906db1` 与 run 三件套+gate.json 摘要前后逐字节不变；
- 篡改任一归档文件字节 / 未登记文件 / 符号链接 / 缺 gate.json / 重复 restore → verify/restore 拒绝
  （exit 3）且不建目标目录；缺 approval.json 时 `approved=no`，不冒充已审批；
- 21 个 pytest 用例 + 114 passed 回归（见 `08-tests-and-evals.md`）。

## 4. 必要产物 / 哈希 / 批准关系（审计口径）

- baseline `bc6f6f906db1`；run `b0-live-20261109T111828086143Z-0efd058b`；
- 六要素：dataset `b0:b0-2026-11-04:bd4f0f7ccc6e` / pipeline `08166b113481` / mode `live` /
  scope `retrieval_only` / gate `mktkb.gate.v0.2` / corpus `68899152…`；
- 归档逐文件 sha256+bytes 记入 `archive_manifest.json`；approval→`gate_result_sha256`→
  `gate.json` canonical 摘要三方互证；`approver=主人`、exit 0、quality pass。

## 5. 剩余问题 / 待办（如实）

1. **代码变化后旧 baseline 不得冒充新 pipeline 发布基线**：本次行为语义变化已把
   `QA_ENGINE_VERSION` 从 `s2-a-1` 升为 `s2-a-2`，新 run `pipeline_version` 由 `08166b113481`
   变为 `d3ca88d2c515`；旧 baseline 只能 `compare_with` 跨版本分析（`release_allowed=False`）。
   新 P1 release baseline 必须：真实 live run + gate 重评 + baseline approve（主人审批）；
   **本次未重签 GO、未执行真实调用，故新基线为待办**。
2. 零真实调用无法建立新 live baseline（需要 embedding/rerank 与预算/GO 授权）；未伪造/未重算。
3. 归档产物未入库（`var/**`、`backend/.pytest-tmp/**` 均 gitignored）；若需随 PR 分发，需主人
   决定存放位置与脱敏，本次未上传/未提交任何敏感数据。
