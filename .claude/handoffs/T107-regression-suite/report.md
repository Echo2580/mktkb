wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T107 报告：regression suite 与数据集契约扩展（P1 第 2 包）

> 基线 `p1/fix-retrieval` @ `40901b5`；任务单 `.claude/handoffs/T107-regression-suite/handoff.md`。未切换/新建分支，未 push/amend。

## 1. 完成内容

- 新增 `fixtures/evaluation/regression.jsonl`：7 条种子，`suite=regression` / `split=dev` / `label_version=regression-p1-2026-11-05`；逐条 `stratum=defect-t101..t106` + `source_err_id=ERR-20261104-01..07`；初始 **7/7 RED**。
- `dataset.py`：新增可选 `OPTIONAL_CASE_FIELDS=("source_err_id",)`（`dataset.py:77`）；`regression` 缺该字段拒绝（`dataset.py:364`）；缺省不写入规范 JSONL，b0/badcase 字节与 `dataset_version` 不变。
- `corpus.py`/`runner.py`/`cli.py`：suite 白名单与默认清单扩为 `b0/badcase/regression`（`corpus.py:46`、`runner.py:177/244`、`cli.py:63`）；regression 复用 `corpus/enterprise-20261101` 全量，并按数据集引用的 `doc_code` fail closed（`runner.py:300`、`runner.py:1323`）。
- `gate.py`：仅补 fail-closed 口径文档（`gate.py:301`）；行为沿用既有 `min_sample_for()` 返回 `None` → `GateUnknown(min_sample_missing)`。
- 测试：新增 `backend/tests/evaluation/test_regression_suite.py`（10 个测试）；未改既有断言、无 skip/xfail。
- 证据 4 份：`docs/reports/OBS-EVAL/P1/evidence/T107/01–04`；本报告五段。1 个 commit。

## 2. 验收标准自证

1. **加载/校验**：`regression.jsonl` 经 `load_cases` 全量通过；UUID、`chunk_id`/`unit_id`、重复 `case_id`、regression 缺 `source_err_id`、未知字段均拒绝——`test_regression_suite.py:94/129/195/209/232`。
2. **向后兼容**：b0/badcase 的 `cases_to_jsonl` 与文件逐字节相等、sha256 与 `dataset_version` 均为改动前值——`test_regression_suite.py:163`；对照表见证据 02。
3. **suite 接入**：`default_corpus_dir("regression")`/`default_dataset_path`/CLI choices/`RunManifest.from_dict` 均接受 regression——`test_regression_suite.py:246/286`；`run_suite` 产出 `dataset_version=regression:regression-p1-2026-11-05:760fb06576ce`。
4. **gate 默认覆盖**：`gate_v0_1.json` 的 `hard_gate_min_sample` 仍只有 b0/badcase；干净 regression run 的 gate 为 `exit 3` + `min_sample_missing`——`test_regression_suite.py:286`、证据 03-B。初始 RED run 因硬失败 exit 1，但 `min_sample_missing` 仍在 unknowns（硬失败 1 优先于 unknown 3，非静默通过）——证据 03-A。
5. **种子映射与初始 RED**：7 条逐条映射，7/7 fail；逐条修复前 kind/failed checks/依赖见证据 01；未放宽断言、未写死退出码。
6. **回归与预算**：本包 `10 passed`；`backend/tests/evaluation` `330 passed`；全量按 §11A 检查内存后标 **NOT-RUN**（见 §3/§4）。

## 3. 实际运行结果

| 检查 | 结果 |
| --- | --- |
| 本包 `pytest tests/evaluation/test_regression_suite.py -q` | `10 passed, 1 warning in 1.21s` |
| 受影响目录 `pytest tests/evaluation -q` | `330 passed, 1 warning in 17.18s`，0 failed / 0 error |
| 全量 `pytest backend/tests -q` | **NOT-RUN**：`FreePhysicalMemory=1.179 GB`（22:37）/`1.171 GB`（22:43）< 2 GB，未启动 |
| 全量 regression run | `run_id=regression-local-20261105T144032858382Z-57a1d4fd`，7 cases，`{"fail":7}` |
| gate（同一 run） | `exit_code=1`，`hard_failures=['security_leak','pagination_contract']`，`min_sample=None`，`min_sample_missing` 在 unknowns |
| 干净 regression run gate | `exit 3`、`hard_failures=[]`、`min_sample_missing`（证据 03-B） |

提交：单 commit `p1/T107 regression suite + dataset contract extension`；sha 与 `git show --stat` 见交付回复（单 commit 无法内嵌自身 sha，未 amend）。

## 4. 偏离或未做

- **语料选择**：regression 取 `corpus/enterprise-20261101` **全量**（49 份，边界/扫描/X04 按既有 subset policy 排除），不是 badcase 4 份子集。理由：T101 需 L02、T102-policy 需 W02、T103 需 E05，badcase 子集覆盖不到；全量在本机离线约 50–90 秒，确定性可跑。
- **dataset 层无法完整表达的缺陷**（按 handoff §5 声明）：
  - T103/ERR-04：D09《物料领用通知》不在 enterprise 语料，service 层 20/100 overshoot 逻辑不在 `RagIndex.ask`；RG004 以 `kind=clarification` + `notes` 声明，候选/回落断言由 T103 包内 service 测试承担。
  - T104/ERR-07：异常按 provider/配置/预算/内部映射需 monkeypatch；RG005 只断言越界题应为 `no_answer` 且不出现 `MODEL_UNAVAILABLE`。
  - T106/ERR-05：reason→文案映射主体由 T106 包内断言；RG007 以 `kind=no_answer` + forbidden + notes 表达。
  - T102/T105 多轮：当前 runner 仍单轮（T109 才执行 `turns`）；RG002/RG003/RG006 已带 `turns`，单轮下仍为 RED，但“状态继承/指代”完整复现依赖 T109，且 T102 若选澄清口径需在 T102 包更新 RG002 的 `expected_kind`。
- **全量 pytest NOT-RUN**：内存 <2GB，按 handoff §6.6 不启动；`backend/tests/evaluation` 已全绿，未用 skip/xfail 替代。
- 未改 `docs/evaluation/gate_v0_1.json`、`fixtures/evaluation/{b0,badcase}.jsonl`、`observability/`、业务代码；无新增生产依赖；未读 `.env`/Holdout。

## 5. 风险

- 7 条 regression 种子依赖 T101–T106 的实现口径（尤其 T102 澄清/作答选择、T103/T104/T106 的 service/文案断言、T109 多轮）；在这些包收口前，regression gate 会持续 hard-fail 或 unknown，属预期，不应被当作 P1 放行依据。
