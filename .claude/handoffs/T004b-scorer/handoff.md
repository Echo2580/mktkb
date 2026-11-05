# T004b · scorer（值/来源/kind/分页/拒答/检索指标）（P0 第 8 包）

> PM 任务单。基线：`p0/obs-eval` @ T004a 收口 commit（开工前 `git log --oneline -2` 确认）。T001–T004a 已通过独立验收。
> 本包只新增打分器与测试，不做 runner/门禁。完成后由全新上下文的独立验收助手按本文件逐条证伪。

## 1. 目标（一句话）

实现确定性 `score_case`：值命中、来源命中、kind 正确、分页契约、引用精确/召回、拒答三指标、检索指标（Recall@10 / MRR@10 / nDCG@10 / 硬过滤违规 / 空召回）、延迟与成本字段；全部输出 `CaseResult` 的逐项 check（id/status/evidence），不依赖任何具体 provider 返回类型。

## 2. 交付物（只准写这些路径）

- 新增 `backend/src/mktkb/evaluation/scorers.py`（含 `EvalOutcome` 归一化输入、`score_case`、各指标函数）
- 新增 `backend/tests/evaluation/test_scorers.py`；允许新增/追加 `backend/tests/evaluation/conftest.py` 的 fixture
- 证据（入库，**提速策略 A/C：≤4 份关键证据**）：`docs/reports/OBS-EVAL/P0/evidence/T004b/`（00 基线、01 本包、02 evaluation 目录、03 全量一次；不重复跑全量、不存大段输出）
- 报告：`.claude/handoffs/T004b-scorer/report.md`（五段模板，**≤80 行**）

## 3. 输入（只看这些）

1. P0 设计 §7.1（Case 字段）、§7.2（gold 解析/去重）、§8.2（质量指标清单：Recall@10、MRR@10、nDCG@10、hard_filter_violation_rate、empty_recall_rate、value_hit、source_hit、kind_correct、citation_precision/recall、refusal_recall/false_refusal_rate/refusal_precision、P50/P95、Token、单题成本）。
2. P0 计划 Task 4 Step 4 的 scorer 段（`EvalOutcome` 字段：kind/text/citations/facts/pagination/trace_id/path；`score_case(case, resolved, outcome, trace) -> CaseResult`）。
3. 已验收代码（只读）：`evaluation/{dataset,gold}.py`（`CaseSpec`/`ResolvedGold`/`GoldUnresolved`）、`observability/contracts.py`（Trace 字段）、`observability/store.py`；`qa`/`rag` 的返回类型（只读参考，不得 import 业务包做判分依赖）。
4. 现有相关测试的归一化口径（`backend/tests/acceptance/support/b0.py` 的 `value_present`/`normalize` 仅作参考，不要复制业务判分器）。

## 4. 允许 / 禁止

**允许**：§2 交付物；`git switch p0/obs-eval`；本包一个 commit。

**禁止**：
- 不改 `evaluation/{dataset,gold}.py`、不改 runner/gate/baseline/report、不改业务代码/观测内核、不改既有测试。
- 不新增依赖；零真实模型/OCR/embedding/rerank 调用；不读 `.env`；不打印凭据。
- 不记录问题/答案原文到证据（测试可用合成/固定文本，但证据目录不要留真实业务原文）。
- 不碰 `docs/evidence/**`、`var/**`、`fixtures/**`、账本/GO、归档区；不 push。

## 5. 验收标准（逐条可判定）

1. **值命中**：全角/半角、大小写、空白归一化正确（`Ｂ区１号货架` ↔ `B区1号货架`、多余空格）；数字不误配（`12` 不命中 `120`）；`expected_values` 命中判定与"不得编造额外数值"分开（有 check 可查）。
2. **来源命中**：`doc_code` + `unit_key`（或 locator）匹配；引用到无关 unit 不计命中；`relevant_units` 与引用 unit 按 unit 去重后计算 `citation_precision`/`citation_recall`。
3. **kind 正确**：answer/clarification/no_answer/conflict/refusal 与 case 期望比较；拒答样本按 `should_refuse` 判。
4. **分页契约**：`total/returned/has_more/next_page` 四项按契约校验（缺失/类型错误 → 对应 check fail）。
5. **拒答三指标分离**：`refusal_recall`、`false_refusal_rate`、`refusal_precision` 三个字段各自计算、互不替代；测试用混合样本证明三者数值不同。
6. **检索指标**：`Recall@10`、`MRR@10`、`nDCG@10` 在 unit 级（多 chunk 同 unit 去重）计算，有手工小样本对照；`hard_filter_violation_rate` 与 `empty_recall_rate` 可量化；无 gold 的 case 不进入检索指标分母（T003c/P1 负样本口径）。
7. **确定性**：同一输入两次 `score_case` 输出完全一致（无随机/时间依赖）；每个 check 有稳定 `id/status/evidence`。
8. **测试与回归（提速策略 A）**：`pytest backend/tests/evaluation -q` 全绿；全量 `backend/tests` **只在提交前跑一次**，目标 = T004a 收口基线通过数 + 本包新增测试数、0 failed/0 error；不要求重跑旧基线套件。不新增依赖、零真实调用。

## 6. 必须实际运行的检查（提速策略 A/C：共 3 次 pytest，输出摘要存证据）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_scorers.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\scorers
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\eval-all
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t004b-full
git show --stat --oneline HEAD
```
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\eval-all
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t004b-full
git show --stat --oneline HEAD
```

## 7. 已知边界（必须遵守）

- T003d 证据目录若有并发残留，不要动；PM 未跟踪文件不要动。
- 所有 JSON/JSONL 用 UTF-8、`ensure_ascii=False`；路径 `pathlib`。
- `EvalOutcome` 只做"归一化输入"用途，**不要**为了让 scorer 好写而修改 `RagAnswer`/业务返回类型。
- 数值/百分比口径在函数 docstring 与报告里写明（0–1 还是 0–100，统一 0–1）。

## 8. 提交

分支 `p0/obs-eval`，一个 commit：`p0/T004b scorer`；只 add 本包交付物；不 push（amend 后重采最终 HEAD stat）。

## 9. report.md 格式（提速策略 C：≤80 行）

模板：1) 完成内容（文件清单一句话）2) §5 逐条自证（每条≤2 行，命令或 `文件:行`）3) 实际运行结果（包/目录/全量各一行 + commit sha + stat）4) 偏离与未做 5) 风险与遗留。末尾 ≤10 行交接摘要。
