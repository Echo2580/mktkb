# T108 交接单：Holdout 支持与防污染（P1 第 9 包）

> 基线：分支 `p1/fix-retrieval`（T100–T107/T101–T106 已 G6；HEAD `cdf3baa`）。P1-PRE-1 已交付 holdout 30 题（questions sha `a8c8aa7f…6738` / labels sha `8f713a2a…c1bf`，`label_version=holdout-2026-11-04`，不入库）。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 0. PM 口径（先读；与设计 §4/§7 冲突处以此为准）

1. **仓库导出**：`fixtures/evaluation/holdout-questions.jsonl` = 本地 `questions.jsonl` 的**逐字节拷贝**（P1-PRE-1 已按"题干+元数据、不含答案"交付；含 coarse `expected_kind`/`should_refuse` 等元数据，**不含** `expected_values/expected_sources/relevant_units/reference_answer` 等答案；sha256 必须等于 `a8c8aa7f…6738`）。开发助手**不得读取** `docs/evidence/LOCAL-R1-20261101/P1-HOLDOUT/`；该导出由 PM 先把 `questions.jsonl` 拷到 `.claude/handoffs/_scratch/T108/questions-copy.jsonl`（gitignored），开发从该**副本**生成/提交仓库导出（不接触 holdout 目录本身）。
2. **答案分离**：答案在本地 `labels.jsonl`（30 行，label_version=`holdout-2026-11-04`，sha `8f713a2a…c1bf`），**永不入库**。holdout run 通过 CLI `--holdout-labels <path>`（或环境变量 `MKTKB_HOLDOUT_LABELS`）在**运行时**读取；开发测试只用合成 holdout 夹具（临时目录），不得读取真实 labels。
3. **默认聚合**：`run --suite holdout --mode local` 默认只写聚合（summary/manifest；不含逐题题干/答案/逐题结果，不写 `cases.jsonl`）；逐题详情必须 `--allow-holdout-details`，且同时写 `holdout_audit.json`（操作人/时间/参数/run_id/数据 sha/label_version）。
4. **CI/gate 禁 flag**：检测到 CI/门禁环境（至少 `CI`、`GITHUB_ACTIONS`、`MKTKB_CI` 任一为真）时，`--allow-holdout-details` 必须**硬失败**（非零退出、明确错误）；`gate --run` 对 holdout 默认聚合 run 必须可用（不得因缺 cases.jsonl 报未定义错误）；对含逐题详情的 holdout run，gate 在 CI/门控环境应拒绝（硬失败）或仅用聚合（dev 二选一并写明，report 披露）。
5. **拒绝条件（fail closed）**：questions/labels 缺失、行数非 30、case_id 集合不相等、分层不是 10/5/5/5/5、`label_version` 缺失或与数据集不一致、questions sha ≠ `a8c8aa7f…6738` 或 labels sha ≠ `8f713a2a…c1bf` → 明确拒绝运行/退出非零。
6. **红线**：开发期间不读真实 holdout 内容；证据/报告/shell 中不得出现逐题题干或答案原文；验收方抽查 shell 历史与证据。
7. 本包**不**接入 holdout 门槛（`gate_v0_2` 校准留 T112）；`b0/badcase/regression` 冻结不动；不改 `intent.py`/业务 API 字段结构；零真实调用；Holdout 明细默认不可达。

## 1. 目标
让 holdout 30 题可受限运行且防污染：加载/校验（questions 仓库导出 + labels 本地）、默认只出聚合、逐题需 flag + 审计、CI/gate 禁 flag、缺 label_version/不匹配拒绝。

## 2. 输入
`2026-11-04-p1-design.md` §4（:57-95）与 §7.4；`2026-11-04-p1-task-breakdown.md` §T108；`P1-HOLDOUT/README.md`（只读路径与 sha，不读内容）；`evaluation/{dataset,runner,cli,gate}.py`；P0 设计 §7.1/§7.4（数据集字段/退役补位）；`fixtures/evaluation/{b0,badcase,regression}.jsonl`（结构参考，冻结不改）。

## 3. 交付物（只准写这些路径）
1. `backend/src/mktkb/evaluation/dataset.py`（holdout 加载/校验/合并；仓库导出校验）。
2. `backend/src/mktkb/evaluation/runner.py`（holdout 默认聚合、details 开关、audit、manifest 标记）。
3. `backend/src/mktkb/evaluation/cli.py`（`--holdout-labels`、`--allow-holdout-details`、CI 检测硬失败、`dataset export-holdout-questions` 或等价导出命令）。
4. `backend/src/mktkb/evaluation/gate.py`（holdout 聚合 run 可用；详情 run 在 CI/门控环境拒绝；不泄漏逐题）。
5. `backend/tests/`（合成 holdout 夹具；默认聚合不含逐题、details+audit、CI 硬失败、缺 label_version/sha/分层不匹配拒绝、case_id 集合校验）。
6. `fixtures/evaluation/holdout-questions.jsonl`（PM 提供的 questions 副本导出；无答案字段；sha 与本地 questions 一致）。
7. 证据 `docs/reports/OBS-EVAL/P1/evidence/T108/`（≤4）、`report.md`（≤80 行五段）、1 commit。
**不要写**：真实 holdout 目录、labels、b0/badcase/regression、业务代码、API schema、gate 配置（`docs/evaluation/`）、账本/GO。

## 4. 验收标准（逐条可判定）
1. **默认聚合**：本地合成 holdout run 默认产物（manifest/summary/stdout）**不含**逐题题干/答案/逐题结果，且不写 `cases.jsonl`；有测试与证据。
2. **details + audit**：`--allow-holdout-details` 才写逐题结果，并生成 `holdout_audit.json`（操作人/时间/参数/run_id/数据 sha/label_version）；测试覆盖。
3. **CI 硬失败**：设置 CI 环境变量后带 flag 运行 → 非零退出/明确错误；测试覆盖；`gate --run` 对 holdout 聚合 run 不报错（且不泄漏逐题）。
4. **拒绝条件**：缺 labels/label_version/行数≠30/分层≠10/5/5/5/5/case_id 不匹配/sha 不符 → 退出非零且信息明确；测试逐项覆盖。
5. **仓库导出**：`fixtures/evaluation/holdout-questions.jsonl` 30 行、与本地 `questions.jsonl` 逐字节一致（sha256=`a8c8aa7f…6738`，PM 提供副本核对）、不含答案字段（无 `reference_answer/expected_values/expected_sources/relevant_units/forbidden_*`）；`labels.jsonl` 内容/路径永不入库。
6. **回归/预算**：本包测试 + `backend/tests` 相关目录 + 全量 `backend/tests` 0 failed/0 error（§11A；内存 <2GB 轮询）；b0/badcase local run+gate 对 P0 `case_diffs=0`、hard `[]`；regression 仅 RG006 fail→pass、RG005/RG007 不变；无 skip/xfail/删断言/新依赖；未读真实 holdout；证据 ≤4、report ≤80、1 commit、只改允许路径。

## 5. 提交与报告
- 1 commit：`p1/T108 holdout support + anti-leak guardrails`；不 push/不 amend。
- report 五段 ≤80 行：完成内容 / 验收标准自证（≤2 行/条，命令或 `文件:行`）/ 运行结果（本包/相关目录/全量 + b0/badcase/regression 对照 + commit sha + stat）/ 偏离或未做（含 gate 对详情 run 的处理选择、真实 holdout 运行由验收方执行）/ 风险。
- 回复 ≤10 行摘要。

## 6. 坑
- 不要把 `questions.jsonl` 的答案字段带进仓库导出（先 `git diff`/grep 确认）；labels 永不入库。
- 默认聚合与 details 产物要分目录/分文件；`holdout_audit.json` 不得含答案原文。
- CI 检测用环境变量组合，测试用 monkeypatch env；不要依赖网络。
- 真实 holdout 运行由**验收方**在受限环境跑（labels 路径由 PM/验收方提供）；开发只用合成夹具。
