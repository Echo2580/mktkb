# T107 交接单：regression suite 与数据集契约扩展（P1 第 2 包）

> 基线：分支 `p1/fix-retrieval`（自 `main@083eaef`；T100 已收口）。前置：T107 依赖 P0 已完成；PRE-1 Holdout 已就绪（**本包禁止读取 Holdout 目录**）。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 1. 目标（一句话）
新增 `suite=regression` 数据集与契约/加载/门禁接入，种子用例覆盖 7 项必修缺陷并带 `source_err_id` 映射；回归用例**初始为 RED**（修复前失败、修复后转绿），现有 b0/badcase 行为与字节不变。

## 2. 输入（先读这些，只看指定范围）
1. `.claude\handoffs\2026-11-04-p1-design.md` §3（7 项必修缺陷表）与 §4（数据集/Holdout 协议）。
2. `.claude\handoffs\2026-11-04-p1-task-breakdown.md` T107 段。
3. `docs\evaluation\eval_data_v0_1.md`（Case 契约 §2/§3/§8）。
4. 代码现状：`backend\src\mktkb\evaluation\{dataset,corpus,runner,cli,gate}.py`；测试 `backend\tests\evaluation\`。
5. 错误记录：`错误记录-20261104.md` §二（ERR-20261104-01～07 的现象/期望/证据）；只读。
6. `fixtures\evaluation\b0.jsonl`、`badcase.jsonl` 各读 1–2 行了解字段（**禁止修改**）。
7. P0 数据契约细节：`docs\evaluation\trace_schema_v0_1.md` 只需 §6.1 的 reason-aware 表（gate 用）。

## 3. 交付物（只准写这些路径）
1. `fixtures/evaluation/regression.jsonl`（新增；≥7 条种子，见 §5）
2. `backend/src/mktkb/evaluation/` 内的**最小 wiring**：`dataset.py`（契约扩展）、`corpus.py`（suite→语料映射）、`runner.py`（suite 白名单）、`cli.py`（suite choices）、`gate.py`（suite 枚举/min_sample fail-closed 路径）。**PM 澄清**：拆解稿允许 `dataset.py`+`gate.py`，但验收②要求 gate 默认覆盖三套件，故允许 evaluation 模块内的最小 wiring；**不得**改 `observability/`、业务代码、其他模块。
3. `backend/tests/evaluation/` 内新增/最小修改测试。
4. `docs/reports/OBS-EVAL/P1/evidence/T107/`（≤4 份证据）
5. `.claude/handoffs/T107-regression-suite/report.md`（五段，≤80 行）
6. 1 个 commit（见 §7）

**不要写**：`fixtures/evaluation/{b0,badcase}.jsonl`、`docs/evaluation/gate_v0_1.json`、`docs/evidence/**`、`var/**`、账本/GO、业务代码、`.claude/handoffs` 其他文件（report.md 除外）。

## 4. 允许 / 禁止
- 允许：evaluation 模块内最小 wiring；新增 regression 数据与测试；只读读 b0/badcase/语料/错误记录。
- 禁止：修改 b0/badcase 数据集或改其 `dataset_version`/规范字节；改 `gate_v0_1.json`（阈值审批是主人门，T112 才做）；放宽/删除既有断言；`skip`/`xfail` 掩盖失败；真实模型/embedding/rerank/OCR；读 `.env`；读 Holdout 目录；切换分支/push；新增生产依赖。

## 5. 数据与缺陷映射要求
- 字段沿用 `eval_data_v0_1.md` §2（一行一 JSON，UTF-8，`ensure_ascii=False`）；新增**可选**字段 `source_err_id`（regression 套件必填，b0/badcase 省略且字节不变）。
- 每个种子：`suite="regression"`、`split="dev"`、`label_version`（建议 `regression-p1-2026-11-05`）、`stratum` 用缺陷组标签（如 `defect-t101`）、`source_err_id` 用错误记录编号（如 `ERR-20261104-03`）。
- **逐条映射（≥7 条，每项必修缺陷至少 1 条）**：
  | 包 | 缺陷 | 种子方向（来自设计 §3 回归证据列） |
  |---|---|---|
  | T101 | ERR-03 词表误伤 | 法规题（《明码标价和禁止价格欺诈规定》何时施行/废止哪两个规定）不得被判"采购价格缺失" |
  | T102 | ERR-01 组 A | 多轮：先问城东店海报 → 再问「城西区的宣传海报在哪」；不得沿用城东店实体 |
  | T102 | ERR-02 | 多轮：先问某店物料 → 再问「档期物料要提前多少天提报需求」；不得回显未提及实体 |
  | T103 | ERR-04 记录路 | 「物料领用通知图片要求先填写什么」不得"无解澄清"，应回落/给候选信息 |
  | T104 | ERR-07 产品侧 | 异常场景按真实原因分类，不得一律 `MODEL_UNAVAILABLE`（dataset 层能表达的用 kind/forbidden/notes） |
  | T105 | ERR-06 指代 | 「那个海报呢」有上文时不得倾倒整条记录全字段（期望澄清要哪项信息） |
  | T106 | ERR-05 文案 | 每种 outcome/reason 文案唯一且诚实（dataset 层用 kind + notes；文案主体由 T106 包内断言） |
- **初始 RED 语义**：种子表达"修复后应达到的行为"；本轮**不要求绿**，但必须能在 `mode=local` 下确定性跑出 `CaseResult`（pass/fail），并在证据中记录"修复前状态"表。若某缺陷无法用 dataset 层字段完整表达，允许用 `notes`/`reference_answer` 声明并**在报告 §4 显式列出**"该条依赖 T1xx 包内断言"。
- regression 语料：复用 `corpus/enterprise-20261101`（与 badcase 同源）；具体取全量还是 badcase 子集由开发按"可确定性运行 + 覆盖种子所需资料"选择，**必须在 report 写明选择与理由**。

## 6. 验收标准（逐条可判定，≤6 条）
1. **加载/校验**：`regression.jsonl` 经 `load_cases` 全量通过；重复 `case_id`、`expected_sources` 含 `chunk_id`/`unit_id` UUID、regression 缺 `source_err_id`、未知字段 → 均按 §8 校验要求失败（有测试）。
2. **契约扩展向后兼容**：b0/badcase 的 `load_cases` + `cases_to_jsonl` 规范字节与 `dataset_version` **与改动前完全一致**（有测试或证据：变更前后 sha 对照）。
3. **suite 接入**：`SUITES`（corpus/runner/cli）与 gate suite 处理包含 `regression`；`dataset_version = regression:<label_version>:<sha12>`；`run --suite regression --mode local` 与 `gate`（以该 run）可执行，不因未知 suite 报错。
4. **gate 默认覆盖**：默认 suite 清单为 `b0`/`badcase`/`regression` 三套；gate 在配置缺 regression `hard_gate_min_sample` 时按既有 fail-closed 语义（unknown/退出码 3），**不得静默通过**；不得改 `gate_v0_1.json`。
5. **种子映射与初始 RED**：≥7 条种子逐条 `source_err_id` 映射；证据含"修复前状态"表（每条 seed 在 local 的 status/原因），并说明哪些缺陷依赖后续包断言；**不得用放宽断言/写死退出码的方式假装绿**。
6. **回归与预算**：`backend/tests/evaluation` 全绿 + 全量 `backend/tests` 0 failed / 0 error（§11A：本包 1 次 + 受影响目录 1 次 + 全量 1 次；全量前看 `FreePhysicalMemory`，<2GB 标 NOT-RUN 并说明）。

## 7. 提交要求
- 分支 `p1/fix-retrieval`（不要切换/新建/ push/ amend 历史）。
- 提交前 `git status --short` 只应含：`fixtures/evaluation/regression.jsonl`、evaluation 源文件、`backend/tests/evaluation/` 测试、`docs/reports/OBS-EVAL/P1/evidence/T107/**`、report.md。
- **1 个 commit**，消息：`p1/T107 regression suite + dataset contract extension`。
- report.md 记录 commit 信息（sha 写入交付回复即可，report §4 说明口径即可，不必内嵌自身 sha）。

## 8. 报告格式（五段，≤80 行）
1) 完成内容；2) 验收标准自证（每条 ≤2 行，带命令/`文件:行`）；3) 实际运行结果（本包 / `backend/tests/evaluation` / 全量各一行 + commit sha + stat）；4) 偏离或未做（含"无法用 dataset 表达的缺陷"清单）；5) 风险（一句话）。
