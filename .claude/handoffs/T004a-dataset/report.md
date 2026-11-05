# T004a 报告 · 评测数据集 + gold 解析 + fixtures（P0 第 7 包）

> 基线：`p0/obs-eval` @ `b811f9f`（p0/T003d qa legacy spans，父 `776497f`）。
> 任务单：`.claude/handoffs/T004a-dataset/handoff.md`。本包一个 commit：`p0/T004a eval dataset`（不 push）。
> 本包按主人 2026-11-05 要求不做独立验收，但证据与自证口径不变；以下全部命令均实际执行。

## 1. 完成内容

只新增评测数据层，不接 runner/门禁，不改业务代码/观测代码/冻结 fixtures：

| 交付物 | 内容 | 关键位置 |
| --- | --- | --- |
| `backend/src/mktkb/evaluation/dataset.py` | `CaseSpec`（21 字段，顺序即 JSONL 顺序）、`CASE_FIELDS`、`validate_case`、`load_cases`、`cases_to_jsonl`、`write_cases`、`dataset_version` | 字段表 `dataset.py:49`；校验 `:298`；装载 `:341`；规范 JSONL `:375`；字节写/哈希 `:382`；版本 `:393` |
| `backend/src/mktkb/evaluation/gold.py` | `GoldUnresolved`、`ResolvedSource`、`ResolvedGold`、`resolve_case`、`resolve_gold`；`unit_key` 身份型唯一、`locator` 范围型、OCR 显式 skipped、unit 去重 | `gold.py:25/41/51/144/219/245` |
| `backend/src/mktkb/evaluation/__init__.py` | 公开导出（dataset/gold） | `__init__.py:1-38` |
| `tools/build_eval_dataset.py` | B0 40 + BadCase 13 转换、离线索引逐题 `resolve_gold` 自证、两次构建字节一致 | 转换 `:208/:349`；校验 `:409`；主流程 `:438/:477` |
| `fixtures/evaluation/b0.jsonl` | 40 行，stratum exact/text/ocr = 24/8/8，OCR 8 题 `requires_ocr=true` | sha256 `bd4f0f7c…521e4f`（28903 B） |
| `fixtures/evaluation/badcase.jsonl` | 13 行，`stratum` 记录来源会话组（poster2/policy1/price4/notice2/clarify2/safety2） | sha256 `e5f0662a…07b371a`（9385 B） |
| `backend/tests/evaluation/{__init__,conftest,test_dataset,test_gold}.py` | 34 个用例；离线 session 级索引（B0 D01–D06、badcase E03/E11/P03/W01） | 装配 `conftest.py:52/82`；用例见 §2 |
| `docs/reports/OBS-EVAL/P0/evidence/T004a/00–10` | 基线/红/绿/全量/构建两次/逐题 gold/静态卫生/交付物摘要 | 见各文件 |

数据集协议（21 字段，UTF-8、`ensure_ascii=False`、`\n`、`pathlib`）：
`case_id/suite/split/stratum/business_date/question/turns/expected_kind/expected_values/expected_sources/relevant_units/reference_answer/should_refuse/refusal_reason/forbidden_values/forbidden_sources/expected_pagination/requires_ocr/labeler/label_version/notes`。
`split=dev`；`business_date=2026-10-28`；`label_version` 分别 `b0-2026-11-04` / `badcase-2026-11-04`；`suite=b0/badcase`。

## 2. §5 逐条自证（命令或 文件:行）

1. **行数与字段**
   - `fixtures/evaluation/b0.jsonl` 40 行、`badcase.jsonl` 13 行：`test_load_b0_cases_counts_fields_and_strata`（`test_dataset.py:59`）、`test_load_badcase_cases_records_source_group_and_refusal_labels`（`:79`）；证据 `08-static-hygiene.txt` 的 `lines=40/13`、`fields=[...]`。
   - stratum：B0 `{"exact":24,"text":8,"ocr":8}`；badcase 来源组计数（`:79-90`）。每行字段集合等于 `CASE_FIELDS`（`:73-75`）。
   - 21 字段中 `expected_pagination` 来自设计 §7.1（§5.1 清单未列，见 §4 偏离）。badcase `stratum` 用来源 `conversations[i].id` 作“来源 group”，未新增猜测。

2. **校验规则**
   - gold 只允许 `doc_code` + `unit_key`/`locator`/`record_code`：`SOURCE_KEYS`（`dataset.py:42`）；locator 只允许 `kind/sheet/row/heading/page/paragraph/table/column`（`:139`）。
   - 出现 `chunk_id`/`unit_id` 键，或 UUID / 32/64 位纯 hex 值直接 `ValueError`：`_reject_opaque`（`:100`）、`_reject_forbidden_keys`（`:105`）；测试 `test_case_schema_rejects_opaque_ids_and_unknown_locator_keys`（`test_dataset.py:145-160`，7 组参数）。
   - `should_refuse=true` 必须有 `refusal_reason`：`dataset.py:324-328`；测试 `:167`。
   - `turns` 与 `question` 同时为空拒绝：`dataset.py:315-317`；测试 `:173`。
   - `expected_kind` 枚举复用 `observability.contracts.OutcomeKind`（`dataset.py:44`、`:313`）；测试 `:162`。
   - 额外 fail closed：未知/缺失字段、重复 `case_id`、坏 JSON 行号、分页字段类型（`load_cases` `:341-373`；测试 `:188/:196/:179`）。

3. **OCR 处理**
   - 8 道 OCR 题 `requires_ocr=true`；来源只保留页级 locator：Q33/34 `D07:p3`、Q35/36 `D08:p2`、Q37/38 `D09:p1`、Q39/40 `D10:p1`（Q37–40 原 `image/table_row` 归一为 page=1，§5.3 允许）。
   - 测试 `test_ocr_cases_keep_page_locator_and_never_image_or_table_row_keys`（`test_dataset.py:108`）断言 locator 恰为 `{"page": int}`。
   - **未触发真实 OCR**：索引装配只解析 D01–D06（`conftest.py:45` 的 `B0_NON_OCR_KINDS`），D07–D10 从未进入索引；`test_ocr_cases_are_skipped_and_index_never_parsed_them`（`test_gold.py:53`）断言可见文档恰为 D01–D06、8 题 `skipped=True` 且 `unit_ids==()`。

4. **gold 真实可解析（离线索引 + resolve_gold）**
   - 构建脚本每次运行都建两份离线索引（临时目录，离线 provider）并逐题 `resolve_gold`，任一 unresolved 直接非 0 退出：`build_eval_dataset.py:409-474`。
   - stdout（证据 `04/05/06`）：`b0: resolved=32 no_gold=0 skipped_requires_ocr=8 units=32`；`badcase: resolved=10 no_gold=3 skipped_requires_ocr=0 units=36`。
   - 测试 `test_b0_all_40_cases_resolve_without_ocr`（`test_gold.py:36`）、`test_badcase_gold_resolves_and_negative_cases_have_no_gold`（`:67`）；逐题解析结果见证据 `06-gold-resolution.txt`（53 行明细，含每个 case 的 doc_code/unit_key/unit 数）。
   - **无法解析的 gold：0 条**。N10/N12/N13 在源数据本就无 `expected_sources`（歧义/无答案题），数据集保留为空 gold 并显式断言，未删除、未伪造。

5. **fail closed**
   - 0 匹配：`unit_key_not_found`（`gold.py:168-175`）、`locator_not_found`（`:186-193`）、`document_not_found`（`:96`）；测试 `test_gold.py:95/104/111`。
   - 同 key 多 unit：`duplicate_unit_key`（`gold.py:176-182`），用同 doc_id、不同 version_id 的两条 `rag_units` 行构造（`conftest.py:169`；DB 约束是 `(version_id, unit_key)`，未绕过任何约束）；测试 `:125`。
   - locator 命中多个 unit 但 `unit_key` 重复 → `ambiguous_units`（`gold.py:194-200`）；测试 `:132`。
   - 多个 chunk 命中同一 unit：按 unit 去重（`ResolvedGold.unit_ids` 去重 `gold.py:242`）；`test_multiple_chunks_of_one_unit_collapse_to_one_gold_unit`（`:147`）用被拆成多 chunk 的单条长记录证明仍只有 1 个 gold unit。
   - 重复引用同一来源也去重：`test_duplicate_source_references_are_deduped`（`:139`）。

6. **版本与幂等**
   - `dataset_version = suite:label_version:sha256[:12]`，摘要即规范 JSONL 字节的 SHA-256：`dataset.py:393-410`；测试 `test_dataset_version_matches_file_sha256_and_is_stable`（`test_dataset.py:219`）逐套数据断言 `version.endswith(sha256(file)[:12])`。
   - 两次连续构建输出相同：`same_as_run1=True`（证据 `05-build-run-2.txt`）；`b0 bd4f0f7ccc6e9f50ba630598c01b3519804447d4e0f3bfbc2facd54a5a521e4f`、`badcase e5f0662af3f2bf51ac9354cf467ab55be9bd3b97444ae2ba7d359d3d907b371a`。
   - `dataset_version` = `b0:b0-2026-11-04:bd4f0f7ccc6e` / `badcase:badcase-2026-11-04:e5f0662af3f2`。
   - `write_cases` 不做行尾转换（`write_bytes`），测试断言无 `\r` 且 roundtrip 相等（`:243`）。

7. **测试与回归**
   - `pytest backend/tests/evaluation -q`：**34 passed**（证据 `02-pytest-evaluation.txt`；最近一次 2.14s）。
   - 全量 `pytest backend/tests -q`：**1300 passed**（548.67s；证据 `07-full-suite.txt`）；基线 `b811f9f` 同口径 **1266 passed**（599.70s；证据 `00b-baseline-full-suite.txt`）→ 净增 34 个新用例、**0 新增失败**。
   - TDD 先红：实现未创建时 collection 2 errors（证据 `01-tdd-red.txt`），实现后绿。

8. **硬约束**
   - 证据 `08-static-hygiene.txt`：冻结/只读路径（`fixtures/acceptance`、`docs/evidence`、`rag/`、`ingestion/`、`observability/`、`qa/`、`conversations/`、`var/`）`git status` 为空；本包路径无 tracked diff。
   - 新源文件禁止模式扫描 `hits=0`（`load_dotenv`/`dotenv`/`.env"`/`os.environ`/`httpx`/`requests`/`openai`/`DASHSCOPE`/`sk-`/`bailian`）；零真实模型/OCR/embedding/rerank 调用；未读 `.env`；未打印凭据。
   - fixtures 无 `chunk_id`/`unit_id`、无 UUID/32-hex（`test_fixture_files_contain_no_opaque_ids` `test_dataset.py:122`；卫生证据 `uuid=False`）。
   - 未新增依赖：只用 stdlib + 既有 `sqlalchemy` + 项目内 `mktkb.rag` 模型/解析器。

## 3. 实际运行结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 基线全量（`b811f9f`） | **1266 passed, 1 warning in 599.70s** | `00b-baseline-full-suite.txt` |
| TDD 红 | collection 2 errors（`mktkb.evaluation.dataset` 未实现） | `01-tdd-red.txt` |
| `pytest backend/tests/evaluation` | **34 passed, 1 warning**（最近一次 2.14s） | `02-pytest-evaluation.txt` |
| 构建第 1 次 | b0 40 / resolved 32 / skipped OCR 8 / units 32；badcase 13 / resolved 10 / no_gold 3 / units 36；exit 0 | `04-build-run-1.txt` |
| 构建第 2 次 | 同上；`same_as_run1=True` | `05-build-run-2.txt` |
| 逐题 gold 解析 | 53 行明细（40 b0 + 13 badcase），exit 0 | `06-gold-resolution.txt` |
| 全量（本包后） | **1300 passed, 1 warning in 548.67s** | `07-full-suite.txt` |
| 静态卫生 | 冻结路径为空、禁止模式 hits=0、fixtures 无 UUID | `08-static-hygiene.txt` |
| 交付物 SHA-256 | 见列表（10 自身不入列表） | `10-deliverables-sha256.txt` |

构建 sha256：
- `fixtures/evaluation/b0.jsonl` = `bd4f0f7ccc6e9f50ba630598c01b3519804447d4e0f3bfbc2facd54a5a521e4f`
- `fixtures/evaluation/badcase.jsonl` = `e5f0662af3f2bf51ac9354cf467ab55be9bd3b97444ae2ba7d359d3d907b371a`

提交：单 commit `p0/T004a eval dataset`（不 push）。commit 文件清单（amend 前采集，最终 HEAD 见交付回复与 `09-final-commit-stat.txt` 的说明）：

```
 .claude/handoffs/T004a-dataset/report.md
 backend/src/mktkb/evaluation/__init__.py
 backend/src/mktkb/evaluation/dataset.py
 backend/src/mktkb/evaluation/gold.py
 backend/tests/evaluation/__init__.py
 backend/tests/evaluation/conftest.py
 backend/tests/evaluation/test_dataset.py
 backend/tests/evaluation/test_gold.py
 fixtures/evaluation/b0.jsonl
 fixtures/evaluation/badcase.jsonl
 tools/build_eval_dataset.py
 docs/reports/OBS-EVAL/P0/evidence/T004a/00-git-rev-parse.txt
 docs/reports/OBS-EVAL/P0/evidence/T004a/00b-baseline-full-suite.txt
 docs/reports/OBS-EVAL/P0/evidence/T004a/01-tdd-red.txt
 docs/reports/OBS-EVAL/P0/evidence/T004a/02-pytest-evaluation.txt
 docs/reports/OBS-EVAL/P0/evidence/T004a/03-fixture-samples.txt
 docs/reports/OBS-EVAL/P0/evidence/T004a/04-build-run-1.txt
 docs/reports/OBS-EVAL/P0/evidence/T004a/05-build-run-2.txt
 docs/reports/OBS-EVAL/P0/evidence/T004a/06-gold-resolution.txt
 docs/reports/OBS-EVAL/P0/evidence/T004a/07-full-suite.txt
 docs/reports/OBS-EVAL/P0/evidence/T004a/08-static-hygiene.txt
 docs/reports/OBS-EVAL/P0/evidence/T004a/09-final-commit-stat.txt
 docs/reports/OBS-EVAL/P0/evidence/T004a/10-deliverables-sha256.txt
```

说明：与 T003d 同口径，commit 内容无法记录自身最终短 sha；`09-final-commit-stat.txt` 是最后一次 amend 前采集的 stat（由该 amend 并入同一 commit），**最终 HEAD 短 sha 见交付回复**。基线 `b811f9f` 是已固定的父提交。

## 4. 偏离与未做（含转换规则摘要、无法解析项）

**转换规则摘要（全部离线、确定性）：**

- B0 exact（24 题）：用 `record`（P01–P08 / S01–S04）在 xlsx 的 identifier 角色列定位唯一行 → `sheet:物品位置:row:8…15` / `sheet:店家信息:row:5…8`；每行同时写 `record_code`。
- B0 text（8 题）：在 `locator.heading` 限定段落中，以“期望值连续命中数唯一最大 + 全部值可连续或按序子序列命中”定位答案段：
  Q25→`paragraph:5`、Q26→`paragraph:6`、Q27→`paragraph:4`、Q28→`paragraph:5`、
  Q29→`paragraph:p1:l6`、Q30→`paragraph:p1:l8`、Q31→`paragraph:p1:l4`、Q32→`paragraph:p1:l6`；
  原 `locator`（heading/page）保留作可读与跨版本回退。
- B0 OCR（8 题）：`requires_ocr=true`，只保留 `locator.page`；Q37–Q40 的 `image/table_row` 归一为 `page=1`（单页图片，§5.3 允许），原 locator 记入 `notes`。
- badcase（13 题）：`row`（+可选 sheet）→ 行级 `unit_key`（N01/N02/N08/N11 = `E11 sheet:物品位置:row:7`；N04/N06 = `E03 sheet:NKA卖场:row:10`）；`clause`（第七条）→ 条款段 `W01 paragraph:13`；只给 `sheet` 的 N05 是整表范围型 locator（11 units）；只给 `file` 的 N09 是整篇范围型（17 units）；N10/N12/N13 源数据无来源 → 空 gold。

**无法解析项：无（0 条）。** 构建脚本与测试均无 `GoldUnresolved`；无静默删除、无跳过失败样本。

**偏离/取舍（均已在数据与报告中显式记录）：**

1. **`locator` 多命中语义**：设计 §7.2 写“0 个或多个 unit → GoldUnresolved”。本包区分两种引用：`unit_key` 是身份型（必须恰好 1 个 unit，0/重复都失败）；`locator` 是范围型（整表/整篇天然包含多个 unit，0 命中才失败，多个命中若 `unit_key` 重复则 `ambiguous_units`）。否则 badcase N05（整张 NKA 表）/N09（整篇 P03）无法表达。§5.5 的“多匹配”用“两 unit 同 key”测试（`duplicate_unit_key`），保持 fail closed。
2. **`expected_pagination`**：§5.1 字段清单未列，但设计 §7.1 的 Case 结构包含；本包按设计纳入并统一输出 `null`。N05 源字段 `expected_min_total=1` 未伪造为四分页契约，保存在 `notes` 中（`badcase.jsonl` N05）。
3. **N11 多轮上下文**：源 `clarify` 会话中 N11（“滨江店”）承接 N10 的澄清追问。数据集 13 行保持一题一行、`turns=[]`，在 `notes` 明确“承接 N10、单轮记录、多轮上下文由 runner 负责”；未发明 turn 结构（turn schema 未在设计冻结）。
4. **`reference_answer`**：B0 取 40 题矩阵“标准答案要点”= `expected_values` 的并列（未新增事实）；badcase 源无参考答案，留空（设计 §7.1 允许 P0 为空）。
5. **OCR 页级 locator**：Q37–Q40 原 `image/table_row` 不是设计 locator 键；按 §5.3“保留 locator.page（或空 sources）”改为 page=1，同时在 `notes` 留原值，未凭空写 unit_key。
6. **badcase `stratum`**：源数据无 `group` 字段，使用 `conversations[i].id` 作为“来源 group”（poster/policy/price/notice/clarify/safety）。
7. **TDD 红证据形态**：`01-tdd-red.txt` 是“实现模块未创建”的 collection ImportError（先写测试后写实现），不是产品缺陷。

**未做（超出本包范围）：** 未接 runner/scorer/gate/baseline；未实现 `evaluation/corpus.py`（任务单 §2 交付物不含）；未对 B0 全 10 份资料建索引（OCR 4 份按设计不解析）。

## 5. 风险与遗留

1. **`locator` 回退的版本敏感性**：badcase 的 `clause → paragraph:13` 与行号类 locator 依赖当前解析器的编号规则；跨解析器版本回退可能失配。缓解：数据同时带 `unit_key`（优先）与 `label_version`；跨版本比较时按设计“优先 unit_key，不存在再回退 locator”。
2. **`dataset_version` 摘要包含 `label_version` 字段本身**：因此改 `label_version` 会同时改前缀与摘要；这是刻意让“标签版本变更”不可与“内容变更”混淆。若后续要求摘要只覆盖 case 内容，需要新版本协议。
3. **gold 解析依赖 `rag_units` 存储结构**（SQLAlchemy 查询 `RagUnit.doc_id/locator/unit_key`）：若 T005 之后索引 schema 变化，需要同步更新 `gold.py`；本包未引入新的抽象层。
4. **离线索引是“必要文件子集”**：B0 只解析 D01–D06、badcase 只解析 E03/E11/P03/W01（§7 已知边界）。这证明 gold 在真实解析产物上可定位，但不是全语料索引；全量/真实 provider 下的召回质量仍需后续 live 包验证。
5. **P0 数据集不含 Holdout**：本包只有 `b0`/`badcase`（`split=dev`）；Holdout 防污染、`--allow-holdout-details` 等属于 P1，未实现。
6. **N05 分页期望尚未被消费**：`expected_pagination=null`，`expected_min_total` 只在 notes；T004b 若要校验“至少 1 条”，需扩展分页契约或读取 notes（本包不擅自定义四分页语义）。
7. **全量测试耗时 ~9–10 分钟**（含既有集成测试），后续包验收需预留时间；本包新增测试仅 ~4.3s。

## 6. 交接摘要（≤10 行）

- 交付：`evaluation/{dataset,gold}.py` + `tools/build_eval_dataset.py` + `fixtures/evaluation/{b0,badcase}.jsonl` + 34 个测试 + 证据 00–10。
- 数据：b0 40（exact24/text8/ocr8）、badcase 13（来源会话 6 组）；`split=dev`、`business_date=2026-10-28`。
- gold：unit_key 唯一、locator 范围型；0/重复 key/重复身份 fail closed；OCR 8 题 skipped 且索引中无 D07–D10。
- 构建自证：b0 32/32 非 OCR + badcase 10/10 有 gold 全部解析；N10/N12/N13 为空 gold（源数据即无来源）；无法解析项 0。
- 幂等：两次构建 sha256 相同 `bd4f0f7c…` / `e5f0662a…`；`dataset_version=b0:b0-2026-11-04:bd4f0f7ccc6e` / `badcase:badcase-2026-11-04:e5f0662af3f2`。
- 回归：基线 1266 passed → 本包后 1300 passed（新增 34，0 新增失败）；`pytest backend/tests/evaluation` 34 passed。
- 硬约束：冻结/只读路径 0 改动；禁止模式 hits=0；0 真实调用、未读 `.env`、无新依赖。
- 偏离：locator 多命中按范围型处理（unit_key 才要求唯一）；`expected_pagination` 统一 null（N05 min_total 在 notes）；N11 turns 留空并在 notes 说明。
- 提交：`p0/T004a eval dataset`（单 commit，不 push）；最终 HEAD 见回复。
- 遗留：clause→paragraph 的跨版本回退、N05 分页语义、全语料/live 验证留给后续包。
