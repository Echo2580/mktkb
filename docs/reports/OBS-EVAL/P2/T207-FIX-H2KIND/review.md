# P2-T207-FIX-H2KIND 独立验收报告（review）

- 角色：独立验收助手（全新上下文）；分支 `codex/p2-e2e`；只读复核 + 零真实调用；未 commit。
- 开工 HEAD `3bc8347`；核验期间并行包 FIX-CONFLICT 提交了 `0260b7b`。已核对
  `git diff 3bc8347 0260b7b -- backend/src/mktkb/evaluation` **为空**，本包评分源码基线未漂移；
  本包四个文件仍为工作区未提交改动（HEAD 内无 `compat_refusal_kind`）。
- 结论：**接收（阻断 0）**。逐条判定见下，证据在 `evidence/verify/`。

## 1 逐条判定

| # | 验收项 | 判定 | 依据（独立复跑） |
|---|---|---|---|
| 1 | 范围/合规 | **PASS** | numstat 仅 4 文件：scorers +34/−2、p2_scoring +9/−0、两个测试 +203/+129（删除 0）；受保护路径与账本/预算/GO 的 `git status` 为空；无 skip/xfail；本包无 commit；新增代码无网络调用。详见 `evidence/verify/01-scope.txt` |
| 2 | 默认行为不变 | **PASS** | HEAD 源码 vs 工作区源码，90 case × 10 kind × 4 文本 × 2 引用 = **7200 次** `score_case`（报告 2160 的 3.3 倍），整份 JSON sha256 **完全相同**（`40d36c12…`，12,912,044 bytes），**0 分歧**；fixtures 2 道 refusal 题默认路径 not_found/no_answer 仍 **0 pass**；生产代码唯一显式打开点 `p2_scoring.py:899`。详见 02 |
| 3 | 语义正确且不放宽 | **PASS** | expected=refusal + actual∈{not_found,no_answer,refusal} → pass（evidence `compat="refusal"`，字面 refusal 走相等分支无标记）；actual=answer/conflict/clarification/error → fail；expected=not_found + actual=no_answer 仍 fail；expected=answer + actual=not_found fail；`should_refuse=False` 时 actual=not_found 被 `refusal_unexpected=fail` 拦下；`_kind_checks` 的 refusal_expected/refusal_unexpected 代码未改。详见 03 |
| 4 | 合成 H2 复现 | **PASS** | 自建 30 题（answer23/conflict1/refusal6、产品只回 not_found）走**真实 H2 入口** `holdout_case_scores_from_rows`：开关开 **30/30**；同一入口只关开关（monkeypatch 仅覆盖该参数）**24/30**；6 道被作答 **24/6**；翻转题严格 = 6 道 refusal（VH2-16..20/26）。阈值常量 OLD/NEW 均 `TOTAL=30, MIN_PASS=24, HARD_MAX=0`；三臂 blocks 仅 `holdout_threshold_unapproved(unknown)`、`release_ready=false`、`unclassified=[]`，门禁未被绕过。详见 04 |
| 5 | 回归与合规 | **PASS** | 点名四文件 **108 passed**；新增 **15 条逐条 PASSED**；evaluation 全目录 + 3 个 P2 集成文件 **852 passed**，零 FAILED/ERROR（提交 0260b7b 后复跑）。基线 **93 passed** 用 HEAD 源码+HEAD 测试在工作区外隔离目录独立复现（93+15=108）。未读 `.env`/H2 封存；H1 题面仅作不透明输入。详见 05 |
| 6 | 限制结论 | **PASS（附结论）** | 见 §3 |

## 2 关键事实核对
- `scorers.py` 新增 `REFUSAL_COMPAT_KIND="refusal"` 与 `score_case(..., compat_refusal_kind=False)`；
  `_kind_checks` 的兼容分支三条件（开关开 ∧ expected=="refusal" ∧ actual∈REFUSAL_KINDS），其余分支不变。
- `p2_scoring.score_public_case` 显式 `compat_refusal_kind=True`（`p2_scoring.py:899`）；
  P2 公开/H2 评分与 CLI 路径都经它（`p2_score_run.py:308/403/506`）；
  真实 H2 run 的评分入口 `p2_runner.py:1855 → holdout_case_scores_from_rows → score_public_case` 确实吃到该开关。
- P1 五处 `runner.score_case` 均不传新参数（`runner.py:1578/1622/1802/2112/2119`），默认 False。
- 公开套件的 expected_kind 分布（b0 40 answer；badcase 10 answer/1 ambiguous/2 no_answer；
  regression 3 answer/1 clarification/3 no_answer）无 refusal → 该放宽对公开评分读数无影响；
  refusal 只存在于 H1 题面 fixture（2 题）与 H2（6 题）。

## 3 限制与残余风险（第 6 项结论）
1. **合成 H2 只证明评分口径**：不走封存/解密、不跑产品、不分轮次；30/30 不代表真实 H2 质量。
   真实 H2 读数仍取决于真实题面/标注、产品对拒答题的实际结局与阈值审批。
2. **不影响“口径”可信度，但影响“数值可引用性”**：真实 H2 run 与本次合成走同一函数，故修复会正确作用于
   真实 run；但在阈值/门禁审批（当前 gate_v0_3 unapproved）之前，真实 H2 卡仍是 unknown，
   **任何“30/30 达标/H2 通过”的表述都不可用**。
3. **24/30 的结构性上限确实被解除，但阈值 24 未动**：修复后 30/30 有 6 题余量；若真实 H2 有其它
   value/source 类失手，仍需按 24 判定。注意 `threshold_met` 是 `>=` 语义（24/30 也为 true），
   真正的问题是修复前零余量；修复本身没有、也不应改阈值。
4. `not_found`/`no_answer` 在 kind 层无法区分“资料缺失”与“越权安全拒答”；安全审计仍需靠标注/判定表，
   不能从 kind_correct 推断安全拒答已做对（H2 安全题若要单独审计，需封存判定表）。
5. 若真实 H2 存在 `expected_kind="refusal"` 但 `should_refuse=False` 的标注不一致，该题仍会 fail
   （`refusal_unexpected`）——这是正确的 fail-closed，但建议数据侧核对两字段一致性。
6. 文档 `docs/evaluation/p2-dataset-v0_1.md` 未更新；报告已说明理由（只描述 dataset 结构）。
   属可接受，建议后续在 T209/口径文档补一句“refusal 为 P1 兼容值，P2 按拒答族匹配”。

## 4 非阻断观察
- 开发测试的 before 臂直接调 `score_case`（非真实入口），但测试同时断言生产入口逐题一致；
  本验收用真实入口 + 单参数 monkeypatch 独立复现 24/30，风险已被抵消。
- 报告“P1 差分 2160 次”与本次 7200 次不矛盾（规模更大，结论一致）。
- 核验期间 HEAD 前移（并行包提交）不改变本包结论；本包文件仍未提交，符合“不 commit”。

## 5 最终建议
**接收（阻断 0），附三条收口要求：**
1. 对外/对主人只写“评分口径修复：合成上限由 24/30 提升到 30/30”，**不得**写成“H2 30/30 达标/通过”。
2. 真实 H2 run 仍须过阈值/门禁审批 + 新 GO；本包不改变 `holdout_threshold_unapproved` 与 `release_ready=false`。
3. （建议，非阻断）补 `docs/evaluation/p2-dataset-v0_1.md` 的 refusal 口径说明；数据侧核对
   `expected_kind="refusal"` 与 `should_refuse` 一致性。

## 6 证据清单（`evidence/verify/`）
- `01-scope.txt` 范围/唯一打开点/受保护路径/HEAD 漂移
- `02-default-diff.txt` + `probe_default_diff.py` + `raw-default.txt`（7200 次、0 分歧）
- `03-semantics.txt` + `probe_semantics.py` + `raw-semantics.txt`（16 场景矩阵）
- `04-synthetic-h2.txt` + `probe_h2.py` + `raw-h2.txt`（30/30、24/30、24/6）
- `05-tests.txt` + `raw-pytest_93_baseline.txt` / `raw-pytest_108.txt` / `raw-pytest_15.txt` / `raw-pytest_852.txt`
- `probe_consts.py` + `raw-consts.txt`（阈值常量 OLD/NEW）、`probe_kinds.py` + `raw-kinds.txt`（expected_kind 分布）
