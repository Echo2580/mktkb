# E：baseline 归档/恢复/重建可执行流程与隔离验证（report）

- 状态：**已修复并自测通过**（未 unresolved；仅「新 pipeline 零真实调用重建基线」为待办）
- 分支/HEAD：`p1/fix-retrieval` @ `3eec866`；只读保护文件、`var/**`、GO/预算/账本未动；未 commit/push；
  未读 `.env`、未调 provider/网络、未新增生产依赖、未改 API 字段结构。
- 改动文件（均在任务允许范围）：
  - `backend/src/mktkb/evaluation/baseline.py`（新增归档/校验/恢复，fail closed）
  - `backend/src/mktkb/evaluation/cli.py`（新增 `baseline archive/verify/restore` 子命令与 help）
  - `backend/tests/evaluation/test_baseline_portability.py`（新增，21 用例）
  - `docs/evaluation/baseline-portability-2026-11-10.md`（新增：产物/版本/哈希/审批/流程/反例）
- 未改：report.py、gate.py、conversations/、runner.py、fixtures、`docs/evidence/**`、`var/**` 原产物。

## 1. 实现

- `archive_baseline(baseline_id, root, out_dir)`：`load_baseline` → 先读 run_manifest 判身份与
  holdout → `Baseline.load_run()` 复核身份/run_id/三件套摘要 → 打包 `baseline.json`、
  `approval.json`（存在时）、RUN_ARTIFACTS 三件套、`gate.json`（存在时）→ 写
  `archive_manifest.json`（schema=`mktkb.baseline.archive.v0.1`，记录六要素、run_id、
  gate_result_sha256/approver/approved_at、逐文件 sha256+bytes、源路径、excluded、时间）。
  目标已存在拒绝；先写暂存目录并 `verify_archive` 自校验，通过才上架（失败不留半成品）。
  不打包 `traces.sqlite3*`、`index/`、`gate_proposal.json`、`holdout_audit.json`；
  `suite=holdout` 或 manifest holdout 标记（`holdout_details`/`holdout_labels_sha256`）整体拒绝。
- `verify_archive(archive_dir)`：schema/相对路径/文件集合（拒绝未登记文件与符号链接）/
  逐文件实际 sha256+bytes / baseline 可重算 baseline_id / run_manifest 六要素=baseline /
  三件套字节=baseline.artifact_sha256 / approval↔manifest 关系一致 / 无审批时 approved=no /
  `gate.json` canonical 摘要=`baseline.gate`(`approval`).gate_result_sha256。
- `restore_baseline(archive_dir, root, runs_root=None)`：先 verify；目标 baseline 目录或 run
  目录任一已存在即拒绝；run 默认写 `<root>/../runs/<run_id>/`；`baseline.json` 仅改顶层
  `run_dir`（其余键逐键断言不变），approval 原字节复制；写后 `load_baseline`+`load_run`
  复核并断言 identity/approval/artifact_sha256/gate 快照不变；失败删除本次新建目录并抛错。
- CLI 子命令（`--help` 可见）：`baseline archive --baseline <id> [--root var/eval/baselines] --out <dir>`、
  `baseline verify --archive <dir>`、`baseline restore --archive <dir> --root <目标根> [--runs-root <dir>]`；
  输出 UTF-8 JSON（ensure_ascii=False）；失败 exit 3、只打印 `ERROR:` 不抛栈。

## 2. 命令示例（真实 baseline 只读；归档/输出都在临时目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
& .\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli baseline archive --baseline bc6f6f906db1 --out backend\.pytest-tmp\p1fix-e-manual\archive
& .\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli baseline verify  --archive backend\.pytest-tmp\p1fix-e-manual\archive
& .\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli baseline restore --archive backend\.pytest-tmp\p1fix-e-manual\archive --root backend\.pytest-tmp\p1fix-e-manual\dst\eval\baselines
& .\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli baseline list    --root backend\.pytest-tmp\p1fix-e-manual\dst\eval\baselines
```

## 3. 隔离验证结果

- `pytest backend\tests\evaluation\test_baseline_portability.py -q -p no:cacheprovider
  --basetemp backend\.pytest-tmp\p1fix-e`：**21 passed**（tmp_path 隔离、无 skip/xfail：
  往返 / 6 个归档文件逐个同字节数篡改拒绝 / 未登记文件拒绝 / gate 摘要不绑定审批拒绝 /
  缺产物与源 run 被篡改拒绝 / holdout 三种标记拒绝 / 目标已存在拒绝 / 缺 approval.json 时
  approved=no / CLI 成功与 exit 3 路径 / help 可见 / 源目录摘要前后不变）。
- 回归：`test_baseline.py + test_cli.py + test_t112_gate_baseline.py + test_report.py +
  test_baseline_portability.py` = **114 passed**（0 failed/0 error）。
- 真实 `bc6f6f906db1` 隔离实测（复制到 `backend/.pytest-tmp/p1fix-e-manual/work-*/`，源只读）：
  archive `files=6 approved=yes` → verify `ok` → restore 到另一 tmp 根 → `baseline list`
  `approved=yes`；`load_baseline`/`load_run` 通过（cases=40）；恢复后 baseline.json **仅
  run_dir 变**；篡改 cases.jsonl 后 verify/restore 均 exit 3 且不建目标目录；重复 restore exit 3；
  `var/eval/baselines/bc6f6f906db1` 与 run 三件套+gate.json 摘要前后逐字节不变。

## 4. 必要产物 / 哈希 / 批准关系（审计口径）

- baseline `bc6f6f906db1`，run `b0-live-20261109T111828086143Z-0efd058b`；六要素
  dataset `b0:b0-2026-11-04:bd4f0f7ccc6e` / pipeline `08166b113481` / mode `live` /
  scope `retrieval_only` / gate `mktkb.gate.v0.2` / corpus `6889915267c5…`。
- 归档文件哈希（与源逐字节一致）：baseline.json `1924faf8…6b07a`、approval.json `80113647…aad43`、
  run_manifest `010e6cc0…543b68`、cases.jsonl `0a4ba7fb…fd17966`、summary `f8542e66…58a993`、
  gate.json `da208e34…c36c1e7`。
- 批准关系：approver=`主人`、`gate_result_sha256=c9fcbbb6…7421742b`、exit 0、quality pass；
  `baseline.gate` 与 `approval` 及归档 `gate.json` canonical 摘要三方互证；恢复不改审批、
  也不是重新审批（缺 approval.json 时 approved=no，不冒充）。

## 5. 剩余问题 / 待办

1. **新 pipeline 需重新 live run + 重新审批**：`pipeline_version` 变化后旧 baseline 只能
   `compare_with` 跨版本分析（`release_allowed=False`），不得冒充发布基线；E 流程不提供伪造/重算入口。
2. **零真实调用无法建立新基线**：重建需真实 embedding/rerank 与预算/GO 授权；本次仅移植既有证据，
   该缺口如实记录为待办，未伪造。
3. 归档产物未入库：`var/**`、`backend/.pytest-tmp/**` 均 gitignored；若需随 PR 分发归档，
   需主人决策存放位置与脱敏（本次任务范围外，未上传/未提交任何敏感数据）。
4. Windows 上暂存目录上架已加有限重试（杀软/索引器瞬时占用）；仍失败则 fail closed。
