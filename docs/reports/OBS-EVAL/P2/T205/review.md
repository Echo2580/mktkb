# P2-T205 独立验收（review）

- 角色：独立验收助手（全新上下文），证伪优先；只写本 review 与 evidence/verify/。
- 现场：分支 codex/p2-e2e @ HEAD 7cbabef；T205 未提交（新增 p2_scoring.py / gate_v0_3.json / 三测试；gate.py +22/-5）。
- 真实调用：0（全 Mock / 离线）。未读 .env、H1、H2 题干；未联网；未装依赖；未改源码/测试/报告/契约/gate；未 commit/push。
- 复跑：44 passed（三文件）、109 passed（gate+quality）、136 passed（受影响 P1 控制）、7 passed（local 有界对照）、13 passed（既有 U，参数化展开）。
- 结论：**有条件通过（可接收）**。核心分母、8 硬门禁、fail-closed、公开反例全部实测成立；2b 的 L/真实标记为缺项（F1，需经理决定“补”或“书面降级到 T206”），F3 证据需重生成，F2 列 T207 前置。均非安全阻断，见 §5。

## 1. 逐条判定

| # | 验收项 | 判定 | 依据（命令/位置） |
|---|---|---|---|
| 1 | 范围与不回退 | **PASS** | git status 仅 `gate.py`(+22/-5) 与协调文档 `_index.md` 变更；fixtures/既有测试零改动；新测试无 skip/xfail/monkeypatch；query/answer 未动（见 §3） |
| 2a | 分母与精确口径 | **PASS** | 由 `fixtures/acceptance/questions.json` 的 category 现算：B0 40＝exact Q01–Q24(24)＋text Q25–Q32(8)＋OCR Q33–Q40(8)；N8/C6/U10；H2 manifest 元数据 case_count=30、strata 10/5/5/5/5；OCR 跳过→`ocr_not_executed`+`case_error`（passed 39、ocr_executed 7）；error/未执行单列且不入正确数 |
| 2b | L/真实标记分离 | **FAIL（缺项）** | `p2_scoring.py` grep `real` / `"L"` 零命中（`live` 仅出现在 `live_unauthorized` 阻断文案）；`P2CaseScore`/`P2PublicScorecard`/`P2HoldoutScorecard`/`P2GateDecision` 均无执行模式或真实调用标记 → 见 §5-F1 |
| 3 | 8 硬门禁正反例 + fail-closed | **PASS** | `test_p2_gate.py` 8 类均有正反例（trace 另有 unbound/unreadable）；not_applicable≠unknown（`test_not_applicable_vs_unknown_are_distinct`）；另由自写探针补测开发用例未直测分支：public/holdout/manifest/summary/hard_gate 缺失、8 项全 not_applicable、not_evaluated → 全部不放行 |
| 4 | 公开财务反例 4 个 + 正向 | **PASS** | 自写探针（非复用开发用例）实跑产品 Mock：F01/F02/F03/F04 判 fail，F05（6 自然日）/F06（多轮 3 工作日）判 pass；语料事实逐条核实（§4）；未接触 H2 |
| 5 | U/多轮/权限/更新删除 | **PASS** | 既有 `test_t09_mutation.py` 零改动、13 passed；多轮只判末轮、中间轮 error→整题 error；来源权限 employee 200 / 他人 403 |
| 6 | 执行码 vs 质量码 | **PASS** | `P2GateDecision` 分 `execution_exit_code`/`quality_exit_code`；shipped v0.3 unapproved → release False、exec 0 / quality 3；改 `p2_standards` 必被拒；提案不得覆盖 gate_v0_3 |
| 7 | 证据/限制 | **PASS（含 F3 缺陷）** | report 的 6 个 sha256(16)/行数与实测逐一相符（03-source-facts §4）；两条限制实测为真（§3）；`evidence/02-reproduction.txt` 中文乱码 → §5-F3 |
| 8 | 复跑 | **PASS** | `evidence/verify/01-pytest-recheck.txt`（44/109/136/7/13，全部 exit 0） |

## 2. 关键实测（可复跑）

```bash
.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_p2_scoring.py backend/tests/evaluation/test_p2_gate.py backend/tests/integration/test_p2_public_controls.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t205-verify
# 44 passed
.venv\Scripts\python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T205/evidence/verify/probe_verify.py
# A/B/C/D/E 五段全 PASS；输出见 evidence/verify/02-output-probe.txt
```

## 3. 范围/不回退与两条“限制”的独立核对

- **gate.py 行为**：`structured = False/True` 对 v0.1/v0.2 与旧 `is_v0_2` 逐值等价；v0.3 只新增分支与 `P2_GATE_CONFIG_PATH` 保护。109+136+7 复跑无回退。
- **产品 query/answer 未改**：`git status` 只有 `gate.py` 与协调文档变更；`backend/src/mktkb/{qa,conversations,rag}`、`fixtures/` 零改动。
- **限制 1（trace 无身份）实测为真**：Mock 产品一轮 trace 有 `intent_parse/retrieve/model_answer/answer_validate/commit` 五个 span 与 mode/scope/path，但 `dataset_version/pipeline_version/run_id/index_revision/manifest_sha256/config_hash` 全为 None ⇒ `trace_integrity` 必 `version_binding` 硬失败。属 fail-closed（不是绕过），T206 必须补绑定。
- **限制 2（无检索证据 id）实测为真**：`evaluate_p2_gate` 的 `citation_evidence_complete` 默认 False 且无任何代码把它算成 True ⇒ 记 unknown（exit 3）。同为 fail-closed。

## 4. 公开财务反例（自写探针，全 Mock，出站 0）

| 诱饵 | 产品实际回答（节选） | 判定 | fail 的 check |
|---|---|---|---|
| E10 其他指标目标（问 90%，表内另有 95%） | 「月份：2026-09；指标：陈列达标率；计算口径：…×100%」缺 90% | fail | value_hit |
| W03 其他分档审批人（8000 元应=市场部经理） | 整条第六条，含「事业部总经理」等 | fail | value_forbidden |
| E03 2025 旧价（2.99 vs 2.5，row14 已失效） | 只给单号/SKU/规格，缺 2.99 | fail | value_hit |
| 他实体（价目表无「咸味饼干」） | 回「启沣柠檬茶」SKU 行 | fail | kind_correct |
| 正向：结案报告时限 | 「第十二条 …6 个自然日…」 | **pass** | — |
| 正向：多轮追问活动变更 | 「第四条 …提前 3 个工作日…」（executed_turns=2） | **pass** | — |

语料核实：E10 row103=90%（row80/104 的 95% 是物料覆盖率）；E03 NKA row7=2.99、row14=2.5/2025 已失效、全表无「饼干」；W03 第六条 8000→市场部经理、第十二条 6 自然日、第四条 3 工作日。**未接触 H2、未按 H2 调参。**

## 5. 发现（非安全阻断，需经理决策）

**F1【需求缺项】L/真实标记未实现。** 任务要求“结果分别报 L（本地/Mock）与真实标记”，但评分/聚合产物无任何执行模式或真实调用字段：`P2CaseScore`、`P2PublicScorecard`、`P2HoldoutScorecard`、`P2GateDecision` 都没有；`score_public_suites().to_dict()` 也无此键。当前全部为 Mock、report 亦如实写“真实调用 0”，故**未产生虚报**。
- 最小修复：`P2CaseScore` 增 `execution_mode`（`mock/local/real`）+ run_summary 的 `real_requests` 透传到 scorecard；补 1 条“mock 不得标 real”的用例。
- 或由经理书面降级到 T206（首个真实 run 前必须到位）。

**F2【新用例标签陷阱，卡 T207】F01 不可被“正确回答”通过。**
```
'陈列达标率的年度目标是 90%。'                                   -> pass
'陈列达标率年度目标 90%；计算口径：检核合格门店数 ÷ 抽检门店数 ×100%。' -> fail(value_no_fabricated)
```
问题问“计算口径和年度目标”，但照实给出 `×100%` 会被 `value_no_fabricated` 判为编造数字（100 不在 `_gold_number_keys`）。F01 是新标签、非冻结：最小修复=给该 CaseSpec 加 `reference_answer`（含口径）或把问题收窄为“年度目标是多少”。否则 T207 修好产品仍判 fail，且 `test_p2_public_controls.py` 中“有 90% 就必须 PASS”的分支会红灯。F02/F03 已验证可被简洁正确回答通过（F02 整条法条含其他分档 → 按设计 fail）。

**F3【证据可读性】`evidence/02-reproduction.txt` 中文不可逆乱码**（"锟斤拷"形态，4978 bytes）。反例本身可复现（`evidence/verify/02-output-probe.txt` 为同 4+2 条的 UTF-8 版本）。
- 最小修复：`set PYTHONIOENCODING=utf-8`（或 `python -X utf8 probe_t205.py > 02-reproduction.txt`）重生成。

**F4【设计风险，非本包缺陷】scorecard 未与 run 绑定**：`evaluate_p2_gate` 接受调用方传入的 `public`/`holdout`/`citation_evidence_complete`，未校验其 run_id/config_hash。因 v0.3 unapproved，当前无法放行；T206/T209 接入前应把 `run_id+gate_config_hash` 写入 scorecard 并核对。

## 6. 未覆盖 / NOT-RUN

- 未跑全仓（按指示）；未跑真实模型/OCR/embedding/rerank；未执行 T206 真实 pilot、T207 产品修复、Ragas、Langfuse。
- 未验证 H2 的逐题标签质量（只读元数据，属 T202 保管面）。
- 未验证前端/浏览器链路（不属 T205）。
- 测试覆盖盲点（不影响本次判定，探针已代跑）：`public_scorecard_missing`/`holdout_missing`/`run_manifest_missing`/`run_summary_missing`/`hard_gate_missing`/`hard_gates_not_applicable`/`hard_gate_not_evaluated` 在开发用例中无直测。

## 7. 边界声明

本验收只新增：`docs/reports/OBS-EVAL/P2/T205/review.md` 与 `docs/reports/OBS-EVAL/P2/T205/evidence/verify/`（`probe_verify.py`、`01-pytest-recheck.txt`、`02-output-probe.txt`、`03-source-facts.txt`）。未改源码、测试、report、gate 配置，未 commit/push。
