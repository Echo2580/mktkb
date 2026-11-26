# C1-P4 证据索引

全部为合成/Mock 证据；零真实调用、零出站。生成环境：`backend` 目录、
`.venv\Scripts\python.exe`（Python 3.12.7）。

| 文件 | 内容 / 生成方式 |
|---|---|
| `pytest-collect.txt` | `python -m pytest tests/evaluation/test_p2_evidence_axes_adapter_v2.py --collect-only -q` |
| `pytest.txt` | 同一测试模块在进程级出站守卫下运行（`PYTHONPATH=<p4>/evidence/netguard`、`C1P4_GUARD_OUT=<p4>/evidence/zero-call.json`） |
| `zero-call.json` | `pytest.txt` 那次进程的守卫计数（外部 socket/DNS/http/httpx 全 0、`blocked=0`） |
| `netguard/c1p4_netguard.py`、`netguard/sitecustomize.py` | 进程级出站守卫（只读注入，不联网） |
| `netguard/positive_control.py` | 守卫正对照：外部 TCP + 外部 DNS 各尝试一次 |
| `netguard-positive-control.txt` / `.json` | 正对照输出与守卫计数（两次尝试均 `blocked`） |
| `counterexample_probe.py` | 反例矩阵探针：复用测试模块的合成构造器，逐类跑适配器并记录固定码；AST 统计固定码断言 |
| `counterexamples.json` | 22 类反例（期望码 == 实测码）、正例状态/计数、键空间探针（2 轴/受影响 1）、66 处固定码断言、43 个测试函数 |
| `counterexamples-guard.json` | 反例探针进程的守卫计数（全 0） |
| `protected_compare.py` | 保护件比对：C 冻结 12 + 15 tracked modified + R2 基线 2084 个 untracked 文件 |
| `protected-after.json` | 当前 HEAD/分支/暂存/15 tracked 哈希/C 冻结 12 哈希/untracked 树摘要 |
| `protected-compare.json` | 比对结论（`unchanged`）与明细 |

重放命令（仓库根目录）：

```powershell
$ev = "docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\c1-1\p4\evidence"
$ng = "$ev\netguard"
$py = ".venv\Scripts\python.exe"

# 1) 测试（守卫注入）
$env:PYTHONPATH = (Resolve-Path $ng).Path
$env:C1P4_GUARD_OUT = (Join-Path (Resolve-Path $ev).Path "zero-call.json")
Push-Location backend
& "..\$py" -m pytest tests/evaluation/test_p2_evidence_axes_adapter_v2.py -q
Pop-Location

# 2) 守卫正对照
& $py (Join-Path $ng "positive_control.py")

# 3) 反例矩阵
& $py (Join-Path $ev "counterexample_probe.py") > (Join-Path $ev "counterexamples.json")

# 4) 保护件
& $py (Join-Path $ev "protected_compare.py") --out (Join-Path $ev "protected-compare.json") --after (Join-Path $ev "protected-after.json")
```

`pytest.txt` / `counterexamples.json` 若由 PowerShell 重定向生成，可能带 UTF-8 BOM；
本次已去除，内容未改。
