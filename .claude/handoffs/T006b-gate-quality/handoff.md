# T006b · 门禁质量层 + 校准 + 豁免（P0 第 11 包）

> PM 任务单。基线：`p0/obs-eval` @ T006a 收口 commit（开工前 `git log --oneline -3` 确认）。
> 前置：T001–T006a 已独立验收通过。本包在 T006a 的硬门禁之上增加**质量层、`--calibrate` 提案、质量 waiver**；不改硬门禁判定与退出码优先级。
> 完成后由**全新上下文**的独立验收助手按本文件 §5 逐条证伪。

## 1. 目标（一句话）

按 stratum 与总体实现质量门禁（绝对阈值 + 同版本 baseline 的 `max_regression_pp` + `min_sample`），用 `calibrate_gate` 从一次真实 run 生成 `gate_proposal.json`（观测值 + 建议阈值 + 配置 hash），质量门禁可带 `reason`/`approver` 豁免，阈值未审批时质量结果只能 `unknown`（exit 3），**绝不冒充通过**；退出码 2 只由质量回退触发。

## 2. 交付物（只准写这些路径）

- 修改 `backend/src/mktkb/evaluation/gate.py`（追加质量层 + `calibrate_gate` + `GateProposal` + waiver；**不改** T006a 的 8 项硬门禁语义与 0/1/3/4 映射）
- 修改 `docs/evaluation/gate_v0_1.json`（追加指标定义：`absolute_min`/`absolute_max`/`max_regression_pp`/`min_sample`/`direction`；**阈值保持空占位 + `status: "unapproved"`**，审批由主人在 T009 人工门完成）
- 新增 `backend/tests/evaluation/test_gate_quality.py`（不改 T006a 的 `test_gate.py` 既有断言；允许追加）
- 证据（入库，≤4 份）：`docs/reports/OBS-EVAL/P0/evidence/T006b/`（含 `gate-proposal.json` 与一次真实 run 的质量观测摘要）
- 报告：`.claude/handoffs/T006b-gate-quality/report.md`（五段，≤80 行）

## 3. 输入（只看这些）

1. 设计 §8.2（指标清单与属性：`absolute_min/absolute_max`、`max_regression_pp`、`min_sample`、`direction`；按 stratum + 总体；不设综合分）、§8.3（baseline 身份、同版本才做回退检测）、§8.4（退出码）。
2. 计划 Task 5 Step 4/5（质量门禁、首轮校准、退出码/豁免）。
3. `docs/evaluation/gate_v0_1.json`（T006a 初版）与 `evaluation/gate.py`（T006a 实现）。
4. T005 的 run 产物：`run_manifest.json`/`cases.jsonl`/`summary.json`（字段见 T005 handoff §5；`scored_count` 已排除 OCR/error）。
5. T005 验收实测（T006b 校准的唯一现有观测）：b0 Recall@10/MRR@10/nDCG@10 = 0.96875 / 0.869792 / 0.895458；badcase = 0.767914 / 0.716667 / 0.685102；b0 local 3 fail（Q25/Q26/Q31）、badcase 4 fail（N05/N06/N09/N11）。

## 4. 允许 / 禁止

**允许**：§2 交付物；本包一个 commit；允许对 `backend/tests/evaluation/conftest.py` **追加** fixture（只增不改）。

**禁止**：
- 不改 T006a 的 8 项硬门禁判定、`unknown`/`not_applicable` 口径、0/1/3/4 退出码语义；不得让 waiver 作用于硬门禁。
- 不改 `evaluation/{dataset,gold,scorers,runner,corpus}.py`、`observability/**`、业务代码/API/schema、既有测试断言；不新增依赖；零真实模型/OCR/embedding/rerank；不读 `.env`。
- 不把阈值"拍脑袋"写成已审批：未获审批时 `status` 必须仍是 `unapproved`，质量结果 `unknown`。
- 不碰 `docs/evidence/**`、`var/**`（读 T005 产物可以）、账本/GO、`evidence/verify/**`；不 push。

## 5. 验收标准（逐条可判定）

1. **质量指标按 stratum + 总体**：读 `summary.json` 的指标，按 `stratum` 与 `all` 各自评估；不产生综合分；指标清单至少覆盖设计 §8.2 的检索/答案/拒答/运行四组（缺失指标显式 `unknown`，不默认 0）。
2. **阈值语义完整**：`absolute_min`/`absolute_max` 按 `direction` 判定；有同版本 baseline 时同时检查 `max_regression_pp`（只在 `pipeline_version` 相同时启用；跨版本必须拒绝回退判定并标 unknown）；`min_sample` 用 `scored_count`（b0=32、badcase=10），样本不足 → `unknown` → exit 3。
3. **校准提案**：`calibrate_gate(run, config)` 产出 `GateProposal`（每个指标/stratum 的观测值、建议阈值、`gate_config_hash`、`run_id`），写成 `gate_proposal.json`；**不得自动改写** `gate_v0_1.json`；未审批时质量评估返回 `unknown`（不得返回 0 冒充通过），有测试证明"未审批 → unknown → exit 3"。
4. **退出码 2 只由质量回退触发**：硬门禁失败仍是 1（优先级高于 2）；样本不足/未审批仍是 3；质量未达绝对阈值或回退超限 → 2；测试证明 1 不被 2 覆盖。
5. **waiver 规则**：质量门禁可豁免，必须带 `reason` + `approver`，豁免记录进入 `GateResult.warnings` 与报告；缺任一字段 → 拒绝（报错或保持失败）；**对硬门禁申请豁免必须被拒绝**（有测试）；豁免不改变已发生的硬失败。
6. **测试与回归（提速策略 A）**：`pytest backend/tests/evaluation -q` 全绿；全量 `backend/tests` 只在提交前跑 1 次，目标 = T006a 基线 + 本包新增、0 failed/0 error；`gate_v0_1.json` 可被 `load_gate_config` 解析且 `status=unapproved`、阈值空。

## 6. 必须实际运行的检查（输出摘要存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_gate_quality.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\gateq
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\eval-all
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t006b-full
git show --stat --oneline HEAD
```

另给一条真实链路：用 T005 的 local run 产物跑 `calibrate_gate` → 产出 proposal（写入证据目录）；再用同一 run 在"未审批"配置下 `evaluate_gate` → 证明退出码 3 且 `unknowns` 含质量指标；用一份 fixture 审批配置 → 证明通过时 exit 0、回退时 exit 2。

## 7. 已知边界（必须遵守）

- **阈值审批是人工门**（T009）：本包只产出提案，不替主人拍板；`gate_v0_1.json` 的 `status` 保持 `unapproved`。
- 质量指标分母只算 `scored_count`（排除 OCR 与 error 行）；`value_no_fabricated` 仅可作诊断字段，**不得**参与质量判定或退出码（T004b MEDIUM-1）。
- 拒答相关质量指标排除 `error`/`service_error`/`knowledge_changed`（T004b MEDIUM-2）。
- 跨版本 baseline 只能分析、不可放行（设计 §8.3）；`max_regression_pp` 不得跨 `pipeline_version` 生效。
- 既有 flake `test_g08_short_budget_cancels_inflight_model_call` 与本包无关；命中则隔离复跑并记录。

## 8. 提交

分支 `p0/obs-eval`，一个 commit：`p0/T006b gate quality layer`；只 add 本包交付物 + 报告 + 证据；不 push。

## 9. report.md 格式（≤80 行）

五段：1) 完成内容 2) §5 逐条自证（≤2 行/条）3) 实际运行结果（包/目录/全量 + commit sha + stat + 质量观测与 proposal 摘要 + 退出码矩阵）4) 偏离与未做 5) 风险与遗留。末尾 ≤10 行交接摘要。
