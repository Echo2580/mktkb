# T007 R1 定向复验（独立验收）

- 对象：`08536ed`（`p0/T007 baseline diff report R1`，父 `7e9ee34`；首轮对象 `6447b85`）。
- 环境：Windows/PowerShell；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；`.\.venv\Scripts\python.exe -B`；串行；零真实调用；未读 `.env`。
- 证据：`verify/T007/R1-min-sample-probe.txt`、`R1-regression-boundary.txt`（本次新增；首轮证据与 `evidence/T007/03` 未改）。
- **总判定：PASS**。MEDIUM-1 / LOW-1 / LOW-2 均已修复；回归全绿；R1 commit 边界合规；MEDIUM-2 未被越权修改（仍按约定留给 T008a）。

## 1. MEDIUM-1（min_sample 取 0）— PASS

- 默认配置真实链独立重渲染（只读 `%TEMP%\t007-baseline-report`，零调用）：
  `exit=3 / quality=unknown / 42 unknowns`；提示为
  `retrieval=8（Recall@10/text）、answer=8（value_hit/text）、refusal=1（refusal_precision/all）、runtime=8（p95_latency_ms/text）`。
  无 `= 0（`，旧 `最小 stratum 分母 = 0` 不再出现。
- `cost_per_case_cny`（all/exact/text）denominator=0、observed=None、status=unknown；`refusal_recall` 同样 denominator=0、observed=None，status=pass 是 `gate.py` 既有行为（自 `6447b85` 未改），提示已把它按零样本排除。
- 独立合成验证（非交付测试）：全零指标 + 多 stratum 指标 → `retrieval=6、answer=2`；只有全零指标 → “全部指标为零样本…不给数值提示”；同组多指标取该组最小正分母（4 而非 9）。15/15 probe checks PASS。
- fixture 配置重渲染：`exit=2 / quality=fail`；`retrieval=8、answer=8、refusal=8、runtime=8`，与 `05-r1-min-sample.txt` 一致。
- 重渲染产物与交付 `%TEMP%` 产物逐字节一致（md `16111` LF bytes / 191 lines；html `23303` LF bytes；sha256 见证据）。
- 措辞观察（不阻断）：提示仍含“（分母 0）”作为排除理由，不是 min_sample 值；若把“不含 0”理解为字面禁止字符 0，则需再改措辞。

## 2. LOW-1（41→42）— PASS

- `evidence/T007/01-baseline-identity.txt:50` 已是 `42 passed`，并注明“原文误写 41，按 04-tests.txt 的 42 项改正”；`04-tests.txt:8` 仍为 42。无误导。

## 3. LOW-2（p95 方向语义）— PASS

- `report.py` 模块 docstring、`MetricDelta`、`_delta_status` 均写明 `regressed/improved` 只是数值方向；markdown 第 4 节与 html diff 段新增同义说明；p95 note 改为“质量/门禁状态 unknown … 只是数值方向”。独立重渲染确认 md/html 均含该说明；新增测试通过。

## 4. 回归（串行 1 次）

| 范围 | 结果 |
| --- | --- |
| `test_report.py` | 20 passed, 0.48s |
| `test_baseline.py` | 25 passed, 0.27s |
| 两文件合计 | 45 passed, 0.69s |
| `backend/tests/evaluation` | 278 passed, 25.75s；0 failed/0 error |
| `backend/tests` 全量 | 1551 passed, 771.86s（0:12:51）；0 failed/0 error，exit 0 |

## 5. 边界

- `git show --name-status 08536ed` 仅 5 个路径，全部在 rework-R1 §2 允许列表：`report.md`、`report.py`、`test_report.py`、`evidence/T007/01`、`evidence/T007/05`。
- `baseline.py` 无 diff；`diff_runs` 与 `require_release_baseline` 与 `7e9ee34` 逐字节一致（未修 MEDIUM-2）；`gate_v0_1.json` blob 两侧同为 `cfbbe0a0…`（仍 unapproved）。
- 无新依赖；工作树在新增本 review/R1 证据前干净；未 commit/push；未改 `_index.md`/其他包产物。

## 6. 未覆盖/残余

- 无 live 模型/OCR/embedding/rerank；未读 `.env`；未运行 T008 CLI；HTML 仅静态字节/内容检查，未开浏览器。
- `refusal_recall` 质量表 `status=pass`（零样本、observed=None）是 R1 前的 gate 行为；若要求表内也显式 unknown，应另开 gate 包，T009 不应据此认为拒答召回通过。
- 全量墙钟 771.86s 高于交付记录 713.90s，属环境波动；无失败/超时。
