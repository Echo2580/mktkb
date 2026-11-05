# T004a 独立验收报告

- 验收对象：`574e288`（`p0/T004a eval dataset`，父 `b811f9f`）；分支 `p0/obs-eval`。当前 HEAD `9d52b7c` 仅簿记：`git diff --stat 574e288 HEAD -- backend/src/mktkb/evaluation fixtures tools backend/tests/evaluation` 只有 T004b 新增 `scorers.py`/`test_scorers.py`，T004a 交付路径未被改动（证据 03）。
- 总判定：**PASS**。§5.1–§5.8 全部 PASS；两处 PM 指定口径为非阻断偏离（§A），另有 3 项 MEDIUM、2 项 LOW 遗留（§2）。
- 环境：每会话 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；`.\.venv\Scripts\python.exe -B`；串行 3 次 pytest（本包 34 / 目录 104 / 全量 1377）；basetemp 均在 `%TEMP%`。零真实模型/OCR/embedding/rerank，未读 `.env`。

## 1. §5 逐条判定

| 标准 | 判定 | 复跑证据 |
| --- | --- | --- |
| §5.1 行数/字段/分层 | PASS | 独立探针 `load_cases`：b0=40、badcase=13；21 字段逐行齐全且顺序等于 `CASE_FIELDS`；b0 exact/text/ocr=24/8/8；badcase 来源组 2/1/4/2/2/2；与源 `fixtures/acceptance/questions.json`、`S1-DEV/questions.json` 逐题比对 `question/expected_values/expected_kind/stratum` 均 0 差异；无 CR。证据 02/03。`expected_pagination` 见 §A2。 |
| §5.2 校验规则 | PASS | 独立直调 `validate_case`：`chunk_id`/`unit_id` 键、UUID/32hex `unit_key`、未知 locator 键、缺 `doc_code`、`should_refuse` 无 reason、`question+turns` 全空、非法 `expected_kind` 全部 `ValueError`；实现见 `dataset.py:99-113, 298-338`；证据 02。 |
| §5.3 OCR 处理 | PASS | 8 道 OCR 题 `requires_ocr=true`，sources 仅 `locator.page`、无 `unit_key`；B0 索引只解析 D01–D06（`conftest.py:52-79`）；OCR case 在 `gold.py:221-229` 短路 skipped，传 `index=None` 仍 skipped；把 Q33 的 flag 改 false 后因 D07 不在索引而 `document_not_found`；无 OCRGateway 注入、无 D07–D10 解析。证据 02。 |
| §5.4 gold 真实可解析 | PASS | 独立探针自建离线索引（B0 D01–D06；badcase E03/E11/P03/W01）逐题 `resolve_gold`：B0 32/32 非 OCR 成功、badcase 13/13 成功，`GoldUnresolved=0`；N10/N12/N13 空 gold 保留（源本无来源）；逐题 unit 明细见证据 02，与开发 `06-gold-resolution.txt` 的 53 行逐条一致。 |
| §5.5 fail closed | PASS（范围型 locator 偏离见 §A1） | 0 匹配：`document_not_found`/`unit_key_not_found`/`locator_not_found` 均抛 `GoldUnresolved`；同 doc 两 unit 同 key → `duplicate_unit_key`；locator 命中同 key 两 unit → `ambiguous_units`；单 unit 拆 7 chunk → `unit_ids==("D90-long",)`；`gold.py:165-216, 240-241`；证据 02。 |
| §5.6 版本与幂等 | PASS | 两次构建分别输出到 `%TEMP%\t004a-build-1/2`：b0/badcase sha256 完全相同，且与仓库已提交文件逐字节相同；`dataset_version` 复算稳定并等于 `suite:label_version:sha256[:12]`；`dataset.py:393-408`；证据 02。 |
| §5.7 测试与回归 | PASS | `pytest backend/tests/evaluation/test_dataset.py test_gold.py` = **34 passed**；`pytest backend/tests/evaluation` = **104 passed**（含 T004b）；`pytest backend/tests` = **1377 passed, 0 failed/error**（520.71s）；证据 01。HEAD 全量含 T003d R1（+7）与 T004b（+70），1300+7+70=1377；T004a 路径自 `574e288` 无改动（证据 03）。未重跑旧 commit 基线全量（按提速策略）。 |
| §5.8 硬约束/提交边界 | PASS | `git show --name-status 574e288` 23 文件全部落在 handoff §2 允许路径；无 `fixtures/acceptance`、`docs/evidence`、业务/observability/`var`/依赖清单改动；新源码禁止模式 `hits=0`；验收窗口内（外部 PM 写 `_index.md` 前）`git diff --stat` 为空、冻结路径 status 为空；当前唯一 tracked 改动是外部 PM 的 `_index.md` 簿记（非本包/非本验收者，证据 03）。 |

## A. PM 指定两处口径判断

**A1 `locator` 范围型：可接受偏离（非阻断）。** 实测 0 匹配仍 fail closed；`unit_key` 身份型仍要求恰好 1 个 unit（0/重复都失败）；多 chunk 同 unit 去重成立；放宽只发生在“无 unit_key、只有 locator 且命中多个不同 unit_key”的范围语义。但设计 §7.2:260 字面是“0 个或多个 unit → GoldUnresolved”，实现 `gold.py:182-199` 对范围型多命中返回全部 unit，仅同 key 重复报 `ambiguous_units`，属对 §7.2 字面的放宽，不是对 handoff §5.5 操作口径（“两 unit 同 key”）的违反；N05 整表 11 unit、N09 整篇 17 unit 只能这样表达。结论：不判 FAIL，记 MEDIUM，需 PM 在设计层追认“unit_key 身份型 / locator 范围型”并写入 §7.2；否则 T004b/T005 可能把整页/整表命中误当精确 gold，且当前范围命中数无上限。

**A2 `expected_pagination` 统一 null：不构成 §5.1 字段缺失，但 N05 分页事实仅存 notes。** 设计 §7.1:236 确有该字段，实现按设计保留 21 字段；§5.1 清单未列它，但“符合 Case 协议”不排除设计已有字段，故不是字段缺失。风险是 53 行（40+13）全部 null；N05 源 `expected_min_total=1` 只在 `badcase.jsonl` N05 的 notes 字符串里，未写入结构化 `expected_pagination`；`PAGINATION_KEYS` 已含 `min_total`（`dataset.py:44`），所以“不伪造四分页契约”不足以解释不写 `{"min_total":1}`。结论：§5.1 PASS，记 LOW 数据保真缺口；T004b 若校验分页必须先把 notes 提升为结构化字段或新增契约；T006 不应声称 badcase 已覆盖分页语义。

## 2. 问题分级

- **BLOCKER**：无。**HIGH**：无。
- **MEDIUM-1**：`locator` 范围型与设计 §7.2 字面不一致，需 PM 追认；范围命中无上限（见 A1）。
- **MEDIUM-2**：`record_code` 只被校验、不参与解析；`{"doc_code":"D01","record_code":"P01"}` 实测解析为 D01 全部 9 个 unit（`gold.py:200-208`），T005 若允许 record-only gold 会静默扩大 gold。当前 fixtures 未使用，故不阻断。
- **MEDIUM-3**：badcase N06（“那这个组合价什么时候失效？”）依赖 N04/N05 上下文，但 `turns=[]` 且 notes 未说明；报告只记录了 N11 的上下文（`fixtures/evaluation/badcase.jsonl:6`）。T005 单轮 runner 可能误判 N06。
- **LOW-1**：N05 `expected_min_total` 只在 notes（见 A2）。
- **LOW-2**：报告引用 `__init__.py:1-38`，实际文件 28 行；仅文档引用瑕疵。
- **INFO**：Q37–Q40 的 `page=1` 是从单页图片推断（原 locator 为 image/table_row，notes 留原值）；badcase 用 `stratum` 承载来源 group；`00-git-rev-parse.txt` 记录的是基线 b811f9f 而非 574e288（报告已说明）；全量在 HEAD 跑，含 T003d R1/T004b 新增，不是 574e288 时点纯树；T005 未跟踪文件与 `_index.md` 修改在验收期间出现（`_index.md` 更新 T004a/T004b 行并引用本 review），均非本次产物。

## 3. 未覆盖 / NOT-RUN

- 未重跑 `b811f9f` 基线全量（提速策略明确不重跑）；无回归结论由“全量 0 failed/error + T004a 34 + 574e288 改动范围”支撑，属推定而非同树对照。
- 未做仓库内变异；仅做仓库外独立探针 + 断言抽查。未覆盖 `record_code`-only、`document_ambiguous`、`document_has_no_units`、分页正例、跨版本（V01/V02、P03 变更）解析。
- 未做真实 OCR/embedding/rerank（禁止）；OCR 无调用由“不解析 D07–D10 + 无 OCRGateway 注入 + resolve 短路”证明，不是运行时拦截计数。

## 4. 对 T005 的遗留风险

- 范围型 locator 的 gold 是 unit 集合而非唯一命中；T005 不要把它当精确引用，需定义范围评分/上限。
- N06/N11 是会话跟进题，`turns=[]`；T005 单轮执行会丢失上下文，建议在 runner 层补上下文或标记。
- N05 的 `expected_min_total=1` 仅在 notes；T005/T004b 不能从 `expected_pagination` 读取。
- `record_code` 不是解析键；T005 若支持 record-only 引用会得到整文档 gold。
- OCR Q33–Q40 必须按 `skipped_requires_ocr` 排除分母（与 handoff 一致）。
- `dataset_version` 摘要包含 `label_version`；改标签版本会改摘要，版本比较不要误判为内容变化。

## 5. 复跑证据

- `docs/reports/OBS-EVAL/P0/evidence/verify/T004a/01-pytest-reruns.txt`（34/104/1377）
- `.../02-independent-probe-and-build.txt`（逐题 gold、fail-closed、两次构建 sha256）
- `.../03-commit-boundary-and-hygiene.txt`（提交边界、冻结路径、源数据比对、静态卫生）
- `.../probe_t004a.py`（仓库外探针；只写 `%TEMP%`）
