# P2-T207-FIX-S 独立验收 review（Q39 值匹配最小修复）

- 角色：T207-FIX-S 独立验收助手（全新上下文）；只读复核 + 复跑，零真实调用。
- 工作区：`D:/GPT项目/市场部AI知识库`，分支 `codex/p2-e2e`；审查时 HEAD=`b1bfa60`（FIX-B-R1，10:06 提交）。
- 工作区同时存在并行包 FIX-A 的在飞改动；本 review 已按 mtime/diff 区分，只判 FIX-S 三个文件 + 本包新目录。
- 复跑证据：`evidence/verify/01-default-identity.txt`、`02-q39-matrix.txt`、`03-p1-and-integration.txt`，探针 `verify_probe.py`。

## 结论

**接收（阻断 0）**。默认参数路径与 HEAD 逐值一致（30,912 对 0 分歧）；Q39 修复只对「期望值内部显式空白」生效，错日期/错时间/拆位/非空白分隔全部拒绝；P1 183 passed、gate+quality 109。唯一联动项是 FIX-A 的 `test_p2_score_run.py` 冻结了修复前的 b0 39/1，应由 A-R1 改 2 个断言（不是 S 的缺陷）。

## 逐条判定

| # | 项 | 判定 | 关键证据 |
|---|---|---|---|
| 1 | 范围 | **PASS** | 只改 3 文件 + 本包目录；未改 fixtures/PM/GO/p2_runner/p2_live/gate/runner；无 skip/xfail；无 commit |
| 2 | 默认行为不变 | **PASS（关键）** | HEAD 副本 vs 工作区：115 case / 69 取值 / 448 文本 / 30,912 对 → check_value 0、pattern 0、score_case 0 分歧 |
| 3 | Q39 正确且不过宽 | **PASS** | 24 个变体 0 个 value_hit 判定错误；非空白分隔不命中；无「应 fail 却 pass」 |
| 4 | P1 无影响 | **PASS** | 183 passed；gate 80 + quality 29 = 109；exact 契约只覆盖 stratum=exact，Q39=ocr |
| 5 | 集成影响量化 | **PASS（已如实披露）** | `test_p2_score_run.py` 1 failed/7 passed；HEAD 39/1（Q39 fail）→ 本包 40/0（Q39 pass） |
| 6 | 报告/证据一致性 | **PASS（3 处非阻断笔误）** | 60 行；sha16/行数/148-790-67-0/183 均可复现 |
| 7 | 合规 | **PASS** | 零真实出站；未读 .env/H1/H2；未 commit |

## 1 范围（PASS）

- `git diff --numstat`：`scorers.py +62/−12`、`p2_scoring.py +5/−1`、`test_p2_scoring.py +112/−0`，与报告 §3 逐值一致；sha16 与行数也逐值一致（`aeb42766d5976e77`/1276、`1a20cf0e00170de0`/2206、`085a05476673c0d0`/1030）。
- mtime 聚类：S 三文件 10:02–10:04；FIX-A 的 `product_adapter.py`/`cli.py`/`test_p2_score_run.py` 为 09:42–09:54；PM/GO/预算文档为 09:56，`T207-PM-decisions-01.md` 10:06（PM 自己的 §8/§9），均早于/独立于 S。
- `git status -- fixtures`、`p2_runner.py`、`p2_live.py`、`gate.py`、`runner.py` 均空；GO/预算/账本 diff 中没有 `cross_explicit_space`/Q39 修复内容。
- 新增测试只用 `@pytest.mark.parametrize`；无 skip/xfail。HEAD=`b1bfa60` 是 FIX-B-R1 的提交，S 三文件仍为 M（未 commit）。仓库含 docx 二进制，`git log -S` 不可用；改以 HEAD 源码副本无该参数（见 §2）+ 三文件仍为 M 证明 S 未 commit。
- **非阻断观察**：新测试从 `mktkb.evaluation.p2_public_cases`（FIX-A 的未跟踪文件）取 `load_b0_cases`。若 S 先于 A 落盘，`test_p2_scoring.py` 会 collection error。建议 A 先提交，或 S 改用 `dataset.load_cases(b0.jsonl)` 解耦。

## 2 默认行为不变（PASS，关键项）

方法：`git archive HEAD backend/src/mktkb` → **工作区外**临时目录；两个独立进程分别以 `PYTHONPATH=<HEAD>/backend/src` 与 `PYTHONPATH=backend/src` 加载，只调默认参数（不传 opt-in）；语料为 6 个 fixture 文件（b0 40 + regression 7 + badcase 13 + T207 R1 52 + R2 2 + R3 1 = 115 个 case 行；R1 与 b0 有重复 case_id，未去重，重复行只会重复比较、不影响结论）。

- `check_value`：69 取值 × 448 文本 = **30,912 对，分歧 0**。
- `_value_pattern`：69 条编译模式，**分歧 0**。
- `score_case`：115 case × 2 outcome（answer/no_answer）= **230 个 CaseResult（逐 check 全字段），分歧 0**。
- Q39 默认口径：HEAD `value_hit=fail`、本包 `value_hit=fail`（未被 opt-in 污染）。
- opt-in 窄度：全部 69 个取值中**只有** `2026-10-30 16:00` 一个取值的结果会变（7/448 文本变体）；不含内部空白的 68 个取值 **0 变化**；`_explicit_space_needle` 的 needle 与 `normalize_text(...).replace(" ","")` 全量一致。
- 生产代码内唯一打开点：`p2_scoring.py:881`；`gate.py:1286/1485`、`runner.py:1578/1622/1802/2112/2119` 均未传该参数（`git grep cross_explicit_space` 在 src 内只命中 p2_scoring:881，在 tests 内只命中 S 新测试）。
- 复现开发证据 03：把其 probe 原文抽出后在 HEAD/本包各跑一次，得到 `148 case / 67 取值 / 790 对 / 0 分歧 / 4 条含空白期望值`，与报告一致。

## 3 Q39 修复正确且不过宽（PASS）

走 P2 路径 `score_public_case`（`P2CaseScore`）逐个喂 24 个变体，value_hit 判定错误 **0**：

- 正确：单空格 / 多空格 / Tab / 换行 / 全角 / 日期符两侧带空格 → `value_hit=pass`、case=pass。
- 拒绝：错日期、错年份、错时间、缺时间、缺日期、`1 6:00`、`2026-10-3 0`、尾部多数字 `16:000`、截断 `16:0`、顺序颠倒、被 `12026` 包住 → `value_hit=fail`、case=fail。
- 窄度：`2026-10-30，16:00`、`2026-10-30T16:00`、`2026-10-30 与 16:00` 均不命中 → 只在显式空白处跨空白，不是「任意文本穿越」。
- 两处需如实记录：①「无空白」`2026-10-3016:00` 的 `value_hit=pass`，但 case 仍 fail（既有 `value_no_fabricated` 把 3016 判为编造数字）→ 不存在错写法被判 pass；②`16:00:30` 命中属既有子串口径（旧口径同样命中），ISO T / 中文日期改写 / 12 小时制在范围外仍 fail。

## 4 P1 无影响（PASS）

- 点名 6 文件逐跑：`test_p2_scoring 38 / test_p2_gate 23 / test_gate 80 / test_gate_quality 29 / test_p2_public_controls 6 / test_p0_acceptance 7` = **183 passed**；gate+quality=**109**。
- `_gate_exact_value_contract` 在 `gate.py:1466` 显式跳过 `stratum != "exact"`；Q39 的 stratum=ocr；`P2_B0_EXACT_IDS` 只有 Q01..Q24；exact 组内 0 条含内部空白的期望值。故硬门禁既不新失败也不新通过。
- 红态也复现：HEAD 源码 + 本包新测试 = **6 failed / 32 passed**（5 条 TypeError + 1 条 Q39 断言），证明缺口真实存在、修复必要。

## 5 集成影响（PASS，量化）

- 独立跑 `backend/tests/evaluation/test_p2_score_run.py`：**1 failed / 7 passed**，失败在 334 行 `assert matrix["tallies"]["b0"]["passed"] == 39` → 实际 40。
- 独立复算同一矩阵（不改测试；HEAD 侧只把 S 三文件回退到 HEAD，FIX-A 模块保持工作区版本）：本包 `b0 = 40/0/0`、Q39 row=pass；HEAD 源码 `b0 = 39/1/0`、Q39 row=fail；negative 8、boundary 6、u 10 两边不变 → 影响**只有 Q39 一条**。
- 影响文件/行号：`backend/tests/evaluation/test_p2_score_run.py:332-336`（332-333 注释、334 passed==39、335 failed==1）；该文件是 FIX-A 的未跟踪新文件，不在 S 的可改清单。修正应为 `passed==40`、`failed==0`，并删掉「不改 scorers.py」的注释。PM 的 `T207-PM-decisions-01.md §9-1` 已把该项列入 A-R1。

## 6 报告/证据一致性（PASS，附笔误）

- `report.md` 60 行；sha16、行数、+62/−12 等全部对得上；`evidence 02` 的 183/109、`evidence 03` 的 148/67/790/0 均可复现。
- 限制陈述如实：`forbidden_values` 未 opt-in（当前 0 条含内部空白禁止值，见证据 01）；日期改写/12-24 小时制/区间不在范围。
- 非阻断笔误：①报告写「@405491c」，审查时 HEAD 已因 FIX-B-R1 变为 `b1bfa60`（写报告时属实，现已过时）；②§3 说「命中无空格」容易被读成 case 通过，实际 case 因 `value_no_fabricated` fail，建议注明；③范围外清单未列 ISO T；④基线 172 未独立复跑，但与 27+23+80+29+6+7 及 6 failed/32 passed 的红态算术一致。

## 7 合规（PASS）

- 本次复核只跑纯函数/离线 pytest，未执行任何 live/provider 路径，未发生真实出站；`test_p0_acceptance` 自带的 provider/socket/.env 守卫用例通过。
- 本 review 未读 `.env`/H1/H2；未改任何代码、夹具、期望标签、账本/预算/GO；只写 `T207-FIX-S/review.md` 与 `evidence/verify/`；未 commit。

## 8 非阻断发现（按优先级）

1. **A-R1 必做**：`test_p2_score_run.py:334/335` 改 40/0 + 注释同步（否则 A 无法「套件全绿」接收）。
2. **提交顺序**：S 新测试 import FIX-A 的 `p2_public_cases`；A 未落盘时 S 测试无法 collect。先 A 后 S，或改从 `fixtures/evaluation/b0.jsonl` 直接 `load_cases`。
3. **可选加固**：Q39 真实答案若写 `2026-10-30T16:00` 或中文日期仍 fail；如认为属真实写法，列入 T209 的口径扩展，不在本包放宽。
4. **报告措辞**：§3「无空格命中」补一句「case 仍因 value_no_fabricated fail」，避免误读。

## 9 NOT-RUN

- 全仓 pytest、H2、live/真实 provider、真实 OCR 未跑（超出本包，且要求零真实调用）。
- 172 基线未单独重跑（红态 6/32、绿态 183 已实测，基线数由 HEAD 27 条测试 + 其余 145 条算术得到）。
- 未审计开发者的进程级操作（只能从 diff/证据/夹具状态判断零真实调用）。

## 10 最终建议

**接收**。S 的修复是必要的最小修复：默认口径 0 分歧、Q39 只放开显式空白、P1 全绿、影响面已如实披露。唯一联动项 `test_p2_score_run.py` 的 2 行断言归 FIX-A R1 闭环；建议 A 先提交、S 后提交，或在 S 提交前把测试夹具来源改为已提交的 `dataset.load_cases`。
