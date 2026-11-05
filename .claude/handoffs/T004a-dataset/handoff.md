# T004a · 评测数据集 + gold 解析 + fixtures（P0 第 7 包）

> PM 任务单。基线：`p0/obs-eval` @ T003d 收口 commit（开工前 `git log --oneline -2` 确认）。T001–T003d 已通过独立验收。
> 本包只新增评测数据层（`evaluation/{dataset,gold}.py`、构建脚本、fixtures、测试），不接 runner/门禁，不改业务代码。
> 完成后由全新上下文的独立验收助手按本文件逐条证伪。

## 1. 目标（一句话）

把 B0 40 题与 Bad Case 13 题转成符合 Case 协议的 `fixtures/evaluation/{b0,badcase}.jsonl`，实现 `CaseSpec` 校验、`dataset_version` 与稳定引用解析 `resolve_gold`（0/多匹配 fail closed），并用"离线索引真实解析"证明每条 gold 可定位。

## 2. 交付物（只准写这些路径）

- 新增 `backend/src/mktkb/evaluation/__init__.py`、`dataset.py`、`gold.py`
- 新增 `tools/build_eval_dataset.py`
- 新增 `fixtures/evaluation/b0.jsonl`（40 行）、`fixtures/evaluation/badcase.jsonl`（13 行）
- 新增 `backend/tests/evaluation/__init__.py`（如需）、`test_dataset.py`、`test_gold.py`；允许新增 `backend/tests/evaluation/conftest.py`
- 证据（入库）：`docs/reports/OBS-EVAL/P0/evidence/T004a/`
- 报告：`.claude/handoffs/T004a-dataset/report.md`（五段）

## 3. 输入（只看这些）

1. P0 设计 §7.1（Case 结构/字段规则）、§7.2（稳定引用解析与 fail closed）、§7.3（数据集与版本）。
2. P0 计划 Task 4 Step 3（B0/13 题转换规则）。
3. 数据源（只读）：`fixtures/acceptance/questions.json`（64 题，取 `group=normal` 的 40 题：exact 24 / text 8 / ocr 8）、`docs/evidence/LOCAL-R1-20261101/S1-DEV/questions.json`（13 题 N01–N13，本地文件）、`40题矩阵-题目与标准答案-20261104.md`、`fixtures/acceptance/normal/`（D01–D10 冻结语料）。
4. 代码（只读）：`rag/chunking.py`、`ingestion/parsers/{excel,word,pdf,image}.py` 的 `unit_key` 生成规则（xlsx `sheet:<名>:row:<行>`、docx `paragraph:<n>`/`table:<n>:row:<n>`、pdf `paragraph:p<页>:l<行>`）；`rag/index.py` 的 `RagIndex` 构造方式（离线确定性 provider）；`observability/contracts.py` 的 `CASE_SCHEMA_VERSION`。
5. 既有测试里如何离线构建索引（`backend/tests/rag/`、`backend/tests/acceptance/support/`）——复用既有 helper，**不要复制一大套解析逻辑**。

## 4. 允许 / 禁止

**允许**：§2 交付物；`git switch p0/obs-eval`；本包一个 commit。

**禁止**：
- 不改 `fixtures/acceptance/**`（冻结只读）、`docs/evidence/**`（只读）、业务代码、`observability/**`、其它 evaluation 模块。
- 不新增生产依赖（复用项目已有依赖与解析器；构建脚本可用 stdlib + 既有库）。
- 零真实模型/OCR/embedding/rerank 调用；不读 `.env`；不打印凭据。
- 不碰 `var/**`、账本/GO、归档区；不 push；不 commit PM 的未跟踪文件与 T003c 并发残留。
- 不弱化断言、不跳过失败样本、不把不可解析的 gold 静默丢弃（必须报错或书面列出并经 PM 裁决）。

## 5. 验收标准（逐条可判定）

1. **行数与字段**：`b0.jsonl` 40 行、`badcase.jsonl` 13 行；每行符合 Case 协议（`case_id/suite/split/stratum/business_date/question/turns/expected_kind/expected_values/expected_sources/relevant_units/reference_answer/should_refuse/refusal_reason/forbidden_values/forbidden_sources/requires_ocr/labeler/label_version/notes`）；`b0` 的 stratum=exact/text/ocr 各 24/8/8，`badcase` 记录来源 group。
2. **校验规则**：`expected_sources`/`relevant_units` 只允许 `doc_code` + `unit_key`/`locator`（及 `record_code`），出现 `chunk_id`/`unit_id` UUID 拒绝；`should_refuse=true` 必须有 `refusal_reason`；`turns` 与 `question` 同时为空拒绝；`expected_kind` 枚举合法。
3. **OCR 处理**：B0 的 8 道 OCR 题 `requires_ocr=true`，保留 `locator.page`（或空 sources），**不得触发真实 OCR**；T005 会跳过它们。
4. **gold 真实可解析**：在测试中离线构建索引——B0 的 32 道非 OCR 题（fixtures/acceptance/normal 语料）与 badcase 13 题（`corpus/enterprise-20261101` 语料）逐一 `resolve_gold` 成功、无 `GoldUnresolved`；任何无法解析的 case 必须在报告逐条列出并经 PM 裁决，不得静默删除。
5. **fail closed**：0 匹配与多匹配（测试造两 unit 同 key）都抛 `GoldUnresolved`；多个 chunk 命中同一 unit 时按 unit 去重后再算。
6. **版本与幂等**：`dataset_version = suite:label_version:sha256[:12]` 稳定；`tools/build_eval_dataset.py` 连续运行两次输出字节一致（sha256 相同）。
7. **测试与回归**：`pytest backend/tests/evaluation -q` 全绿；`backend/tests` 全量相对 T003d 收口基线无新增失败。
8. **硬约束**：不新增生产依赖；不改冻结 fixtures/docs/evidence/业务代码；不读 `.env`；零真实调用。

## 6. 必须实际运行的检查（输出原文存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD
```

```powershell
.\.venv\Scripts\python.exe -B tools\build_eval_dataset.py --b0 fixtures\acceptance\questions.json --badcase docs\evidence\LOCAL-R1-20261101\S1-DEV\questions.json --out fixtures\evaluation
# 再跑一次，比较 b0.jsonl/badcase.jsonl 的 sha256 是否一致
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\eval-dataset
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t004a-full
git show --stat --oneline HEAD
```

## 7. 已知边界（必须遵守）

- T003c 证据目录有 4 个未跟踪并发残留文件（非本包范围）；不要 add/commit，也不要清理（T003d 会清）。
- `b0` 与 `badcase` 的 `split` 用 `dev`（非 holdout）；`label_version` 分别固定 `b0-2026-11-04` / `badcase-2026-11-04`。
- `business_date` 统一 `2026-10-28`（B0 来自 acceptance 的 B0 初始状态；badcase 来自 S1-DEV 的 business_date）。
- 离线索引构建可能较慢：测试用 session 级 fixture，只解析必要文件；OCR 图片不解析。
- 所有 JSON/JSONL 用 UTF-8、`ensure_ascii=False`、路径用 `pathlib`。

## 8. 提交

分支 `p0/obs-eval`，一个 commit：`p0/T004a eval dataset`；只 add 本包交付物；不 push（amend 后重采最终 HEAD stat）。

## 9. report.md 格式

五段：完成内容 / §5 逐条自证（命令或 文件:行）/ 实际运行结果（含 commit sha、stat、全量通过数、两次构建 sha256）/ 偏离与未做（含无法解析项与转换规则摘要）/ 风险与遗留。末尾另给 ≤10 行交接摘要。
