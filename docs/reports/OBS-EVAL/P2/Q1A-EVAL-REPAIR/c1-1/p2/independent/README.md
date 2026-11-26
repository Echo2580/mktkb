# C1-P2 独立验收探针：复现说明

本目录是 C1-P2（`p2_empty_scope_proof.py`）的独立验收证据。所有探针只使用合成 envelope 与仓内公共数据；不读真实 H2 题面/标签/答案/私有密文/key/`.env`/保管会话；私密外部项只算 SHA256/字节数，不解密。

## 0. 环境

```powershell
$p = "D:\GPT项目\市场部AI知识库"
$env:MKTKB_NO_DOTENV="1"
$env:PYTHONDONTWRITEBYTECODE="1"
$env:PYTHONIOENCODING="utf-8"
```

除 netguard 外，脚本用 `$p\.venv\Scripts\python.exe -B` 运行；涉及测试模块的脚本在 `$p\backend` 下运行。

## 1. 差分复算（72 例 / 12 分歧）

```powershell
cd $p\backend
& $p\.venv\Scripts\python.exe -B $p\docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\c1-1\p2\independent\11-divergences.py
```

输出 `11-divergences.json`：12 both proven / 48 both not proven / 11 extension / 1 stricter / 0 uncoded；冻结 SHA 前后 `fba6e606…`。

## 2. fail-closed（267 探针）

```powershell
cd $p\backend
& $p\.venv\Scripts\python.exe -B $p\docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\c1-1\p2\independent\12-failclosed.py
```

输出 `12-failclosed.json`：267 probes / 0 failed；AST 仅 1 处 `proven=True`；无网络 import。

## 3. 覆盖率

```powershell
cd $p\backend
& $p\.venv\Scripts\python.exe -B $p\docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\c1-1\p2\independent\13-coverage.py
```

输出 `13-coverage.json`：7/7 要求形状；72 例；22 shape 标签 = 17 组合 + 5 缺口标签；未覆盖 query_state 事件路径等。

## 4. 零调用 + 三路正对照

```powershell
& $p\.venv\Scripts\python.exe -B $p\docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\c1-1\p2\independent\14-netguard-run.py
```

- `14a-control.txt` / `14a-control-guard.json`：socket / DNS / httpx 三路故意出站全部被拦并记账（`blocked=3`）。
- `14b-suite.txt` / `14b-suite-guard.json`：88 passed；退出时 socket/DNS/httpx 全 0。
- `14c-isolated.txt` / `14c-isolated-guard.json` / `14c-isolated-import.json`：stub `mktkb` 只 import 新模块；未加载 provider/冻结模块；最小可证明 envelope proven。

## 5. 保全与终态

```powershell
& $p\.venv\Scripts\python.exe -B $p\docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\c1-1\p2\independent\10-snapshot.py start
& $p\.venv\Scripts\python.exe -B $p\docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\c1-1\p2\independent\15-final-compare.py
```

`15-final-compare.py` 会重新生成 `10-snapshot-end.json` 并对比：
- C 冻结 12、R2 28、Q1a-1 38、只读 2、15 tracked、14 个开发文件；
- 7 个外部/私密项（只比 hash/字节）；
- 外来 untracked 2086 文件；
- `my_products`（24 项）与 `concurrent_products`（P1 并行 3 项）；
- 终态 `verdict = true`。

## 6. 正式测试

```powershell
cd $p\backend
& $p\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_p2_empty_scope_proof.py -q -p no:cacheprovider --basetemp .pytest-tmp/c1p2-verify
```

原始输出见 `05-pytest-independent.txt`：`88 passed, 1 warning`，退出 0。

## 7. 结论文件

- `../independent-review.md`：逐项 PASS/FAIL、12 分歧逐类裁决、R2 翻轴分析、残余 R 码、边界声明。
- `../review-aggregate.json`：机器可读聚合。
