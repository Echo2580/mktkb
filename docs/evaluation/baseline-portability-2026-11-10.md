# P1 baseline 可移植性：归档 / 校验 / 恢复（2026-11-10，E 工作流）

> 结论：`var/eval/**` 里 gitignored 的 P1 release baseline `bc6f6f906db1` 现在有了可执行、
> fail-closed 的证据链**归档 / 校验 / 恢复**流程（零真实调用）。归档只移植既有证据，
> **不建立新 baseline 身份**；恢复只重写 `baseline.json.run_dir`。
> 旧 baseline 不得冒充新 pipeline 的发布基线：新 pipeline 必须重新 live run + 重新审批。

## 1. 现场事实（只读核对，2026-11-10）

P1 release baseline（`pipeline_version=08166b113481`，gate v0.2，b0 live 40 题）：

| 项 | 值 |
| --- | --- |
| baseline_id | `bc6f6f906db1`（= sha256(六要素字面拼接)[:12]） |
| 身份六要素 | dataset_version=`b0:b0-2026-11-04:bd4f0f7ccc6e`；pipeline_version=`08166b113481`；mode=`live`；scope=`retrieval_only`；gate_version=`mktkb.gate.v0.2`；corpus_sha256=`6889915267c5…2755b6` |
| run_id | `b0-live-20261109T111828086143Z-0efd058b` |
| 源目录 | `var/eval/baselines/bc6f6f906db1/`、`var/eval/runs/<run_id>/`（两者均 gitignored） |
| 审批关系 | approver=`主人`；gate_result_sha256=`c9fcbbb67aa8…7421742b`；gate_exit_code=0；quality_status=`pass`；approved_at=`2026-11-09T12:00:14.018+00:00` |

已核对的文件 SHA-256（归档必须逐字节一致）：

| 文件 | sha256 |
| --- | --- |
| baseline/baseline.json | `1924faf86fad52d4495f07c64e2db1a9262a1299a2b0817fe9d604de3ad6b07a` |
| baseline/approval.json | `80113647d0b640d37b3f6c86c6b67758de7e907f51e3a6ff47dc42b1af9aad43` |
| run/run_manifest.json | `010e6cc025fd1d180e489d4ca1f5b006b7de83c359e28351c70e086dda543b68` |
| run/cases.jsonl | `0a4ba7fb90c38a22383edf3ad93a80df4fd12476e1bc0b588b3ac9182fd17966` |
| run/summary.json | `f8542e661a5031d3baa06e3b40424d8ab93b46a105ba9f44cd5180382358a993` |
| run/gate.json | `da208e34eb15cb98cc38bc4ceea9558c4d7875ce7b3e1a118f7eadaece36c1e7` |

`baseline.json` 内的 `artifact_sha256` 与上面三件套一致；`baseline.gate.gate_result_sha256`
= `approval.gate_result_sha256`，且归档的 `run/gate.json` 解析后 canonical 摘要也等于它
（恢复/校验时三方互证，见 §4）。

## 2. 必要产物与归档布局

归档（`archive_baseline` / `baseline archive`）写出：

```text
<out>/archive_manifest.json                  # 工具 schema、身份、审批关系、逐文件 sha256、源路径、排除项
<out>/baseline/baseline.json                 # 原字节（identity / artifact_sha256 / gate 快照不变）
<out>/baseline/approval.json                 # 存在时原字节（审批证据；缺失 = approved=no，不伪造）
<out>/run/run_manifest.json                  # RUN_ARTIFACTS 原字节
<out>/run/cases.jsonl
<out>/run/summary.json
<out>/run/gate.json                          # run 目录存在 gate.json 时归档
```

`archive_manifest.json`（`schema_version=mktkb.baseline.archive.v0.1`，UTF-8、
`ensure_ascii=False`、按键排序）字段：

- `baseline_id` / `identity`（六要素）/ `run_id` / `suite`；
- `source.baseline_dir` / `source.run_dir`（源路径，便于审计；归档本身不含绝对路径依赖）；
- `has_approval` + `approval`（baseline_id / run_id / gate_result_sha256 / gate_exit_code /
  gate_version / quality_status / approver / approved_at）+ `gate`（gate 结果摘要）；
- `files[]`：每个归档文件的 `path` / `sha256` / `bytes`；
- `excluded[]`：run 目录里**未**打包的条目名（`traces.sqlite3*`、`index/`、
  `gate_proposal.json`、`holdout_audit.json` 等，按实际存在登记）；
- `archived_at`、`tool`、`note`。

不打包：`traces.sqlite3*`（trace 库）、`index/`（索引缓存）、`gate_proposal.json`（校准
提案，不是审批证据）、`holdout_audit.json`；`suite=holdout` 或 manifest 标记 holdout
（`holdout_details=true` / `holdout_labels_sha256` 非空）的 run **整体拒绝归档**。

## 3. 命令

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"   # 与既有评测纪律一致；本流程零真实调用
$py = ".\.venv\Scripts\python.exe"; $m = "-B -m mktkb.evaluation.cli"
# 1) 归档（--root 默认 var/eval/baselines；--out 必须不存在）
& $py -B -m mktkb.evaluation.cli baseline archive --baseline bc6f6f906db1 --root var/eval/baselines --out D:\tmp\p1-baseline-archive
# 2) 只读校验（文件 sha256 / baseline↔run 身份 / approval↔gate 关系）
& $py -B -m mktkb.evaluation.cli baseline verify --archive D:\tmp\p1-baseline-archive
# 3) 恢复到隔离根（run 默认写到 <root>/../runs/<run_id>，可用 --runs-root 覆盖）
& $py -B -m mktkb.evaluation.cli baseline restore --archive D:\tmp\p1-baseline-archive --root D:\tmp\fresh\eval\baselines
# 4) 恢复后可用（approved=yes 表示审批证据一起移植，不是重新审批）
& $py -B -m mktkb.evaluation.cli baseline list --root D:\tmp\fresh\eval\baselines
```

## 4. 校验与恢复语义

`verify_archive` / `restore_baseline` 的证明链（全部只读源，全部 fail closed）：

1. `archive_manifest.json` schema 兼容；登记路径只能是 `baseline/` 或 `run/` 下的相对 POSIX
   路径，拒绝 `..` / 反斜杠 / 绝对路径；磁盘文件集合必须恰为「登记文件 + manifest」，
   拒绝未登记文件与符号链接；
2. 每个文件实际字节数、sha256 必须与清单一致（同字节数翻转也能识别）；
3. `baseline.json` 可重建 `Baseline`（schema / `baseline_id` 由 identity 重算 / approval
   绑定校验），且与 manifest 的 `baseline_id` / `identity` / `run_id` / `suite` 一致；
4. 归档 `run_manifest.json` 的身份六要素与 run_id 必须等于 baseline；suite 非 holdout，
   且无 holdout 明细标记；
5. 三件套实际字节摘要 = `baseline.artifact_sha256`（建立 baseline 时记录）；
6. 有 `approval.json` 时 manifest 审批关系逐字段一致；无审批时 `approval=null`、
   `has_approval=false`（approved=no，不冒充）；
7. 归档 `gate.json` 解析后的 canonical 摘要必须等于 `baseline.gate` / `approval` 记录的
   `gate_result_sha256`（只改 gate.json 并同步改清单哈希也会被拒）；
8. `restore_baseline` 在 1–7 通过后才写盘：目标 baseline 目录或 run 目录**任一已存在即拒绝**；
   `baseline.json` 仅顶层 `run_dir` 改为新 run 目录，其余键逐键不变；写后立即
   `load_baseline(...)` + `Baseline.load_run()` 复核（identity / run_id / artifact 摘要），
   并断言恢复前后 identity / approval / artifact_sha256 / gate 快照完全相同；任何失败删除
   本次新建目录并抛 `BaselineArchiveError`。

## 5. 隔离验证（pytest tmp_path + 真实 baseline 副本）

- `backend/tests/evaluation/test_baseline_portability.py`：**21 passed**（合成 run/baseline，
  `tmp_path` 隔离，无 skip/xfail）——归档→校验→恢复往返、6 个文件逐个同字节数篡改拒绝、
  未登记文件拒绝、gate 摘要不绑定审批拒绝、缺产物/源 run 被篡改拒绝、holdout 三种标记拒绝、
  目标已存在拒绝、缺 approval.json 时 approved=no、CLI `archive/verify/restore/list`
  成功路径与 exit 3 路径、`baseline --help` 可见新子命令、archive/restore 前后源目录摘要不变。
- 真实 baseline 隔离实测（只读 `var/**`，副本与归档都在 gitignored 临时目录）：把
  `bc6f6f906db1` + run 复制到 `backend/.pytest-tmp/p1fix-e-manual/work-*/src/`，CLI
  `archive`（files=6, approved=yes）→ `verify`（ok）→ `restore` 到另一 tmp 根 →
  `baseline list` 输出 `approved=yes`；`load_baseline`/`load_run` 通过（cases=40）；恢复后
  baseline.json 仅 `run_dir` 不同；篡改 cases.jsonl 后 verify/restore 均 exit 3 且不建目标目录；
  重复 restore exit 3；源 `var/eval/baselines` 与 run 三件套+gate.json 摘要前后一致。
- 定向回归：`test_baseline.py + test_cli.py + test_t112_gate_baseline.py + test_report.py +
  test_baseline_portability.py` = **114 passed**。

## 6. 反例与边界

- **归档不是新 baseline**：同一 `baseline_id` 仍只绑定一个 `run_id`；恢复只是把同一份证据
  搬到新根，`approval.json` 原样移植（不会变成「新审批」），docs/审批链以
  `gate_result_sha256` 绑定具体一轮 run / gate 结果为锚点。
- **旧 baseline 不得冒充新 pipeline**：代码改动（`pipeline_version` 变化）后，旧
  `bc6f6f906db1` 只能做跨版本分析（`compare_with`，`release_allowed=False`），不能作为新
  pipeline 的发布基线；diff/放行仍按既有 report 守卫拒绝。
- **无法零真实调用重建新基线**：新 pipeline / 新 gate 配置的 baseline 必须重新 live run +
  重新审批（真实 embedding/rerank 调用与预算/GO 授权）；本流程刻意不提供「伪造/重算」入口，
  该缺口记为待办。
- 不覆盖旧证据：归档目标目录、恢复目标目录已存在即拒绝；所有写入都先校验后落盘。
- 仓库不提交归档产物：`var/**` 与 `backend/.pytest-tmp/**` 均 gitignored；归档输出放测试
  临时目录。若需随 PR 分发归档，需主人单独决策存放位置与脱敏（本次任务范围外）。
- 本流程不读 `.env`、不调 provider/网络、不新增生产依赖、不改 API 字段结构；holdout 逐题
  明细与本地 labels 永不进入归档。
