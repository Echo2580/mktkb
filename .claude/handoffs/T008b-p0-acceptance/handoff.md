# T008b · P0 七条验收测试 + p0-report（P0 第 14 包）

> PM 任务单。基线：`p0/obs-eval` @ T008a 收口 commit（开工前 `git log --oneline -4` 确认）。
> 前置：T001–T008a 已独立验收通过。本包只做 P0 七条验收测试 + `p0-report.md`；不改业务/观测/评测实现。
> 完成后由**全新上下文**的独立验收助手按本文件 §5 逐条证伪。

## 1. 目标（一句话）

把设计 §11 的 P0 七条验收落成可重复执行的测试（`test_p0_acceptance.py` + golden），并产出 `docs/reports/OBS-EVAL/P0/p0-report.md`：逐条记录命令、结果、SHA-256 锚、未测边界，并写明"P0 只证明离线回归与确定性门禁，不证明真实回答质量提升"。

## 2. 交付物（只准写这些路径）

- 新增 `backend/tests/evaluation/golden/chat_response.json`（业务行为基线快照，归一化易变字段后比对）
- 新增 `backend/tests/evaluation/test_p0_acceptance.py`（七条验收）
- 允许对 `backend/tests/evaluation/conftest.py` **追加** fixture（只增不改）
- 新增 `docs/reports/OBS-EVAL/P0/p0-report.md`（入库；原始运行产物不入库）
- 证据（入库，≤4 份）：`docs/reports/OBS-EVAL/P0/evidence/T008b/`
- 报告：`.claude/handoffs/T008b-p0-acceptance/report.md`（五段，≤80 行）

## 3. 输入（只看这些）

1. 设计 §11（P0 七条验收）、§10（兼容性契约）、§8.4（退出码）。
2. 计划 Task 7 Step 1（七条测试形态）、Step 6（p0-report 必写内容）。
3. 已验收代码：`evaluation/{runner,gate,baseline,report,cli,scorers,dataset,gold,corpus}.py`、`observability/**`、`tools/rag_eval.py`。
4. 既有 integration 测试与 fixtures（`backend/tests/integration/`、`backend/tests/acceptance/support/b0.py`）——复用既有 client/trace fixtures，不复制一套 app。
5. T005/T006b 的实测指标与分母口径（p0-report 引用时不得改写）。

## 4. 允许 / 禁止

**允许**：§2 交付物；本包一个 commit；conftest 只追加。

**禁止**：
- 不改业务代码/API/响应体、不改观测内核、不改 evaluation 实现、不改既有测试断言。
- 不放宽七条验收为"只要能跑就算过"；golden 不得用当前被测代码的实时输出自我生成后立即断言（必须说明 golden 的来源与归一化规则，且能复现）。
- 不新增依赖；零真实模型/OCR/embedding/rerank；不读 `.env`；不碰 `docs/evidence/**`、`var/**`（运行产物只在 `%TEMP%` 或 `var/eval`，不入库）、账本/GO、`evidence/verify/**`；不 push。
- 不引入 `--allow-holdout-details`。

## 5. 验收标准（逐条可判定）

1. **七条齐备且非空转**：
   (1) 业务行为不变（归一化 `request_id`/`message_id`/时间等易变字段后与 golden 比对，且响应头含 `X-Trace-ID`）；
   (2) `trace_id` 端到端可查（trace 有 `request_id`、spans 非空）；
   (3) b0 与 badcase 可独立回归（两次 `run_suite` 各自产出 `summary.json`，suite 正确）；
   (4) 结果绑定 `dataset_version`/`index_revision`/`pipeline_version`；
   (5) 可生成 baseline + diff + JSON 报告（用**测试内**审批配置；真实 baseline 仍待 T009 人工审批）；
   (6) 硬门禁失败返回非零退出码（敏感来源 case → 1）；
   (7) 零真实调用（provider spy=0、socket guard=0，且未读 `.env`）。
   每条测试必须能在被破坏时失败：抽查 1–2 条做仓库外变异（如去掉 `X-Trace-ID`、放开 `exit_code` 断言）验证会红。
2. **golden 可信**：`golden/chat_response.json` 记录来源（哪次提交/哪条既有行为）与归一化字段清单；测试断言"归一化后相等"，并对易变字段显式剔除；重跑稳定。
3. **p0-report 完整**：`docs/reports/OBS-EVAL/P0/p0-report.md` 逐条列七条验收的命令、结果、证据锚（路径 + sha256）；写清未测边界（真实 OCR/embedding/rerank/模型、live、P1 质量）；包含设计要求的免责句（原文：P0 只证明离线回归与确定性门禁工作正常，不证明端到端 RAG 的真实回答质量已经提升；真实检索与生成效果在 P1/P2 用固定数据集验证）；说明质量阈值 `unapproved`、真实 baseline 待 T009。
4. **口径一致**：报告里的通过数、指标、分母（b0 32、badcase 10/13）与 T005/T006a/T006b 实测一致，不得美化；矛盾处如实标注。
5. **硬约束**：无业务行为变化（golden + 既有 integration 全绿）；无新增依赖；未读 `.env`；零真实调用；无 `--allow-holdout-details`。
6. **测试与回归（提速策略 A）**：`pytest backend/tests/evaluation -q` 全绿；全量 `backend/tests` 只在提交前跑 1 次，目标 = T008a 基线 + 本包新增、0 failed/0 error。

## 6. 必须实际运行的检查（输出摘要存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_p0_acceptance.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\p0-acc
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\eval-all
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t008b-full
git show --stat --oneline HEAD
```

另：用 T008a 的 CLI 命令真实跑一遍 P0 全流程（产物在 `%TEMP%`），把退出码与产物 sha256 写进 p0-report。

## 7. 已知边界（必须遵守）

- 质量阈值未审批、真实 baseline 未建立（T009 人工门）：七条验收中的 (5) 用 `%TEMP%` 内的审批配置演示，p0-report 必须写明"真实 baseline 待主人审批"。
- golden 必须是"改动前业务行为"的等价快照；P0 未改业务代码，可用现行行为采集，但必须在报告写清采集命令与归一化清单，不得循环自证。
- 七条中的 (6) 只证明"硬门禁失败非零退出"，不证明所有硬门禁在真实业务里都被触发。
- 既有 flake `test_g08_short_budget_cancels_inflight_model_call` 与本包无关；命中则隔离复跑并记录。

## 8. 提交

分支 `p0/obs-eval`，一个 commit：`p0/T008b p0 acceptance`；只 add 本包交付物 + 报告 + 证据；不 push。

## 9. report.md 格式（≤80 行）

五段：1) 完成内容 2) §5 逐条自证（≤2 行/条）3) 实际运行结果（七条测试逐条结果 + 包/目录/全量通过数 + commit sha + stat + p0 全流程退出码）4) 偏离与未做 5) 风险与遗留。末尾 ≤10 行交接摘要。
