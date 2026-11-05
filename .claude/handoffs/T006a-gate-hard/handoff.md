# T006a · 门禁硬层（8 项）+ 退出码（P0 第 10 包）

> PM 任务单。基线：`p0/obs-eval` @ T005 收口 commit（开工前 `git log --oneline -3` 确认，HEAD 可能是 PM 簿记 commit）。
> 前置：T001–T005 已独立验收通过。本包只做**硬门禁层 + 退出码 + 配置骨架**；质量层/校准/豁免属 T006b，不得越界实现。
> 完成后由**全新上下文**的独立验收助手按本文件 §5 逐条证伪。

## 1. 目标（一句话）

实现 `evaluate_gate` 的 8 项硬门禁与退出码映射：读 T005 的运行产物，任一硬门禁失败 → 退出码 1；数据/gold/trace 不可用 → 3；`mode=live` 未授权 → 4；全部通过 → 0（2 保留给 T006b 质量回退）。硬门禁不可豁免，且不依赖内核拒绝 `mode=live`。

## 2. 交付物（只准写这些路径）

- 新增 `backend/src/mktkb/evaluation/gate.py`（`GateConfig`/`load_gate_config`/`GateResult`/`evaluate_gate`；硬门禁 8 项 + 退出码）
- 新增 `docs/evaluation/gate_v0_1.json`（**初版只含硬门禁 ID、`min_sample`、指标方向与空阈值占位**；绝对阈值由 T006b 的 `--calibrate` 提案 + 主人审批后填入）
- 新增 `backend/tests/evaluation/test_gate.py`
- 证据（入库，≤4 份）：`docs/reports/OBS-EVAL/P0/evidence/T006a/`
- 报告：`.claude/handoffs/T006a-gate-hard/report.md`（五段，≤80 行）

## 3. 输入（只看这些）

1. 设计 §8.1（8 项硬门禁判定）、§8.4（退出码）、§8.2（质量层只读参考，本包**不实现**）。
2. 计划 Task 5 Step 1/3/5（硬门禁测试形态、逐项检查、退出码/豁免）。
3. `docs/evaluation/trace_schema_v0_1.md` §3（枚举）、§6.1/§6.1.1/§6.1.2（reason-aware 必需 Span 表）、§6.2（条件 Span）、§7。
4. 已验收代码（只读）：`observability/{contracts,tracer,store}.py`、`evaluation/{dataset,gold,scorers,runner}.py`（T005 产物：`run_suite` 返回对象、`run_manifest.json`/`cases.jsonl`/`summary.json`）。
5. 现有 fixtures：`fixtures/evaluation/{b0,badcase}.jsonl`（`forbidden_sources`/`forbidden_values`/`expected_values`/`should_refuse` 等字段就是硬门禁输入）。

## 4. 允许 / 禁止

**允许**：§2 交付物；本包一个 commit；允许对 `backend/tests/evaluation/conftest.py` **追加** fixture（只增不改）。

**禁止**：
- 不改 `evaluation/{dataset,gold,scorers,runner,corpus}.py`、`observability/**`、业务代码/API/业务库与 `rag-index.sqlite3` schema、既有测试断言（conftest 只追加）。
- **不实现质量层**：不做 `calibrate_gate`/`GateProposal`/waiver 审批/`max_regression_pp` 回退检测（全部属 T006b）；不得让 gate 因为"质量指标未达标"返回 2。
- 不新增依赖；零真实模型/OCR/embedding/rerank 调用；不读 `.env`；不打印凭据。
- 不为"通过"改判分器/断言/数据集；不碰 `docs/evidence/**`、`var/**`（读取 T005 产物可以，写产物到 `%TEMP%`）、账本/GO、`evidence/verify/**`；不 push。

## 5. 验收标准（逐条可判定）

1. **8 项硬门禁逐项可达**：`security_leak`、`cross_entity`、`stale_bypass`、`conflict_not_rejected`、`exact_value_contract`、`pagination_contract`、`citation_required`、`trace_integrity` 各自有"构造失败样本 → 命中该 ID → `exit_code=1`"的测试；每个失败项带 `case_id`/`check_id`/`evidence`。
2. **trace_integrity 按 T003d 契约实现**：`require_trace=True` 时缺 Trace → fail；必需 Span 用 **`required_spans(path, outcome, reason=trace.reason)`**（含 §6.1.1/§6.1.2 的 reason-aware 行）；`status=replayed` 的记录**跳过** path/outcome 与 Span 完整性校验（只校验版本绑定与 JSON 结构）；`*_json` 字段非法 JSON → fail closed（不得抛异常崩溃、不得 fail-open）；`TRACE_SCHEMA_VERSION` 不一致 → fail。
3. **不依赖内核拒绝 `mode=live`**：gate 自己检查 run manifest 的 `mode`；`mode=live` 且无显式授权（P0 恒为未授权）→ `exit_code=4`，且不因内核 `_coerce_mode` 接受 live 而放行。
4. **退出码映射完整且互斥**：0 通过；1 任一硬门禁失败（优先于 3/4 之外的其它）；3 数据/配置/gold 解析失败/样本不足（`min_sample` 未达）；4 live 未授权或跳过；**2 在本包保留不使用**（有测试断言"质量未达标不会返回 2"或该码无触发路径）；豁免不存在——对硬门禁尝试豁免必须被拒绝（无 API 或显式报错）。
5. **PM 裁决的硬门禁口径（T004b 验收遗留）**：`value_no_fabricated` **不得**作为硬门禁输入（不得映射到 `exact_value_contract`/`security_leak`，可留作诊断字段但不参与判定）；`citation_required` **不得**仅凭 `source_hit` 通过（需 unit 级引用，或显式 `unknown`）；`record_code`-only gold 不得被当整篇命中（fail closed 或 unknown）；**`security_leak` 的 `forbidden_sources` 匹配必须在 unit 级可解析**——引用只带 `unit_ids` 而 forbidden 用 `unit_key` 时是"漏报"（T004b MEDIUM-4，`scorers.py:588-600`），gate 必须以解析后的 unit 映射比对，无法解析即 `unknown`（走退出码 3），不得默认通过。
6. **测试与回归（提速策略 A）**：`pytest backend/tests/evaluation -q` 全绿；全量 `backend/tests` **只在提交前跑 1 次**，目标 = T005 基线（1377 + T005 新增）+ 本包新增、0 failed/0 error；不新增依赖；`gate_v0_1.json` 可被 `load_gate_config` 解析且不含绝对阈值。

## 6. 必须实际运行的检查（输出摘要存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_gate.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\gate
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\eval-all
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t006a-full
git show --stat --oneline HEAD
```

另给一条命令示例：把 T005 的 local 产物（`run_manifest.json`/`cases.jsonl`/`summary.json`）喂给 `evaluate_gate`，输出 `GateResult` 摘要（`exit_code`/`hard_failures`/`unknowns`）并说明 fixtures 上没有硬失败（或列出真实命中项）。

## 7. 已知边界（必须遵守）

- **trace 是不可信输入**：gate 只读 trace 字段，不因 trace 自称 `status=ok` 就放行；必需 Span 按 path+outcome+reason 重新计算。
- `status=replayed` 的跳过是硬要求（T003a/T003d 遗留）：重放记录用 `annotate(replayed=True)` 写启动字段，不能按产品路径 Span 校验。
- 8 项硬门禁的"敏感模式/跨用户来源/stale"判定所需字段若 T005 产物未提供，必须显式 `unknown`（走 3）而不是默认通过；在报告写明缺哪些字段。
- 既有 flake `test_g08_short_budget_cancels_inflight_model_call` 与本包无关；命中则隔离复跑并记录。
- 所有 JSON 用 UTF-8、`ensure_ascii=False`；数字口径 0–1。

## 8. 提交

分支 `p0/obs-eval`，一个 commit：`p0/T006a gate hard layer`；只 add 本包交付物 + 报告 + 证据；不 push。

## 9. report.md 格式（≤80 行）

五段：1) 完成内容 2) §5 逐条自证（≤2 行/条，命令或 `文件:行`）3) 实际运行结果（包/目录/全量 + commit sha + stat + 8 项门禁触发矩阵）4) 偏离与未做（含"缺字段 → unknown"清单）5) 风险与遗留。末尾 ≤10 行交接摘要。
