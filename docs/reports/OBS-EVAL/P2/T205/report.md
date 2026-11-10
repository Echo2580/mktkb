# P2-T205 开发报告：确定性评分、公开财务反例与 P2 硬门禁（gate_v0_3 初始 unapproved）

- 角色：P2-T205 开发助手（全新上下文），只实施 T205，不自验通过。
- provider/model/effort：由宿主入口决定（任务书 §12 规定 wb / cn:deepseek-v4.1-flash / max）；本包没有自检模型入口的接口，故不声称"已核"。
- 分支/HEAD：codex/p2-e2e @ 7cbabef（起止一致；未切分支、未 commit/push、未建 worktree）。
- 真实调用：0（全 Mock；未读 .env / H1 / H2，未联网，未碰 var/，未装依赖）。
- 只改 T205-dev.md 允许的文件；未改冻结期望/断言，未加 skip/xfail。

## 1. 改动清单（行数 / sha256 前 16）

| 状态 | 文件 | 行数 | sha256 | 说明 |
|---|---|---|---|---|
| 新增 | backend/src/mktkb/evaluation/p2_scoring.py | 1798 | 67f297eb74ea6768 | 产品响应→EvalOutcome、公开分母、H2 聚合、P2 门禁判定 |
| 新增 | docs/evaluation/gate_v0_3.json | 215 | 3af301dba2d4dbd1 | 初始 unapproved；阈值全 null；p2_standards=已批准目标 |
| 新增 | backend/tests/evaluation/test_p2_scoring.py | 577 | ba63d1300d38740c | 19 用例（分母/OCR/error/隔离/H2） |
| 新增 | backend/tests/evaluation/test_p2_gate.py | 837 | d98aff20f8294be0 | 20 用例（8 硬门禁正反例 + fail-closed 判定） |
| 新增 | backend/tests/integration/test_p2_public_controls.py | 509 | 63bc6349df976cc7 | 5 用例（公开财务反例/正向/多轮/权限/U 复用） |
| 改动 | backend/src/mktkb/evaluation/gate.py | +22/-5 | 7e54fbf672cbc1c0 | 最小扩展：v0.3 配置可加载（见 §5） |
| 新增 | docs/reports/OBS-EVAL/P2/T205/ | — | — | 本报告 + evidence（3 入口） |

**未改**：scorers.py、gold.py、dataset.py、runner.py、p2_runner.py、product_adapter.py、p2_ingestion.py、业务 API/schema、fixtures/acceptance、fixtures/evaluation、既有测试。

## 2. 口径（任务书 T205 第一条/第五条）

- **分母冻结**（验收矩阵 §1/§3/§4/§5）：B0=40 题（Q01–Q40，其中精确 Q01–Q24=24、text Q25–Q32=8、OCR Q33–Q40=8）；N=8（N01–N08）；C=6（C01–C06）；U=10（U01–U10）；H2=30（10/5/5/5/5），通过门槛 ≥24/30 且硬失败=0。
- **OCR 不静默跳过**：P1 的 resolve_case 对 requires_ocr 一律 skipped；P2 用"不做索引的 ResolvedGold(skipped=False)"把 OCR 题照常打分（p2_scoring._resolved_without_index）。任何 skipped_requires_ocr 行 → 记 case_error + ocr_not_executed，不计入正确数。
- **error/未执行不计入正确数**：P2CaseScore 只有 pass/fail 计入 executed；error/not_executed 单列并阻断。evaluated_count 与 gate 的 min_sample 口径不变（pass/fail 且非 OCR、非 error）。
- **H2 只聚合**：aggregate_holdout 只输出计数（total/executed/passed/hard_failures/by_stratum），to_dict 显式 detail_export=false 并有泄漏守卫（出现 case_id/question/text 即报错）。
- **执行码与质量码分开**：P2GateDecision 同时记 execution_exit_code（run 是否成功完成）与 quality_exit_code（配置/证据/硬门禁/分母），互不冒充；release_allowed 需两者都过。

## 3. 8 硬门禁 + fail-closed 判定（第二条）

- 每类都有正反例：security_leak（forbidden 值）、cross_entity/stale_bypass（上游 hard_filter_violation 信号；无信号=not_applicable）、conflict_not_rejected、exact_value_contract、pagination_contract、citation_required（无引用 / 非 unit 级 / 不在 evidence）、trace_integrity（缺 trace / 身份未绑定 / 仓储不可读=unknown）。
- not_applicable ≠ unknown：无该类 case 记 not_applicable；缺 outcome/缺 store/缺样本记 unknown（exit 3）；8 项全 not_applicable → 额外 unknown（不得算通过）。
- 不放行清单（均为实测用例）：gate 未审批、旧 gate（v0.2）、同 gate_version 改配置（config_hash 不一致=hard；未绑定=unknown）、跨 scope（retrieval_only）、gate_version 不一致、不完整 run（stop_code/未执行/error）、样本不足（B0<32）、公开分母缺失/多题、H2 未审批/样本不足/分层不符/error/硬失败/低于 24。

## 4. 公开财务反例：先复现，再定点修？——**未改业务代码，理由见下**

复现（evidence/02-reproduction.txt，可复跑 probe_t205.py；全 Mock，出站=0）：

| 诱饵类型 | 问题（公开语料） | 现行产品回答 | 评测判定 |
|---|---|---|---|
| 其他指标的目标值 | E10 陈列达标率的计算口径和年度目标 | 只给月份+指标+口径，**缺 90%** | fail（value_hit） |
| 条号/分档 | W03 单场预算 8000 元由谁审批 | 整条第六条（含"事业部总经理"等其他分档） | fail（value_forbidden） |
| 年份 | E03 2026 Q4 档期特价 | 只给单号/SKU/规格，**缺 2.99**；检索同时带 2025 旧行 | fail（value_hit） |
| 他实体 | E03 咸味饼干 120g 批发价（价目表无此商品） | 回**启沣柠檬茶**的 SKU 行 | fail（kind_correct） |
| 正向对照 | W03 活动结束后几日内上交结案报告 | 6 个自然日（第五章） | **pass** |

- 评测器侧：冻结诱饵文本的确定性用例证明"其他指标目标值 / 他分档审批人 / 2025 旧价 / 他实体 SKU"都不会被判通过；正向对照 pass。
- **未修改 query/answer 分支**：可复现缺陷是"规则路径丢数值字段 + 他实体越界作答"，修它要动 query 字段词表 + 分档/实体判定 + 答案拼装（4+ 文件、跨 P1 控制面），不是"最小定点"；且任务书把这些产品缺陷的修复排在 **T207 定点修复**。T205 已把反例固化为公开可复跑用例与阻断规则，修复前后都成立（用例按"回答是否含诱饵/正确值"给判，不把缺陷写成期望）。**请经理决定是否追加一个小修复单**。
- 有资料支持的正向问题仍可答：W03 第十二条（6 日）、多轮追问"活动变更是提前多久"→3 个工作日，均实测 pass（多轮按末轮判分，中间轮 error 即整题 error）。

## 5. gate.py 最小扩展：调用者与影响

- 新增常量 CONFIG_SCHEMA_VERSION_V0_3 / GATE_VERSION_V0_3 / P2_GATE_CONFIG_PATH；load_gate_config 增加 v0.3 分支（与 v0.2 共用结构化校验，is_v0_2→structured 仅为改名）；write_gate_proposal 增加 P2_GATE_CONFIG_PATH 保护。
- 影响面：v0.1（硬门禁骨架）与 v0.2（P1 retrieval）行为逐字不变（structured=False/True 与旧布尔一致）；新增拒绝路径只对 v0.3 生效。调用者：p2_scoring.load_p2_gate_config / evaluate_p2_hard_gates；现有 evaluate_gate 调用者不受影响。
- 已跑门禁相关 P1 控制 245 passed（见 §6），未跑全仓。

## 6. 实际命令与结果（本机亲跑，原始输出 evidence/01-pytest.txt）

```
.venv/Scripts/python.exe -B -m pytest backend/tests/evaluation/test_p2_scoring.py backend/tests/evaluation/test_p2_gate.py backend/tests/integration/test_p2_public_controls.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t205
→ 44 passed（19+20+5），exit 0
```
受影响 P1 control（gate.py 改动）：
- test_gate.py + test_gate_quality.py → 109 passed，exit 0
- test_t112_gate_baseline.py + test_diff_release_gate.py + test_cli.py + test_report.py + test_holdout_suite.py + test_regression_suite.py → 136 passed，exit 0
有界 local 对照（B0/badcase/regression 各一轮）：test_p0_acceptance.py → 7 passed（其中 #3/#4 各跑 b0+badcase local；版本=当前工作树 7cbabef+本包改动），exit 0。

## 7. 偏差 / 限制（如实）

1. **P2 trace 未带评测身份**：产品 trace 没有 dataset_version/pipeline_version/run_id/config_hash 绑定，因此对真实 P2 产物跑 trace_integrity 会 fail（version_binding/trace_missing）——这是 fail-closed 的预期结果，不是本包缺陷；T206 采集侧需绑定身份。用例用合成 trace 证明正例可达。
2. **检索证据 id 缺失**：P2 产物只有来源摘要与计数，不能证明"引用 ⊆ 本轮 evidence"，evaluate_p2_gate 以 citation_evidence_complete=False 记 unknown（exit 3）；T206 需补采集。
3. **H2 阈值未审批**：gate_v0_3 初始 unapproved；H2 即使 25/30 且硬失败 0 也只报观测值（unknown），放行判定一律 False（用例覆盖"approved 配置对象 → pass"的逻辑路径，仅证明判定可实现，不构成放行）。
4. **公开 C/U 上游**：C01–C06/U01–U10 仍是既有验收场景（fixtures/acceptance/questions.json + test_t09_mutation.py），本包只复用其 id/断言，不另造一套；U 的执行仍由既有测试跑（本包未削弱、未重跑）。
5. 未做：真实模型/OCR/embedding/rerank、T206 GO/账本、T207 产品修复、T208 Ragas、全仓回归、浏览器/Playwright。

## 8. 证据入口（≤4）

1. evidence/01-pytest.txt：上表四条命令的原始输出（44/109/136/7 passed，全部 exit 0）。
2. evidence/02-reproduction.txt：public 财务反例复现（产品回答 + p2 判定 + 出站 0 / RAG POST 0 / 真实请求 0）。
3. evidence/probe_t205.py：可复跑生成器（stdout；归档文件用 `-X utf8` 重定向生成，R2 起 02 为 UTF-8 可读版；不读 .env / H1/H2）。
4. 本报告（含 gate/分母口径与限制）。

## R2 加固（2026-11-10，对照 T205 验收 2b-FAIL / F2 / F3 / F4）

- 现场/边界：`codex/p2-e2e` @ `d850b49`（未 commit/push）；只改本包允许文件；真实调用 **0**，未读 `.env`/H1/H2、未联网；未跑全仓。
- **C1(2b，验收 FAIL 项) L/真实标记到位**：`P2CaseScore` / `P2PublicScorecard` / `P2HoldoutScorecard` / `P2GateDecision` 增加
  `execution_mode`（`local_mock` / `live`）与 `real_calls`，并写进各自的 `to_dict()`。默认是**保守**的 `local_mock`/0；
  要标 `live` 必须显式传（`score_public_case(..., execution_mode="live", real_calls=N)` / `aggregate_holdout(...)` / `evaluate_p2_gate(...)`）；
  mock 上声称 `real_calls>0` 直接抛 `real_calls_without_live_mode`，拼错的模式名抛 `execution_mode_invalid`；
  公开矩阵按逐题派生（混用模式抛 `execution_mode_mixed`），判定按 public+holdout 派生并与调用方声明核对。
- **C2(F2) F01 标签自相矛盾已修**：给 F01 的 `CaseSpec` 加 `reference_answer`（含 2026-09/陈列达标率/口径 ×100%/目标 90%）。
  现在"照实回答"（含 `×100%`）判 **pass**，而缺 90% 或换成 95% 仍 fail；`test_p2_public_controls.py` 里"含 90% 就必须 PASS"分支
  不再是红灯陷阱。**未改冻结 fixtures**（F01 是 T205 新建、非冻结标签）；`probe_t205.py` 内同名 CaseSpec 同步同一口径。
- **C3(F3) 证据可读**：`evidence/02-reproduction.txt` 用 `-X utf8` 重生成（4272B，无替换字符，中文正常）；
  内容随时点更新：F01 现仅差 `value_hit`（缺 90%），不再被 `value_no_fabricated` 误伤。
- **C4(F4) run 绑定量力而为**：`P2PublicScorecard` / `P2HoldoutScorecard` / `P2GateDecision` 增 `run_id`；`evaluate_p2_gate` 从
  `run_manifest.run_id` 取身份，scorecard 的 `run_id` 与之不符 → `run_binding_mismatch`（unknown，不放行）；
  调用方显式 `run_id` 与 manifest 冲突 → `run_id_mismatch` 直接报错。**跨 run 的 config_hash 级绑定仍留 T206/T209**：
  scorecard 由纯计数构成、不含 gate 配置身份，强行塞 `config_hash` 会制造"看起来绑定了"的假象；T206 采集侧补 `run_summary.gate_*` 后一并核对。
- 复跑（本机亲跑）：`pytest test_p2_scoring.py test_p2_gate.py test_p2_public_controls.py` → **51 passed**（22+23+6，原 44 + 新增 7）；
  受影响门槛套件 `test_gate.py test_gate_quality.py` → **109 passed**；`probe_t205.py` 出站 0 / RAG POST 0。
  原始输出见 `../R2/evidence/01-pytest.txt`，判定摘要见 `../R2/evidence/02-probe-outputs.txt`、`../R2/evidence/03-r2-semantics.json`。


## T206-PRE 补充（2026-11-11，T205 §7 限制 1/2 的补采集）

- 现场/边界：`codex/p2-e2e` @ `a8f2a6b`（未 commit）；只改 T205 允许文件 + 本报告追加；
  真实调用 **0**；未改 `gate.py`、未改 `gate_v0_3.json`（门禁阈值/分母零变化）。
- **限制 1（trace 无评测身份）已补**：Mock 产品路径把 `run_id/dataset_version/manifest_sha256/
  pipeline_version/index_revision/config_hash` 绑进 `TraceRecord`（contextvar + 适配器最外层
  middleware，业务代码零改动）；实测把真实 run 产物接进 `build_gate_run` + `evaluate_p2_hard_gates`
  后 `trace_integrity == "pass"`；未绑定/只绑半套仍 fail-closed。
- **限制 2（检索证据 id）已补**：产品 `sources[].source_id`（unit 级）解析成稳定证据身份
  （unit_id/unit_key/locator/document_id/version_id/version_number/state/active/in_run），
  判定函数 `citation_evidence_status` 只在**全部作答轮的引用都核实**时给 `complete=True`；
  缺证据/未核实仍是 unknown。**未新增 API 字段**（`SourceSummary` 不变）。
- **C4 遗留的 config_hash 级绑定已补**：`run_manifest/summary/gate` 与两个 scorecard 都带
  `config_hash`（`binding_config_hash` 由 dataset/pipeline/索引/provider/gate 身份确定性算出），
  `evaluate_p2_gate` 新增 `run_binding_missing`（缺 run_id）、`config_hash_unbound`、
  `config_hash_binding_mismatch`（均 unknown 不放行）；`P2GateDecision.binding_config_hash` 记录依据。
- 新增用例（本包 3 个，全部在本目录既有测试文件内）：
  `test_binding_config_hash_is_deterministic_and_config_sensitive`、
  `test_citation_evidence_status_only_counts_verified_identity`、
  `test_gate_blocks_missing_run_id_and_config_binding`。
- 复跑：`test_p2_scoring.py test_p2_gate.py integration/test_p2_public_controls.py` → **54 passed**
  （原 51 + 新增 3）；`test_gate.py test_gate_quality.py` → **109 passed**（未变）。
- 契约：`docs/evaluation/p2-live-binding-v0_1.md`；统一报告 `docs/reports/OBS-EVAL/P2/T206-PRE/report.md`。
