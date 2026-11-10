# T113 验收证据 04：命令、环境偏差与自证

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（验收方，非交付物）

## A. 起点

```text
git rev-parse --abbrev-ref HEAD        -> p1/fix-retrieval
git log --oneline -4                   -> 22f098e, e52d0da, 5d675bf, 9edc003
git show -s --format='%H %P' 9edc003   -> 9edc003a... 10bb42bdd...
git diff 9edc003..HEAD --stat          -> 仅 .claude/handoffs/**（PM 簿记）
git status --porcelain                 -> tracked clean；未跟踪：_scratch/ 与既有 T114 handoff
```

`report.md`/证据 01 写“父提交 fcc3434”是笔误：`fcc3434` 是祖父方向 3 个 commit
（`10bb42b` 的父为 `bec959c`，再父为 `fcc3434`）；实际父提交是 `10bb42b`。

## B. 验收环境偏差（不改交付物）

1. `backend\.pytest-tmp` 对本进程只读：`mkdir` 返回 `PermissionError`；因此 pytest
   的 `--basetemp` 用 `_scratch\...`，不是 handoff 的 `backend\.pytest-tmp\...`。
2. 本沙箱把 POSIX `0o700` 映射为创建者自己也无法列目录的 ACL；pytest `tmp_path` 与
   评测 `tempfile.mkdtemp` 会因此失败。验收用 `_scratch/pytest_runner.py` 与
   `_scratch/eval_shim.py` 在**进程内**把目录 mode 改为 0o777（仅验收环境 workaround），
   测试代码/业务代码/交付物未动。
3. `docs\evidence\**` 对本进程只读：全量中 43 个 T09 acceptance 与 3 个 budget 锁测试
   以 `PermissionError` 失败；这是环境阻断，不计为 T113 失败（见证据 03 §A）。
4. 证据目录用工作区 `write` 工具落盘；`pwsh` 进程对 `docs\reports\...\verify\T113`
   同样受只读限制。

## C. 实际命令（cwd=仓库根）

```text
# 本包 / observability
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
.\.venv\Scripts\python.exe -B _scratch\pytest_runner.py backend/tests/observability/test_routes.py -q -p no:cacheprovider --basetemp _scratch\pt113v-routes2
.\.venv\Scripts\python.exe -B _scratch\pytest_runner.py backend/tests/observability -q -p no:cacheprovider --basetemp _scratch\pt113v-obs
.\.venv\Scripts\python.exe -B _scratch\pytest_runner.py backend/tests -q -p no:cacheprovider --basetemp _scratch\pt113v-full2
# 独立探针
$env:T113_PROBE_ROOT=(Resolve-Path _scratch\probe-root).Path
.\.venv\Scripts\python.exe -B _scratch\probe_t113.py
.\.venv\Scripts\python.exe -B _scratch\readonly_probe.py _scratch\readonly-root
.\.venv\Scripts\python.exe -B _scratch\export_openapi.py _scratch\openapi.json
# P0 对照
.\.venv\Scripts\python.exe -B _scratch\eval_shim.py run  --suite b0 --mode local --out _scratch\eval\T113\b0
.\.venv\Scripts\python.exe -B _scratch\eval_shim.py gate --run _scratch\eval\T113\b0 --config docs\evaluation\gate_v0_1.json
.\.venv\Scripts\python.exe -B _scratch\eval_shim.py run  --suite badcase --mode local --out _scratch\eval\T113\badcase
.\.venv\Scripts\python.exe -B _scratch\eval_shim.py gate --run _scratch\eval\T113\badcase --config docs\evaluation\gate_v0_1.json
.\.venv\Scripts\python.exe -B _scratch\eval_shim.py run  --suite regression --mode local --out _scratch\eval\T113\regression
.\.venv\Scripts\python.exe -B _scratch\eval_shim.py gate --run _scratch\eval\T113\regression --config docs\evaluation\gate_v0_1.json
.\.venv\Scripts\python.exe -B _scratch\compare_runs.py > _scratch\compare_result.json
```

全量前内存：`(Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue`
= **4368 MB ≥ 2048**，满足 §11D 门槛（非内存 NOT-RUN）。同一时间只跑了一套 pytest。

## D. 只读/隐私的补充自证

- `_scratch/readonly_probe.py` 输出 `equal=true`：业务库、trace 主库、trace `-wal`、
  `run_manifest.json` 的 SHA-256 与 mtime 在 4 个 GET 前后完全一致。
- `_scratch/probe_t113.py` 的响应递归扫描：`secret_in_any_body` 全 false、
  `case_id_in_any_body` 全 false、`json_suffix_keys=[]`、`question/answer/context/cases/
  case_id` 键均不存在；holdout 响应 `holdout_detected=true`、`details_withheld=true`、
  `cases` 键不存在。
- 未读取 `.env`（所有 Settings 显式 `_env_file=None`）；未打印/使用凭据；未打开
  P1-HOLDOUT 逐题内容；未 commit/push/切分支/修改交付物。

## E. 残余

- 全量 0 failed 的验收项在本环境 **BLOCKED**（`docs\evidence` 只读导致 46 项环境失败），
  不是 PASS；T113 相关测试全绿，见证据 03 §A/D。
- OpenAPI 无机读 `securitySchemes`/`security`（仅 401/403 说明），见证据 02 §G；
  属 LOW 口径缺口，建议 T114 处理。
