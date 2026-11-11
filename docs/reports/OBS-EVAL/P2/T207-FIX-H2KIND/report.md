# P2-T207-FIX-H2KIND 开发报告：expected_kind=refusal（P1 兼容值）按任一拒答结局匹配（P2-only、默认不变、零真实调用）
- 角色/边界：T207-FIX-H2KIND 开发助手（全新上下文），分支 `codex/p2-e2e` @ `3bc8347`，未 commit/push；
  真实调用 **0**；未改 `conversations/*`（并行包 FIX-CONFLICT-R1）、`p2_runner`/`p2_live`/业务代码/`fixtures/**`/期望/账本/预算/GO；无 skip/xfail。

## 1 结论
| 口径 | 修复前 | 修复后 |
|---|---|---|
| 合成 H2 30 题（answer 23 / conflict 1 / refusal 6），产品只回 not_found | **24/30**（6 题结构性 fail，恰好等于 min_pass 24 → 零余量） | **30/30** |
| 同一开关下"应该拒答却作答" | 6/6 fail | **6/6 fail（不变）** |
| P1 默认路径（90 题 × 24 组合 = 2160 次打分） | — | 与 HEAD **逐字节相同**（0 分歧） |

## 2 口径与开关（P2-only、opt-in、默认关闭）
- `scorers.py`：新增 `REFUSAL_COMPAT_KIND="refusal"` 与 `score_case(..., compat_refusal_kind=False)`；
  `_kind_checks` 仅在**开关打开 且 expected_kind=="refusal" 且 actual ∈ REFUSAL_KINDS** 时把 `kind_correct` 记 pass
  （evidence 追加 `compat:"refusal"`）。显式 kind（answer/not_found/no_answer/conflict/clarification）仍严格相等；
  `should_refuse`/`refusal_expected`/`refusal_unexpected` 判定逻辑一字未动。
- `p2_scoring.score_public_case`：显式 `compat_refusal_kind=True` —— **全仓唯一**打开处（+9 行）。
  `p2_score_run` 的三处 `score_public_case` 调用（公开 run ×2、H2 `holdout_case_scores_from_rows` ×1）都经过它，
  故 `p2_score_run.py` **无需改动**（任务书"必要时"条件未成立，保持最小改动）。
- P1：`runner.score_case` 五处调用均不传新参数 → 字面相等口径不变。

## 3 P1 默认差分（证据 02）
HEAD 源码（git ls-tree/show 导出 107 文件到 %TEMP%，不 stash、不切分支）vs 本包源码，同一 probe：
fixtures b0+badcase+regression（load_cases）+ holdout-questions（90 题）× 8 actual kind × 3 文本 = **2160 次 score_case**，
整份 JSON（checks/metrics/refused/status）sha256 **完全相同**。定点：fixtures 里的 H19/H30（expected_kind=refusal）
在默认路径下实际 not_found/no_answer **12/12 仍 fail**（只有字面 refusal 才 pass）——放宽确实只在 P2 入口。

## 4 合成 H2 前后（证据 01）
30 题内存构造（stratum 按 P2_HOLDOUT_STRATA 10-5-5-5-5；6 道 refusal = 5 negative + 1 cross_doc_security）。
after 臂走真实 H2 入口 `holdout_case_scores_from_rows -> score_public_case -> aggregate_holdout_bundle` = 30/30；
before 臂同批行只关开关 = 24/30；**翻转题数严格 6 且全为 expected_kind=refusal**。
对照臂（6 道 refusal 改由产品作答）= 24/6 → 开关只认"拒答结局"。两臂 blocks 均只有 `holdout_threshold_unapproved`（阈值未批 → unknown，未改阈值、非放行结论）。

## 5 测试（证据 03）
点名的四文件：93 passed（改动前）→ **108 passed**（+15：`test_p2_scoring.py` 13 条、`test_p2_holdout_scorecard.py` 2 条；只增，无删改）。
相邻影响：`backend/tests/evaluation` 全目录 + 3 个 P2 集成文件 **852 passed**（含 test_scorers 的字面相等 parametrize、
test_p2_score_run/test_p2_runner/test_p2_public_controls；既有 H2 合成实跑 23 pass/7 fail 不变——那些负样本是"故意作答"）。

## 6 限制 / 回退
1. 合成 H2 只覆盖**评分口径**：不走封存加解密、不跑产品、不分轮次；stratum 只作聚合分桶，不是对 H2 题面/标注的验证。
2. 仍未解决的真实缺口：H2 正例的检索/引用类 fail、其它 block 与阈值审批（`holdout_threshold_unapproved`）不在本包范围。
3. `docs/evaluation/p2-dataset-v0_1.md` 未改：该文只描述 dataset 结构，不描述评分口径；口径写进 `scorers` 模块 docstring 与 `score_case`/`score_public_case` docstring。
4. 回退：`git checkout -- backend/src/mktkb/evaluation/{scorers.py,p2_scoring.py} backend/tests/evaluation/{test_p2_scoring.py,test_p2_holdout_scorecard.py}`，删本目录。

变更文件（sha16）：`scorers.py` 1383 行 +34/−2 `4036fc7625ea40b4`；`p2_scoring.py` 2225 行 +9/−0 `4727689e3aea710e`；
`test_p2_scoring.py` 1319 行 +129 `734279a15c2f6ffc`；`test_p2_holdout_scorecard.py` 1403 行 +203 `04e26d747456bfc8`。
证据（3）：`evidence/01-synthetic-h2-before-after.txt`、`02-p1-default-diff.txt`、`03-pytest.txt`。
