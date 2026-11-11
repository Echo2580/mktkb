# P2-T207-FIX-A 开发报告：矩阵工具与计划/GO 重建（零真实调用）

- 角色：T207-FIX-A 开发助手（全新上下文）。真实调用 **0**；未读 `.env`/H1/H2 题干/答案/密文/key；未联网；未改账本/预算/GO
  固定路径、fixtures、`p2_scoring.py`/`p2_runner.py`/`p2_live.py`/`p2_authorization.py` 语义；未 commit/push。HEAD（开工时）`96fede3`。
- 并行包：验证期间 T207-FIX-B-R1 在改 `p2_runner.py`（本包未读改）；该文件 diff numstat 两次复跑稳定 36/8。
- **T207-FIX-A-R1 修订（2026-11-11）**：开工 HEAD = `b1bfa60`（B-R1 已提交），工作区另含 FIX-S 的未提交改动
  （`p2_scoring.py`/`scorers.py`/`test_p2_scoring.py`，本包未改）。本报告的下表、
  §3 的 H2 规模、§5 的验证结果、§6.1/§6.3 已按 R1 现状更新；逐条闭环证据见
  `docs/reports/OBS-EVAL/P2/T207-FIX-A-R1/report.md`。

## 1 改动清单（sha16 = 文件 sha256 前 16 位；**数值为 T207-FIX-A-R1 收口时的实测**）

> 更正（独立验收 §3-6）：上一版此表 12 行里 **11 行行数比实际多 1**（计数口径，非功能问题），
> `test_p2_public_cases.py` 的 sha16 陈旧（写 `8f00e01c120ab07a`，实际 `4d59b34048eb1cef`）。
> 下面按 R1 收口状态逐文件重算（含 R1 自己的改动）。

| 文件 | 行 | sha16 | 改动 |
|---|---|---|---|
| `evaluation/product_adapter.py` | 2212 | `553e4ccf56765356` | `IngestSource.document_ref`（本次 ingest 内按上传名解析 document_id）+ `ingest_document_map` + `ingest_plan_from_document`；只有发布成功才更新 active |
| `evaluation/cli.py` | 1291 | `0bd425ac6aac2ede` | `p2-run --ingest-plan`（与 `--ingest` 互斥）+ 四个只读子命令；**R1**：holdout 缺输入/重复输入稳定码 + `--plan-id` 默认值改为单一来源 |
| `evaluation/p2_public_cases.py`（新） | 362 | `a0b8e12e568a505c` | N/C 只读转换器 + U01 镜像 + R1/R2/R3 case 文件；**R1**：模块头更正 clarification「更严」的错述 |
| `evaluation/p2_holdout_plan.py`（新） | 370 | `23c5bd5e57543833` | H2 受限计划生成器；**R1**：新增 `H2_DEFAULT_PLAN_ID`（CLI/GO/runbook 单一来源） |
| `evaluation/p2_score_run.py`（新） | 889 | `7c04fc4c104304b8` | run 产物→评分/聚合/矩阵/U 控制；**R1**：u-controls 子进程 UTF-8 钉死 |
| `tools/p2_live_execute.py`（新） | 243 | `76245bf0fd22041e` | 显式 `--env-file`：白名单注入子进程环境，只报变量名，拒绝 `.env` |
| 新测试 `test_p2_{public_cases,holdout_plan,score_run}.py` | 212/193/532 | `67b2c26a022f9517`/`5067acb54d6e32de`/`9011d8187e98ad5b` | 转换器/生成器/驱动离线用例；**R1**：b0 期望改 40/0、holdout 缺输入用例、clarification 口径钉住 |
| `tests/evaluation/test_p2_authorization.py` | 1416 | `11d8a0c38d4b28fc` | §8 既有红测试修正（见 §4） |
| `tests/evaluation/test_p2_live_wiring.py` | 1468 | `b4ccd71e3963aa4b` | +F7 多 run（新门/复用门反证）+ 包装器 4 例 |
| `tests/integration/test_p2_product_e2e.py` | 646 | `0f0abafa87984a4d` | +版本槽（V03→D01 v2→V04 v3 不发布）、未知 ref fail-closed、ingest-plan 文档/互斥 |
| `docs/evaluation/p2-*v0_1.md` ×3 | — | — | 追加 §11.6/§11.7、§7.4、§10.7（additive） |
| `T207/**` | — | — | 计划/GO 重发、cost、runbook（顺序/命令/H2/禁止清单）、`cases/*`、`PM/T207-ingest-plan-{R1,R2,R3}.json`、**R1 新增 `PM/T207-ingest-plan-H2.json`**、report、evidence |

## 2 计划/GO 重建
- 公开计划 `PM/T207-plan-v0_1.json`：233 项 / 254 请求（单 run 上界）/ worst 8.127376 / 12 页 OCR；`max_requests` 1000→**1200**，
  新 **`plan_sha256=0b4e55a4cd3a46f968e89fe495ffca3c6931c8f49f1f258a3dd753f83e24a194`**；候选 GO 同步 1200（DRAFT，`production_ready=false`）。
- 拆 run：**R1=B0 40+N8+C01–C04（52 回合 / 242 请求=208+22+12 / 7.994704）**、**R2=U01+C05（2 / 15=8+7 / 0.102784）**、
  **R3=C06（1 / 6=4+2 / 0.04832）**；累计 **263 请求 / 8.145808 元**（≤ 19.4286417）；Q01 只在 R1。
- 授权窗口（每 run 新门，`preflight_p2` 每次重跑）：R3 801 / R2 807 / R1 822，均 ≤1200。
- **发现（已写 cost §3.1 / runbook §3）**：顺序必须 **R3→R2→R1**。计划含 12 页 OCR（5.65），R1 跑完后 ocr 中心只剩 0.35 < 5.65，
  再授权必 `center_budget_insufficient:ocr`（请求窗口仍够：411 ≥ 254）；反证见 `T207/evidence/validate-plan-out.txt` 的 `reorder_control`。
- 只读复核：`preflight_p2` 真实快照 `ok=true`、`stage_remaining=19.4286417`、`requests_remaining=653`；候选 GO `authorize_p2` 通过但
  `production_ready=false`；10 条负例（含 `hard_cap_over_1600`）按稳定码拒；只读证明 `unchanged=true`（账本/预算前后同 SHA）；固定路径 GO 仍是既有 T206 签署件（本包未写，须经理按新 sha 重签）。

## 3 用法（细节见 runbook §3/§5/§8）
- 灌库 `p2-run --ingest-plan <json>`（`p2-ingest-plan/v0.1`；可写 `document_ref`/`publish=false`）：已给 `PM/T207-ingest-plan-{R1,R2,R3}.json`（12/4/2 个 source）；
  **R1 新增** `PM/T207-ingest-plan-H2.json`（12 个 source，H2 语料包状态，见 T207-FIX-A-R1 report §3）。
- 题集 `cases/{R1,R2,R3}.jsonl`（52/2/1 行，sha `e44ab9ff…`/`d5fb8cac…`/`d72c6d54…`），由 `python -m mktkb.evaluation.p2_public_cases` 生成并被用例钉"逐字节一致"。
- H2 `p2-h2-plan --cases-metadata <工作区外> --holdout-manifest docs/evaluation/p2-holdout-v2.manifest.json --ingest-batches B --plan-out <工作区外>`：
  交叉校验 30 题/36 回合/histogram/multi_turn，145 项、**158 请求（B=14）**；计划落在工作区内即
  `plan_out_inside_workspace` 拒，stdout 无 case_id。**R1 更正**：原文写「212 请求（B=68）」，其中 68 是声明包络、
  不是 H2 语料包的实际批数；实测 B=14（产品 chunker + 缓存语义，离线），见 R1 report §3 与 cost-and-quota §5。
- 评分 `p2-score --run-dir --cases --document-codes` → `scorecard.json`/`case_scores.json`/`p2_decision.json`；H2 用 `--visibility holdout`
  + `--holdout-cases|--verdicts` 只写 `holdout_scorecard.json`；矩阵 `p2-matrix --case-scores R1/R2/R3 --u-controls`；U 导出 `p2-u-controls`。
- H2 候选 GO 只作形状预审（`plan_sha256` 全零占位）；签发条件写进 `authorization` 字段（生成器产出后填 sha、语料包已声明、1100/中心逐值一致、绑历史前缀、nonce/时效）。
- 执行 `tools/p2_live_execute.py --env-file <工作区外> -- p2-run ...`（默认不读 `.env`；拒绝名为 `.env` 的输入）。

## 4 既有红测试的合法修复（经理已授权；为什么不是放宽）
- 原断言 = 候选快照整文 sha vs **当前**账本整文 sha。账本只允许追加（pilot/T207 每笔预留都是合法追加），任何一次合法 run 之后
  必然失败，且它证明不了"历史没被改写"。改为三条更强绑定：①整文 sha == **T201 存档证据值** `1f46d1b9…fde7390`（防快照被悄悄重钉）；
  ②快照历史前缀 == **当前**账本历史前缀（历史改写即失败）；③`reservation_count>=505` 保留。准入时 `authorize_p2` 的 `ledger_binding_ok` 仍再核一次。
- 未删/未放宽任何安全断言，无新增 skip/xfail；经理决定与 T201 证据出处写进 docstring。

## 5 验证（`evidence/` 4 份；结果已按 R1 现状重跑）
- `01-pytest.txt`：旧记录 **269 passed** 已过时（那时 `test_p2_score_run.py` 还冻结 Q39 fail，且工作区里没有 FIX-S）。
  **R1 复跑（在 FIX-S 存在的工作区，HEAD `b1bfa60`）**：任务书点名的 7 个文件 + FIX-S 的 `test_p2_scoring.py`
  共 **194 passed / 0 failed**（59.77s）；另跑 A 改动面相邻的 `test_p2_public_controls`/`test_gate_quality`/`test_p0_acceptance` = **42 passed**。
  原始输出见 `T207-FIX-A-R1/evidence/01-pytest.txt`。`02-plan-validation.txt`：新 sha/规模 + 预检/授权/负例/三窗口/顺序反证/只读证明。
- `03-matrix-sample.json`：`p2-matrix` 真实 CLI 产物（`multi_run_scenario_isolated`、`release_decision=false`、U01=R/U02–U10=L、逐 case provenance）。
- `04-wrapper.txt`：包装器 5 条真实 CLI 调用（合法/缺变量/白名单外/`.env`/子进程），哨兵值在输出出现 **0** 次；`--check-only` 只回变量名。

## 6 偏差、限制与发现
1. ~~既有 scorer 缺口~~ **已由 T207-FIX-S 修复（R1 更正，不再是待决项）**：原缺口是 `check_value` 去空格后
   数字间不允许跨空白，Q39 期望值 `2026-10-30 16:00` 在基线里必判 fail；FIX-S 以 opt-in 的 `cross_explicit_space`
   只在 P2 路径打开（默认口径 30,912 对比对 0 分歧）修好，b0 由 39/1 变为 **40/0**。
   本包 R1 已把 `test_p2_score_run.py` 的冻结期望改为 40/0 并加 Q39 行断言；矩阵**不会再出现 Q39 fail**。
   （该文件属 FIX-S，本包未改。）
2. **Mock chat 对记录型问题默认答案不合规**：默认只回前 3 个字段，Q01 类问题会被产品判 `MODEL_OUTPUT_INVALID`；版本槽用例显式给
   `ChatBehavior(answer="位置：…")`（与既有 live 用例同法），断言的是"用哪一版 evidence 接纳答案"，不是模型质量。
3. **H2 逐题输入仍是封存侧产物**：runner 对 holdout 只写聚合（禁改），故 `p2-score --visibility holdout` 需 `--holdout-cases`（封存逐题行）
   或 `--verdicts`（封存判定表），都由受控进程在工作区外产生；**R1 已把缺输入码落到代码**：
   两个都不给 → `holdout_input_missing`、两个都给 → `holdout_input_conflict`（都在解封前 exit 3、不写产物；
   旧实现是 `TypeError`，与文档承诺不符，已由独立验收指出并修掉），不用计数编造 pass/fail；行路径的来源/安全类
   结构问题带 `holdout_hard_failure_unclassified` block（不替封存标注方分类）。
4. **`scorecard.real_calls` 语义**：逐题记 0（不虚构归属），run 级实测值在 `RunScore.real_calls`（`network.outbound_attempts`，不可用退
   `attempts.reserved` 并带 `network_measurement_unavailable` block）。
5. **观测矩阵不是 release**：`release_decision=false`、`gate_config_unapproved` 写死；未审批配置的 `p2_decision.json` 必为 unknown。
6. 未做：真实调用/OCR/H2/Ragas/全仓测试；未跑 `p2-run`（含全量 dry-run）；未评估质量。
   **R1 补跑**：`p2-u-controls` 已在本机实跑（U01–U10 全 pass、stderr 0 字节，见 R1 evidence 04）；顺带修掉它在 Windows
   下解码 pytest 输出的 `UnicodeDecodeError`（子进程 UTF-8 钉死）。

## 7 回退
**基线更正（独立验收 §3-7）**：`p2-runner-contract` §7.4 已随 T207-FIX-B-R1 的提交 `b1bfa60` 进入 HEAD
（并行提交把 A 的未提交内容带了进去），所以 `git checkout --` **回退不掉** §7.4——要撤只能新 commit 反向修改，
或只回退 A 自己的增量。已提交的部分不再算 A 的「本包新增」。

`git checkout --` 5 个被改代码/测试文件（product_adapter、cli、test_p2_authorization、test_p2_live_wiring、test_p2_product_e2e）
+ 3 份 `docs/evaluation/p2-*v0_1.md` 中**尚未提交**的增量 + `docs/reports/OBS-EVAL/P2/T207`；删除 6 个新增代码/测试文件与
`docs/reports/OBS-EVAL/P2/T207-FIX-A/`。无需数据回退：未写账本/预算/GO/run 产物（全部 tmp），账本/预算 SHA 前后一致。
