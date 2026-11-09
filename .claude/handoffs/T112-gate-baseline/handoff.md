# T112 交接单：门禁阈值校准与 P1 (b0) live baseline（P1 第 15 包）

> 基线：分支 `p1/fix-retrieval`；前置 T111（live 检索运行器，dev `735bb93`）、T100–T114 已收口（T114 完成后本包才派）。当前 HEAD 见 `git log -1`。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。**本包含真实调用（唯一例外是 T111），必须严格按 §0 预算/GO 约束。**
> **主人 2026-11-09 18:2x 决策（方案 A）**：T112 缩到 **b0 live baseline**——复用 b0 语料（6 docs / 42 units / 27 chunks，T111 已实测），只跑 **b0 全量 40 题** live（预估约 87 请求，账本剩 565）；**badcase/regression/holdout 的 live 结果本包不做**（记 NOT-RUN，由 T900/P1 报告披露）。主人已放行 b0 全量 live 一次。

## 0. PM 口径（先读，硬约束）

1. **真实调用范围**：仅 `mode=live + scope=retrieval_only`、`suite=b0`、**恰好 40 题**（冻结 `fixtures/evaluation/b0.jsonl` 全量）、真实 embedding `text-embedding-v4`(1024) + rerank `gte-rerank-v2`；**零 chat**、零重试、串行、首个失败即停（fail closed）。
2. **请求/成本上限（本包硬顶）**：`P1-RETRIEVAL` 剩余 2.994731 元、账本剩余 **565** 请求；本包**总真实请求 ≤ 300**、单请求预留 ≤ 0.05 元；运行前必须成本预检，超上限即拒绝运行并如实报告（**不得先跑后说**）。运行环境必须 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`。
3. **账本/GO 只读**：经共享账本 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl` 预留/结算（stage `P1-RETRIEVAL`），GO 绑定前缀 sha `f4710b18…`；**不 commit 账本/GO**、不改 GO/budget 原件。
4. **全量 live 授权**：T111 的 `live.py` 目前硬拒 `pilot_cases=None`。本包允许**最小扩展**：新增显式 `--allow-full-live` 开关（默认关闭，关闭时行为与现在逐字一致），打开时仅允许 `suite=b0` + 数据集与冻结 `fixtures/evaluation/b0.jsonl` **字节级 sha256 一致** + 恰好 40 题，否则拒绝；report §4 单列文件/函数/净增行与理由。
5. **审批不自行伪造**：calibration 只产 proposal（不写回）；`baseline approve` 必须带 `--approver`/`--reason`，缺一拒绝（测试覆盖）。**R0 不得把 `gate_v0_2.json.status` 改成 approved，也不得自行 approve baseline**——提案由 PM 报主人书面批准后，另派 R1 落盘审批（届时才写 `approved` 与 approval.json）。
6. 不改业务代码/API/检索算法/`conversations`/`intent.py`/fixtures 既有数据/P0 gate/baseline；不读 Holdout；不打印凭据/`.env`；证据不含答案原文/逐题明细（聚合指标可）；不 push/amend；无 skip/xfail/删断言/新依赖。

## 1. 目标

1) 新增 `docs/evaluation/gate_v0_2.json`（检索指标阈值、regression suite、`min_sample`、`max_regression_pp`，`status=unapproved`）；2) `gate --calibrate` 对 b0 live run 产出可复现 proposal；3) 建立 **P1 release baseline（b0 live）** 的身份/审批机制（本包建 run + propose，审批留 R1）；4) 跑通 b0 全量 40 题 live 并产出指标与 gate 结果（允许 exit 3：未审批阈值/样本，不得伪造通过）。

## 2. 交付物（只准写这些路径）

1. **新增** `docs/evaluation/gate_v0_2.json`：`schema_version=mktkb.gate.config.v0.2`、`gate_version=mktkb.gate.v0.2`、`status=unapproved`、`hard_gates`（沿用 8 项）、`hard_gate_min_sample`、`quality_layer`（沿用/扩展口径）、`metrics`（至少覆盖 design §8.2 检索 5 指标；`min_sample`/`absolute_min`/`absolute_max`/`max_regression_pp` 字段齐全；proposal 值可空）、`suites` 含 `regression`。
2. `backend/src/mktkb/evaluation/gate.py`：v0.2 配置解析（schema/gate_version/suites/metrics 校验、非法 fail closed）、`calibrate_gate` 对检索指标的 proposal 输出（不写回配置）。
3. `backend/src/mktkb/evaluation/baseline.py`：P1 release baseline 建立/加载（`baseline approve` 现场重算门禁；`baseline_id` 绑定 dataset/pipeline/mode/scope/gate/corpus；缺 approver/reason 拒绝；跨版本只分析）。
4. `backend/src/mktkb/evaluation/live.py`（+ 仅必要的 `runner.py`）：`--allow-full-live` 最小扩展（见 §0-4）。
5. `backend/tests/evaluation/test_t112_*.py`（或等价新文件）：v0.2 解析/校验、calibrate 可复现、approve 拒绝/接受、跨版本比较、全量 live 授权守卫（fake，不真实调用）。
6. 真实运行产物 `var/eval/runs/<b0-live-run_id>/`（gitignored、不入库）；证据 `docs/reports/OBS-EVAL/P1/evidence/T112/`（≤4：live run 摘要+指标+成本/账本/零 chat 证明、gate proposal、v0.2 配置摘要、测试命令）、`report.md`（≤80 行五段）、**1 个 commit**（代码+配置+测试+报告+证据；不含 var 产物）。
7. **R1（另派）**：按主人书面批准落盘 `gate_v0_2.json.status=approved` + 阈值 + `baseline approve`（`approval.json`），补证据与第二个 commit。

禁止：业务路由/API/schema/`conversations/`/`intent.py`、b0/badcase/regression 数据文件、P0 `gate_v0_1.json`/P0 baseline、账本/GO 原件、`.env` 打印、Holdout、`docs/evidence` 写入除账本运行外、push/amend。

## 3. 验收标准（逐条）

1. **gate_v0_2**：文件可加载、schema/gate_version 正确、8 项硬门禁不变、检索 5 指标 + `min_sample`/`max_regression_pp` 字段齐全、`regression` suite 声明；未审批时质量结果 `unknown`/exit 3（不得当通过）。
2. **校准可复现**：对同一 b0 live run 重复 `gate --calibrate` 产出逐字节一致的 proposal（含指标建议值、来源 run_id、gate_config_hash）；不写回 `gate_v0_2.json`；proposal 落证据。
3. **baseline 机制**：`baseline approve` 现场重算门禁（`--gate` 文件仅审计）；缺 approver/reason 拒绝；`baseline_id` 六要素绑定、禁止 copy；跨版本比较标 `explicit_cross_version` 只分析；release baseline 缺失时 fail closed。
4. **b0 全量 live**：恰好 40 题真实跑通（预估 ~87 请求，实测记录 embedding/rerank/chat=0 计数）；manifest 六要素齐全；每 CaseResult 版本字段齐全；零 chat（spy+账本按 run_id 分类）、零重试、fail-closed；账本 stage `P1-RETRIEVAL` 有对应预留/结算；成本预检 vs 账本记录（保守口径）；超上限负例被拒绝。
5. **全量 live 授权守卫**：`--allow-full-live` 默认关闭时行为与原实现一致；打开时仅 b0+40 题+冻结数据集 sha 匹配才放行，其他 suite/题数/sha 不符均拒绝（测试覆盖）。
6. **回归/预算**：本包测试 / `backend/tests/evaluation` / 全量 0 failed/0 error（内存<2GB 轮询；既有 flake 隔离复跑）；b0/badcase/regression **local** + gate 对 P0 `case_diffs=0`、hard `[]`；P0 baseline 不混用；证据 ≤4、report ≤80、单 commit、只改允许路径、无 skip/xfail/删断言。
7. **范围诚实**：badcase/regression/holdout live **NOT-RUN** 必须在 report §5 如实登记原因（主人方案 A 请求上限），不得暗示已覆盖。

## 4. 必跑（命令口径）

- 先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`；同一时间只跑一套 pytest。
- 本包测试 / `backend/tests/evaluation` / 全量：`backend\.pytest-tmp\t112-*`（当前会话 `danger-full-access`，写权限正常）。
- local 对照：b0/badcase/regression `--mode local` + `gate`（对 P0 只读 baseline，`case_diffs=0`、hard `[]`）。
- live 预检（零 HTTP）：`python -B -m mktkb.evaluation.live --suite b0 --dataset fixtures\evaluation\b0.jsonl --allow-full-live --dry-run`
- live 真跑（一次）：同上去掉 `--dry-run`；产出 run 目录后**停止**，不得自动重跑/扩套件。
- `gate --calibrate`、`baseline approve` 的 dry/测试路径见 `evaluation/cli.py`。

## 5. 坑

- `live.py` 现有 `validate_pilot_dataset` 与 CLI `allow_full_live=False` 硬编码：最小改动是**新增开关**，不要放宽 pilot≤10 语义（原测试必须仍全绿）。
- b0 live 索引会重新 embedding 6 docs/27 chunks（约 7 请求）；索引失败不得留半成品；索引在 run 目录内（gitignored）。
- 成本预检用 `preview_live_run`/`plan_live_cost`；`before["reservation_count"]` 是**全账本累计**（当前 435），请求剩余按 565 计，不要按 1000 重算。
- `gate_v0_2` 校准基于本次 b0 live run 的指标；proposal 只建议、不生效；`status=approved` 必须等 R1 主人批准。
- baseline approve 会现场重算门禁：未审批 gate 时 gate 结果为 unknown/exit 3，approve 可能被拒——若如此，R0 如实报告「审批前置条件未满足」，不得绕过（R1 先落 gate approved 再 approve baseline）。
- `report.md` 与证据不得含答案原文/逐题明细/凭据；指标摘要、计数、sha 可以。
- 与 T113/T114 相同：证据路径 `docs/reports/OBS-EVAL/P1/evidence/T112/`；`_scratch/T112/` 放草稿（gitignored）。

## 6. 报告/交接

- `report.md` 五段（完成内容 / 验收标准自证每条≤2 行带命令或 `文件:行` / 实际运行结果：本包·evaluation·全量一行 + commit sha + stat + live run_id + 请求/成本 / 偏离 / 风险与 NOT-RUN），首行注明模型。
- 回复 ≤10 行摘要：commit sha、测试数字、live run_id、请求/成本、proposal 摘要、NOT-RUN 项、需要主人审批的具体值与建议。

## 7. 主人书面审批记录（2026-11-09 19:54 +08:00；R1 依据）

- **审批人**：主人。**授权范围**：仅检索层（answer/refusal/runtime 阈值仍 unapproved，b0/badcase 门禁仍 exit 3）。
- **批准的 gate_v0_2 单值阈值**（跨层最宽松 + 余量）：`min_sample=8`；`Recall@10`/`MRR@10`/`nDCG@10` → `absolute_min=0.855`、`max_regression_pp=2.0`；`hard_filter_violation_rate` → `absolute_max=0.02`、`max_regression_pp=2.0`；`empty_recall_rate` → `absolute_max=0.145`、`max_regression_pp=2.0`；`status=approved`。
- **授权建立 P1 release baseline**：run `b0-live-20261109T111828086143Z-0efd058b`（b0/live/retrieval_only、dataset `b0:b0-2026-11-04:bd4f0f7ccc6e`、corpus `68899152…`、pipeline `08166b113481`、gate `mktkb.gate.v0.2`、gate_config_hash `5362de3c…`）；`baseline approve --approver "主人" --reason "P1 首次 release baseline（b0 live 40 题）；绝对阈值按 T112 校准提案批准；首次建立不做回退检测"`。
- **R1 执行**：见 `prompts/T112-dev-R1.md`；R1 不得改批准值/不得改 proposal；gate 必须 exit 0，否则停手报告。
- **背景事实（R0）**：dev `7f46121`；b0 40 题（32 计分/8 OCR）、70 请求（embedding 39 + rerank 31、chat 0、重试 0）、账本 435→505/1000、P1-RETRIEVAL +0.0090459 元；指标 all/exact/text：Recall=MRR=nDCG=0.96875/1.0/0.875、hard_filter=0、empty_recall all=0.03125/text=0.125；proposal sha `0E7D641F…`（两次一致）；本包 13 / evaluation 433 / 全量 1933 passed。

