# P2-T207-FIX-A 独立验收（review）

- 验收角色：独立验收助手（全新上下文，未参与开发对话）。验收时点：2026-11-11 10:00–10:40 +08:00。
- 工作区：`codex/p2-e2e`；开工时 HEAD `405491c`，验收期间并行包 T207-FIX-B-R1 由经理提交为 **`b1bfa60`**；A 的改动仍未提交。
- **现场变化（影响结论，必须先读）**：验收期间出现并行包 **T207-FIX-S** 的未提交改动
  （`backend/src/mktkb/evaluation/p2_scoring.py`、`scorers.py`、`tests/evaluation/test_p2_scoring.py`），
  其目的是修 Q39「日期+时间」值匹配。它使 A 的 `test_p2_score_run.py` 中「Q39 必 fail」的断言失败（见第 12/13 条）。
  本 review 按**当前工作区**判定；未修改/回退任何并行包文件。
- 边界：真实出站 **0**；未读 `.env`、H1/H2 题干/答案/密文/key；未改账本/预算/GO、fixtures、
  `p2_runner.py`、`test_p2_runner.py`、`p2_authorization.py`、`p2_live.py`；未 commit/push。
  账本/预算/GO 到达=离开：`6b053520…`（1,050,298 B / 1095 行）、`79b21700…`、`79a5f318…`。
- 证据：只保留 4 份，见 `evidence/verify/`（自写探针脚本 + 原始输出 + 套件复跑 + 最终哈希）。

## 0 最终结论

**返工（阻断 3 项）**：A 的公共矩阵/工具主体可保留，但当前不能按「套件全绿、证据自洽」接收。
阻断项都是小改（2 行测试 + 2 处一致性/契约修正），见 §3、§6。

## 1 逐条判定

| # | 项 | 判定 | 独立依据（摘要） |
|---|---|---|---|
| 1 | 范围合规 | **PASS（A 本体）**，附注 | A 的改动=报告 §1 所列文件 + 7 个新增代码/测试文件 + T207 文档/cases/ingest-plan；无 fixtures/固定路径/账本/预算/GO 改动；无新增 skip/xfail；A 未 commit。`p2_scoring/scorers/test_p2_scoring` 的 dirty 属 FIX-S，不是 A。**但** `p2-runner-contract` §7.4 已被 `b1bfa60` 带入 HEAD（见 §3 第 7 条），A 的 report 仍把它列为“本包新增/可回退”。 |
| 2 | 计划/GO 重建 | **PASS（有 1 处规格偏差）** | 独立重建：`plan_sha256=0b4e55a4…a194`，233 项/254 请求/8.127376/峰值 0.5/中心 2.477376+5.65/max_requests=1200；真实快照 preflight `ok=true`、`requests_remaining=653`、`stage_remaining=19.4286417`；候选 GO 绑定同 sha、1200、8.5/6.5/3/2、`production_ready=false`（`go_sha256=7376bc31…`）。固定路径旧 GO 拒（实际码 `go_plan_id_mismatch`，不是文档写的 `go_plan_sha256_mismatch`）。负例：plan 1201 + 同绑 GO 1200 → `go_max_requests_below_plan`；plan/GO 1601 → 各自 hard-cap 码；旧计划 sha → `go_plan_sha256_mismatch`。**但 GO scope max_requests=1201 与 plan=1200 会被接受**（有效上限 `min(plan,GO)`=1200，安全）；任务书“GO 1201 按稳定码拒”在 B 的 1600 硬顶下不成立。 |
| 3 | 拆 run 与顺序 | **PASS** | 独立复算：R1 52 回合/242=208+22+12/7.994704；R2 2/15=8+7/0.102784；R3 1/6=4+2/0.04832；累计 263/8.145808。cases 行数 52/2/1，R2=U01+C05、R3=C06、Q01 只在 R1；ingest-plan 源数 12/4/2；实测 embedding 批 11（非 OCR）+11（OCR 上限）=22、R2=7、R3=2。授权窗口 801/807/822（=547/553/568+254）；顺序反证：先 R1 后 preflight `center_budget_insufficient:ocr`、请求余 411、ocr 余 0.35；必须先 R3→R2→R1。另用离线产品链验证 R2 同 KB 下 U01 仍 answer（B区、引 D01 v2），C05=conflict（引 D01+V01），即 U01 未被 V01 污染（探针节 u01_with_R2_full_plan/c05_with_R2_full_plan）。 |
| 4 | `--ingest-plan`/版本槽 | **PASS** | 独立跑 `-k version_slot or document_ref or ingest_plan_document or ingest_source_rejects`：4 passed。版本槽断言 latest=3/active=2/v3=`review_required`/revision+2；Q01 答「B区1号货架第二层」、引用 version=2、不含 V04；未知 ref fail-closed；`--ingest`/`--ingest-plan` argparse 互斥 exit 2；`documents/service.py` 无 diff。 |
| 5 | `p2_public_cases` | **PASS（口径有 1 处更松）** | 14 条 N/C 逐字段回溯 questions.json 全过（question/suite/kind/values/sources/forbidden/refuse/date/label/notes）；U01 镜像同源；R1/R2/R3 逐字节等于规范转换，sha `e44ab9ff…/d5fb8cac…/d72c6d54…`；document-codes 覆盖 12 名。**注**：clarification（C01–C04）的 any-of 措辞被置空，只判 `kind`，比验收口径**更松**（不是 report 说的“更严”）；not_found 只判拒答。 |
| 6 | `p2-h2-plan` | **PASS（生成器）/ FAIL（配套 GO 的 plan_id）** | 合成元数据（30 题/36 回合/25-4-1）离线跑通：145 项/212 请求（B=68）/page_count=0/worst 1.731328/中心 1.731328；stdout 无 `case_id`/无合成 id；plan 可 `P2RunPlan.from_dict`；plan-out 在仓库内 `plan_out_inside_workspace` 且不落盘；metadata 在仓库内同拒；histogram/version/未知字段/B=69 均稳定码拒。**但**候选 GO `scope.plan_id=P2-T207-H2-20261111` 与 runbook §8.1 `--plan-id P2-H2-20261111` 不一致，按文档生成会被 `go_plan_id_mismatch` 拒（fail-closed 但跑不通）。 |
| 7 | `p2-score`/holdout | **FAIL（1 子项）/ 其余 PASS** | 公开：缺题 C05=`not_executed`、error U01=`case_error`，不伪造；scorecard/case_scores/p2_decision 三件套落盘；逐题 real_calls=0、run 级 real_calls=4。holdout（假数据集，不读 H2）：30/24/6、blocks=`holdout_threshold_unapproved`、release_ready=false、输出无 `case_id`/合成 id。**缺输入**：既无 `--holdout-cases` 也无 `--verdicts` 时，实际是 `TypeError: ... not 'NoneType'`（exit 3），**代码中不存在文档承诺的 `holdout_input_missing`**（全仓 grep 仅 docs 有）。 |
| 8 | `p2-matrix` | **PASS** | `composition=multi_run_scenario_isolated`、`release_decision=false`、`not_a_release_decision=true`、`gate.block_reason=gate_config_unapproved`；逐 case `run_id/index_revision/config_hash/basis/execution_mode/real_calls`；U01=R（R2）、U02–U10=L，缺 u-controls 时 L 行 status=null 不伪造。 |
| 9 | `p2-u-controls` | **PASS（有 1 个 Windows 缺陷）** | 独立跑 `test_t09_mutation.py`：13 passed（U01–U10 全 pass；U07 2 变体、U09 3 变体）；测试文件 sha 前后不变；另用 `--junit-xml` 独立解析，逐 U 判定与导出 JSON 一致（13 个 testcase）。**缺陷**：`export_local_controls` 的 `subprocess.run(text=True)` 在 Windows 下对 pytest 输出解码失败，stderr 出现 `UnicodeDecodeError` 线程异常（命令仍 exit 0/结果正确）。 |
| 10 | `p2_live_execute` | **PASS** | 显式 `--env-file`；白名单外名 `env_name_not_allowed`；名 `.env` → `env_file_forbidden`；缺变量只报 4 个变量名；文件值与父进程同名旧值均不泄漏（父值被剔除）；`values_printed=false`；6 条真实 CLI 调用中哨兵出现 **0** 次；默认（无 `--env-file`）仅 argparse exit 2，不读仓库 `.env`。注：子进程失败时包装器仍打印 `ok:true` + `child_exit_code=3`，语义略歧义。 |
| 11 | 红测试修正 | **PARTIAL** | 跑 `test_p2_authorization.py`：71 passed、无 skip；快照 sha=`1f46d1b9…`（与 T201 verify.json/probe/candidate-numbers/README 多处同值），快照历史前缀=当前前缀 `f4710b18…`，reservation>=505。**但“严格强于旧”不成立**：新断言只看历史前缀，追加后的历史行被改写时前缀不变（我用同长度字节篡改 post-import 行验证：整文变、前缀不变，新断言仍会 pass；旧断言会 fail）。另：两处前缀断言重复；`snapshotted_prefix` 属冗余 helper。 |
| 12 | 测试与报告 | **FAIL** | 复跑报告点名套件两次：**279 passed + 1 failed**（56.92s/55.38s），当前收集 280；不是报告的 269。失败为 A 的 `test_p2_score_run.py::test_matrix_is_multi_run_and_never_a_release`（`assert 40 == 39`，Q39 已由 FIX-S 修好）。报告 §1 的 sha16：12 个文件中 **`test_p2_public_cases.py` 不一致**（实际 `4d59b34048eb1cef`，报告 `8f00e01c120ab07a`）；行数 11 个文件比实际多 1（计数口径，非功能问题）。cost §1/§5/§6/§7 与 runbook §0/§5/§8 有数值/码名不一致（§3）。B 行为未回退（authorization 71、runner 35、hard cap 1600 全过）。 |
| 13 | 两个待决项 | **1 项过时、1 项成立但码缺失** | ① Q39：在 A 的基线（HEAD 的 `p2_scoring`）可复现——`check_value("2026-10-30 16:00","2026-10-30 16:00")=False`，`score_case` 默认 fail（value_hit missing）；但当前 FIX-S 已修（`p2_score_public_case`=pass），A 的报告与测试已过时。② H2 逐题输入：成立——runner 在 holdout 只写 `holdout_aggregate.json`（`p2_runner.py:1947-1963`，`detail_export=False`），p2-score 必须外部 `--holdout-cases/--verdicts`；但缺输入码未实现。 |
| 14 | 合规 | **PASS** | 本验收零真实出站；未读 `.env`/H1/H2；未 commit；只写 `T207-FIX-A/{review.md,evidence/verify/}`（临时探针文件写系统 TEMP，已清理）；固定路径 SHA 前后一致。 |

## 2 复跑命令与原始输出（摘要）

- 计划/GO：`.venv/Scripts/python.exe -B -X utf8 …/evidence/verify/01-probes.py`（节选见 `02-probes.out.txt` 的 `plan_rebuild`/`preflight_real_snapshot`/`authorize_candidate`/`negatives`/`read_only_proof`）。
- 拆 run：同上 `case_files`/`ingest_coverage`/`batch_arith`/`authorization_windows`/`reorder_if_r1_first`。
- 版本槽：`.venv/Scripts/python.exe -m pytest backend/tests/integration/test_p2_product_e2e.py -k 'version_slot or document_ref or ingest_plan_document or ingest_source_rejects' -q` → **4 passed**。
- H2：`p2-h2-plan --cases-metadata <TEMP> --holdout-manifest docs/evaluation/p2-holdout-v2.manifest.json --ingest-batches 68 --plan-out <TEMP>` → `cases=30,turns=36,items=145,total_requests=212`；`plan_out_inside_workspace` / `metadata_inside_workspace` / `turn_histogram_mismatch` / `ingest_batches_over_envelope` 全拒。
- 评分/矩阵/holdout：`p2-score` / `p2-matrix` / `p2-score --visibility holdout`（假数据集，未读 H2）→ 见 `02-probes.out.txt`。
- u-controls：`p2-u-controls --out <TEMP>` → U01–U10 全 pass；测试文件 sha 不变；`--junit-xml` 独立复算 13 testcase。
- 包装器：`tools/p2_live_execute.py --env-file <TEMP> --check-only` 等 6 条；哨兵出现 0 次。
- 套件：`pytest <10 files> -q -p no:cacheprovider` 两次 → `279 passed, 1 failed`（见 `03-pytest-suite.txt`）。

## 3 发现的差异（按严重度）

**阻断（返工项）**

1. **A 的测试与 FIX-S 冲突，套件红**：`test_p2_score_run.py:334` 把 Q39 写死为 fail（`b0 passed==39`），FIX-S 修好后实际 40；两次复跑均 1 failed。A 需改 2 行（期望 40/0，并更新注释），或经理明确以 FIX-S 为准由 A rebase 后重跑。当前 269 passed 的自述不能作为验收证据。
2. **H2 候选 GO 的 `plan_id` 与 runbook 命令不一致**：GO=`P2-T207-H2-20261111`，runbook=`--plan-id P2-H2-20261111`。按 §8.1 生成计划后签发会被 `go_plan_id_mismatch` 拒。二选一对齐（推荐把 runbook 的 `--plan-id` 改成 GO 的值，或在签发时同步改 GO 并写入记录）。
3. **`holdout_input_missing` 未实现**：`p2-score --visibility holdout` 在两输入都缺时抛 `TypeError`（exit 3），不是报告 §6.3/契约 §7.4/runbook §8.4 承诺的稳定码。要么在 `_score_holdout` 入口显式拒绝，要么改三处文档；不能继续声称“缺输入即 holdout_input_missing”。

**非阻断（文档/实现小问题）**

4. `cost-and-quota` §1 仍写「硬顶 1000；余 453」（当前 1600/653）；§6「公开矩阵 255 / 小计 1,281」与 §3 的 263 矛盾（按 263 应为 1,289；+20%≈1,547，1600 结论不变）；§7「公开 8.588048」与 §3 的 8.145808 不一致；§5 H2 worst「144 × 0.044224 = 6.368256」把“每回合 0.044224”误乘 4 次（实际 36×0.044224=1.592064，加 68 批=1.731328），H2 预算结论方向不变但数值需改。
5. `runbook` §0/§4 把固定路径旧 GO 的拒因写成 `go_plan_sha256_mismatch`，实际是 `go_plan_id_mismatch`（T206 pilot 的 plan_id 不同）；§5 的「R1 期望 242/242」是计划上界，实际按真实 embedding 批次（OCR 文本 959 字→4 批）可能少于 242，建议写 ≤。
6. 报告 §1 的 `test_p2_public_cases.py` sha16 陈旧；11 个文件行数比实际多 1（计数口径）；evidence 01 的进度条是两次运行拼接（72+72+72+53=269 的完整第二次 + 前一次残余），不能证明“两次都在同一文件里”。
7. `p2-runner-contract` §7.4 已在 `b1bfa60`（B-R1 的提交）里，A 的 report 仍把它列为“本包新增”、回退章节写 `git checkout -- docs/evaluation/p2-*v0_1.md`；按该命令回退不掉 §7.4（需新 commit 反向修改）。这是并行提交把 A 的未提交内容带入历史，建议经理记录并调整回退说明。
8. `p2-u-controls` 在 Windows 下 `subprocess.run(text=True)` 解码 pytest 输出失败，stderr 有 `UnicodeDecodeError` 线程异常（不影响结果，但会污染执行日志；建议 `encoding='utf-8', errors='replace'` 或 `PYTHONIOENCODING`）。
9. 澄清类（C01–C04）的 any-of 措辞未进入评分，只判 `kind`；这是**更松**不是更严，报告 §5 的措辞应改。
10. 包装器子进程失败仍回 `ok:true`（带 `child_exit_code`）；建议 `ok=false` 或改名 `env_ok`，避免操作者误读。
11. `score_run` 的 `network_measurement_unavailable` block 只在 `summary.network` 存在且 `available!=true` 时加；若 `network` 整个缺失而回退 `attempts.reserved`，不会带该 block（与报告 §6.4 的“并带 block”不完全一致）。

## 4 限制 / NOT-RUN

- 未跑真实 `p2-run`（含全量 dry-run）、未发任何真实请求、未跑 OCR/Ragas/全仓测试。
- 未读 H2 题干/答案/密文/key；H2 的 holdout 路径只用**假数据集**验证“只出聚合/无 case_id/缺输入行为”，真实 H2 的 30 题评分未执行（按边界不允许）。
- 未验证 T206 pilot 的真实账本增量/供应商账单；账本只做只读快照与前后 SHA。
- 验收期间工作区是移动目标（B-R1 提交 `b1bfa60`、FIX-S 未提交）；本 review 的“当前”读数以 10:40 左右为准，套件复跑时间见 `03-pytest-suite.txt`。
- 未独立验证 `p2_runner.py` 的 B-R1 语义（属另一验收线）；只在报告点名套件中被动运行。

## 5 给经理的最小决策

1. **Q39**：FIX-S 已把“正确答案判 fail”修好；A 的 test 需改 2 行为 40/0（或由 FIX-S 的验收方一并改，但文件归属是 A）。此项已不再是“是否修 scorers.py”的开放决策，而是**合并顺序/测试期望**问题。
2. **H2 逐题输入**：runner 只写聚合、p2-score 必须外部封存输入，这是真实缺口；经理需决定是否接受“H2 质量结论依赖封存侧逐题文件”的流程，并要求把 `holdout_input_missing` 落到代码或从契约/报告删除。

## 6 最终建议

**返工**：保留 A 的计划/GO 重建、拆 run、ingest/版本槽、H2 生成器、评分/矩阵、wrapper 主体；先解决 §3 的 3 个阻断（测试 2 行、H2 plan_id、holdout_input_missing），再复跑套件到 280 passed 并更新 report/cost/runbook 的上述数值。阻断项均为小改，不需要重做主体。
