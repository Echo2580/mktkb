# P2-T207-FIX-S 开发报告：Q39「日期 + 时间」值匹配缺口最小修复（零真实调用）

- 角色：T207-FIX-S 开发助手（全新上下文）；分支 codex/p2-e2e @ 405491c（未 commit/push）。
- 边界：真实调用 **0**（纯函数评分 + 冻结夹具；无 provider/网络/OCR/.env/DB）；未改 `fixtures/**`、期望标签、账本/预算/GO、
  `p2_runner.py`/`p2_live.py`/`product_adapter.py`/`cli.py`、产品回答代码；无 skip/xfail；只跑点名用例（+1 次相邻影响核对，§6-1）。

## 1 结论

| Q39（冻结期望 `2026-10-30 16:00`） | 修复前 | 修复后 |
|---|---|---|
| 正确回答：单空格 / 多余空白 / 全角 | fail（唯一失败项 value_hit） | **pass**（P2CaseScore=pass） |
| 错日期 / 错年份 / 错时间 / 缺时间 / `1 6:00` | fail | fail（不变） |
| 共享 scorer 默认口径（P1 路径） | 不命中 | 不命中（逐字不变） |

## 2 复现与本因（证据 01：修复前后同一 probe）

1. `check_value` 把期望值 `.replace(" ","")` 成针 `2026-10-3016:00`；`_value_pattern` 规定「数字与数字相邻不插 `\s*`」，
   模式退化为 `2026\s*\-\s*10\s*\-\s*3016\s*:\s*00` —— 正文里的 `2026-10-30 16:00` 永远不命中，与答案对错无关。
2. 调用链（`inspect` 定位）：`p2_scoring.score_public_case:878` → `scorers.score_case:1033` → `scorers._value_checks:535`（把 expected 送进值检查） → `scorers.check_value:329`；反证：修复前喂**正确**回答仍 `status=fail`（只 value_hit fail）。

## 3 改动（sha16 = 文件 sha256 前 16 位）

| 文件 | 行数 | diff | sha16 | 改动 |
|---|---|---|---|---|
| `evaluation/scorers.py` | 1276 | +62/−12 | `aeb42766d5976e77` | 新增 `_explicit_space_needle`（折叠空白并记录空白位置）；`_value_pattern(needle, *, cross_space_at=())` 只在这些位置放开数字-数字跨空白；`check_value`/`_value_checks`/`score_case` 增 **默认关闭** 的 `cross_explicit_space=False` 并透传；默认分支逐字保留原实现。 |
| `evaluation/p2_scoring.py` | 2206 | +5/−1 | `1a20cf0e00170de0` | `score_public_case`(:881) 显式 `score_case(..., cross_explicit_space=True)` —— 全仓唯一打开 opt-in 处。 |
| `tests/evaluation/test_p2_scoring.py` | 1030 | +112/−0 | `085a05476673c0d0` | 只增 §12，共 11 条新用例（§5）。 |

opt-in 不是"数字间一律可跨空白"，而是"只在期望值内部本来就有空白处跨空白"：命中 `2026-10-30 16:00`/多空格/全角/无空格，不命中 `2026-10-30 1 6:00`。

## 4 对 P1 无影响的证明（证据 03）

1. 默认路径逐字不变：`cross_explicit_space=False` 仍走 `normalize_text(expected).replace(" ", "")` + `_value_pattern(needle)`。
2. 全仓夹具差分（HEAD 源码副本 vs 本包，**只调默认参数**）：148 case 行 / 67 个取值 / 790 个「取值 × 文本变体」对 →
   `check_value` 结果分歧 **0**、编译出的 67 条正则分歧 **0**。
3. P1 调用点无一处传新参数：`gate.py:1286`（禁止值泄漏）、`gate.py:1485`（`exact_value_contract`）、`runner.py:1578/1622/1802/2112/2119`。
   硬门禁 `exact_value_contract` 只覆盖 `stratum=="exact"`，Q39 是 `ocr` → P1 既不新失败也不新通过。
4. 全仓含内部空白的期望值仅 4 条（Q27/RG001/RG003 两侧非数字，旧口径已命中；只 Q39 是数字-数字）；含内部空白的禁止值 0 条。

## 5 测试（证据 02）

- 新增 11 条：正确回答 pass（单空格/多空白/全角）；错日期、错年份、错时间、缺时间、`1 6:00` 全 fail；3 条既有样本（`12`/`B区1号`/
  `3 个工作日`）opt-in 开关前后一致；`score_case` 默认参数对 Q39 仍 fail（钉住共享默认行为）。
- 基线（三文件全 HEAD）**172 passed** → HEAD 源码 + 新测试 **6 failed / 32 passed**（红） → 修复后 **183 passed**，exit 0：
  `test_p2_scoring` 38 / `test_p2_gate` 23 / `test_gate` 80 / `test_gate_quality` 29（gate+quality=**109**）/ `test_p2_public_controls` 6 / `test_p0_acceptance` 7。

## 6 限制 / 未决 / 回退

1. **相邻文件期望值陈旧（需其归属方改 2 行）**：`tests/evaluation/test_p2_score_run.py:332-336` 把"Q39 必然 fail"写进冻结计数
   （`b0 passed==39 / failed==1`，注释还写着"不改 scorers.py"）。修复后矩阵应为 **40/0**，该用例现 1 failed / 7 passed（`assert 40 == 39`）；
   本包允许改文件清单不含它，故只报不改。
2. `forbidden_values` 仍走默认严格口径（未开 opt-in）；当前 0 条含内部空白的禁止值 → 无可观测差异；将来若出现属"更严"的另一类口径变化，需单独决策。
3. 只修"期望值内部显式空白"这一种缺口；`2026年10月30日 16:00` 改写、12/24 小时制、区间值不在范围内；未评估真实 OCR/模型答案写法；未跑全仓/gate/H2/live。
4. 回退：`git checkout -- backend/src/mktkb/evaluation/{scorers.py,p2_scoring.py} backend/tests/evaluation/test_p2_scoring.py`，并删除本报告目录（未 commit）。

## 7 证据入口（3）

1. `evidence/01-reproduction-before-after.txt`：修复前后同一 probe 输出（HEAD 源码副本 vs 本包）+ 调用链定位。
2. `evidence/02-pytest.txt`：基线 172 / 红 6 / 修复后 183 / 相邻文件 1 failed，含命令与原始摘要。
3. `evidence/03-p1-impact.txt`：含空白期望值清单、790 对差分（0 分歧）、P1 调用点、硬门禁分析、probe 源码。