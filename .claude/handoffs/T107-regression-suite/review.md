wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T107 独立验收 review：regression suite 与数据集契约扩展

> 基线 `p1/fix-retrieval` @ `36fe095`（父 `40901b5`）；1 个 commit；工作区 clean；未切分支、未 push/commit。
> 开发方 `report.md` 只作线索；以下判定全部来自本机复跑/复算，证据见
> `docs/reports/OBS-EVAL/P1/evidence/verify/T107/01..04`。

## 1. 逐条验收

| # | 验收项 | 判定 | 命令 / `文件:行` |
| --- | --- | --- | --- |
| 1 | 加载/校验：7 条种子合法；缺 `source_err_id`、未知字段、`chunk_id`/`unit_id`、重复 id 均拒 | **PASS** | `load_cases(regression.jsonl)` 全过；独立探针 5 类非法输入全部 `ValueError`；`dataset.py:77,255,362-365,397-399`；测试 `test_regression_suite.py:94-238` |
| 2 | 契约向后兼容：b0/badcase 规范字节与 `dataset_version` 不变 | **PASS** | 从 `git cat-file blob 40901b5:…` 复算：b0 `bd4f0f7c…`、badcase `e5f0662a…`，与 `36fe095`/工作区逐字节相等；`cases_to_jsonl==文件` True；版本仍 `b0:b0-2026-11-04:bd4f0f7ccc6e` / `badcase:badcase-2026-11-04:e5f0662af3f2` |
| 3 | suite 接入 corpus/runner/cli，`run --suite regression --mode local` 可执行 | **PASS** | `corpus.py:46,51-55`、`cli.py:63,444,449`、`runner.py:177,244`；独立 run 退出 0（59.6s），`dataset_version=regression:regression-p1-2026-11-05:760fb06576ce`，`index_revision=49` |
| 4 | gate 覆盖 regression，缺 `hard_gate_min_sample` 时 fail-closed | **PASS** | 干净 run：`gate exit 3`、`hard_failures=[]`、`min_sample_missing` 在 unknowns；RED run：`exit 1` 且 `min_sample_missing` 仍在 unknowns（`gate.py:3331-3341,3400-3403`）；`gate_v0_1.json` 未改 |
| 5 | ≥7 条种子逐条映射 7 项缺陷；初始 RED 状态表与实际一致 | **PASS** | 7 条 / 7 个 `ERR-20261104-01..07`（RG002+RG003 同属 defect-t102）；独立 run `status_counts={"fail":7}`，7 条的 kind 与失败 checks 与证据 01 逐行一致 |
| 6 | `backend/tests/evaluation` 全绿 + 全量 0 failed/0 error | **PASS（附 flake）** | 本包 `10 passed`；目录 `330 passed`；全量 run1 `1 failed,1602 passed`（既有 flake），run2 `1603 passed`。详见 §2/§4 |

**不通过项：无（本包改动面）。NOT-RUN：无。**

## 2. 实际运行结果（本人复跑）

| 检查 | 结果 |
| --- | --- |
| 本包 `pytest backend\tests\evaluation\test_regression_suite.py` | `10 passed, 1 warning in 1.49s` |
| 受影响目录 `pytest backend\tests\evaluation` | `330 passed, 1 warning in 27.20s` |
| 全量 run1 `pytest backend\tests` | `1 failed, 1602 passed in 378.30s`（前 2.881GB / 后 3.137GB） |
| 全量 run1 失败项 | `integration\test_lifecycle.py::test_concurrent_publish_and_global_revision_cas[v05]`（`:759`），时序 flaky |
| 该 flaky 单测隔离复跑 | 3 次均 `2 passed`；文件自 `366046d` 未改且不导入 `mktkb.evaluation` |
| 全量 run2（内存 2.521GB） | `1603 passed, 1 warning in 441.00s` |
| regression run（默认语料/数据集） | `7 cases`，`{"fail":7}`，`dataset_version` 与 sha 绑定正确 |
| RED run gate | `exit 1`，`hard_failures=['security_leak','pagination_contract']`，`min_sample_missing` 在 unknowns |
| 干净 run gate（合成 E11 语料 + 1 条 pass case） | `exit 3`，`hard_failures=[]`，`min_sample_missing` 在 unknowns |

内存门槛：22:45:22 实测 `FreePhysicalMemory=1.098GB`（<2GB，等待），22:46:19 为 `3.025GB` 后开跑；
全量两次均在 ≥2GB 时启动，无因资源中断。

## 3. 重点核验明细

- **数据契约**：`regression.jsonl` 每行 JSON 合法、`ensure_ascii=False`、无 BOM、`\n` 结尾；
  `cases_to_jsonl` 复算与文件字节相等；`expected_sources`/`relevant_units` 无 `chunk_id`/`unit_id`；
  `suite=regression`、`split=dev`、`label_version=regression-p1-2026-11-05` 全量一致。
- **初始 RED**：RG001 clarification、RG002 ambiguous、RG003 clarification、RG004 no_answer
  （期望 clarification）、RG005/007 answer（期望 no_answer）、RG006 answer（期望 clarification）；
  回答文本与证据 01 摘要吻合（例：RG001“请补充要查询的商品名称或规格…”，RG006 倾倒“店内外侧/40 张”）。
- **gate 语义**：exit 1 优先于 exit 3 的硬失败优先级来自 `gate.py:3400-3403`；干净 run 证明
  regression 缺阈值时不是静默通过，而是 `unknown/3`；`gate_v0_1.json` 的 `hard_gate_min_sample`
  仍为 `{"b0":32,"badcase":13}`，未被本 commit 触碰。
- **测试真实性**：无 `skip`/`xfail`；commit 只新增测试文件，未改既有测试；断言覆盖字节、版本、
  拒绝路径与 gate 退出码；未见“只调用不断言”的空转。
- **改动范围**：`git show --stat 36fe095` 共 12 文件，全部落在 handoff §3 允许路径；无业务代码、
  `observability/`、b0/badcase、gate 配置、依赖文件改动；1 个 commit，工作区 clean。
- **格式**：证据恰 4 份；report 51 行、五段、首行模型说明符合要求。

## 4. 发现与风险（不改变通过结论）

1. **全量 flaky（既有）**：`test_lifecycle.py:759` 并发发布用例在 run1 失败、run2 与单测 3 次均通过；
   文件自 `366046d` 未改、不导入 evaluation，与本包无关。若 PM 采用“全量必须一次 0 failed”的字面口径，
   该 flake 是仓库级问题，需单独立项，不应要求 T107 返工。
2. **RG003 混合了 pagination 硬失败**：问句“给出所有内容”会触发 enumerate，初始 RED 额外产生
   `pagination_contract` 硬失败；证据 01 有说明，但 report §4 未单独列出。T102 修复时需确认该硬失败随回答路径收敛，
   否则该 seed 会长期 hard-fail（不构成本包失败）。
3. **badcase 装配校验略放宽**：`corpus.py:203-209` 由 `parsed_codes != required` 改为只查 `missing`；
   因 badcase 仍用 `only_codes=BADCASE_CODES`，实际行为不变（低风险）。
4. **验收预算**：全量执行了 2 次（§11A 列 1 次），第 2 次仅用于区分 flaky 与本包回归，已如实记录。
5. 开发报告 §3 的全量 NOT-RUN 与当时实测内存（1.179/1.171GB）自洽；本次在内存恢复后补跑，不视为虚假陈述。

## 5. 限制

- 未调用真实模型/embedding/rerank/OCR；未读 `.env`、未读 Holdout；未修改任何交付物。
- 未验证 T101–T106/T109 修复后的回归转绿（本包只要求初始 RED 与契约接入）。
