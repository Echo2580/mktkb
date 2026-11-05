# T107 独立核对：改动范围、测试真断言、报告格式（handoff §6.5/§7/§8）

## A. 改动范围（`git show --stat 36fe095`）

`12 files changed, 641 insertions(+), 25 deletions(-)`；`40901b5..HEAD` 仅 1 个 commit
（`36fe095 p1/T107 regression suite + dataset contract extension`），工作区 clean。

| 文件 | 是否在允许路径 |
| --- | --- |
| `fixtures/evaluation/regression.jsonl`（新增，7 行） | 是 |
| `backend/src/mktkb/evaluation/cli.py` / `corpus.py` / `dataset.py` / `gate.py` / `runner.py` | 是（evaluation 最小 wiring） |
| `backend/tests/evaluation/test_regression_suite.py`（新增） | 是 |
| `docs/reports/OBS-EVAL/P1/evidence/T107/01-04`（4 份） | 是 |
| `.claude/handoffs/T107-regression-suite/report.md` | 是（报告本身） |

未出现：`fixtures/evaluation/{b0,badcase}.jsonl`、`docs/evaluation/gate_v0_1.json`、
`backend/src/mktkb/observability/**`、业务代码、`pyproject/requirements`、`.claude/handoffs` 其他文件。
现有测试文件未被修改/删除（`git show --name-status -- backend/tests` 只有新增文件）。

## B. 测试是否真断言

- 无 `pytest.mark.skip` / `xfail`；`Select-String` 在 `backend/tests/evaluation/*.py` 无命中。
- 10 个测试全部有实际断言，且断言的是行为/字节，不是“只调用不检查”：
  - 种子映射 `test_regression_suite.py:94-126`（逐 stratum 的 `source_err_id` 集合、7 个 err id 全集、`should_refuse`/`refusal_reason`）；
  - 规范字节与版本 `:129-138`（`cases_to_jsonl == 文件字节`、`dataset_version` 公式）；
  - b0/badcase 向后兼容 `:163-176`（硬编码 sha256 / `dataset_version`、`source_err_id` 不存在、键集合恰为 `CASE_FIELDS`）；
  - 可选字段仅显式设置时出现 `:179-187`；
  - 缺 `source_err_id` 拒绝 `:195-206`，未知字段/UUID/chunk_id 拒绝 `:209-229`，重复 `case_id` 拒绝 `:232-238`；
  - suite 白名单/CLI/默认路径 `:246-259`；
  - run→gate fail-closed `:286-325`（`status=="pass"`、`exit_code==3`、`hard_failures==()`、`min_sample_missing` 存在）。
- 未发现放宽/删除既有断言：commit 未触碰既有测试，且 `backend/tests/evaluation` 330 passed。

## C. 报告与证据格式

- `report.md` 共 51 行（≤80），首行 `wb / cn:deepseek-v4.1-flash / reasoning_effort=max`，
  五段齐全：完成内容 / 验收标准自证 / 实际运行结果 / 偏离或未做 / 风险。
- `docs/reports/OBS-EVAL/P1/evidence/T107/` 恰 4 份：`01-prefix-status.md`、`02-backward-compat.md`、
  `03-run-gate.md`、`04-test-results.md`（≤4）。
- 证据 01 的“修复前状态”表经独立 run 逐条核对：7/7 status=fail，kind 与失败 checks 全部一致（见本目录 02 文件 A 节）。
- 证据 02 的 sha/版本数字经 git 旧 blob 复算一致（见本目录 03 文件 A 节）。
- 证据 03 的 RED gate（exit 1 + `min_sample_missing`）与干净 gate（exit 3）均复现（见本目录 02 文件 B/C 节）。
- 证据 04 的 NOT-RUN 声明与开发时内存实测（1.179/1.171 GB < 2 GB）自洽；本次验收在内存 ≥2 GB 后补跑全量，
  结果见本目录 01 文件。

## D. 观察（不构成验收失败）

- `corpus.py:203-209` 把 badcase 原先的 `parsed_codes != required` 放宽为仅检查 `missing`；
  因 badcase 仍以 `only_codes=BADCASE_CODES` 装配，实际行为不变（风险低）。
- `RG003` 的问句“给出所有内容”会把 ERR-02 种子同时推到 enumerate/pagination 硬失败路径；
  report §4 未单独列出该条硬失败的依赖（证据 01 RG003 行有说明）。初始 RED 下可接受，
  但 T102 修复时需确认该硬失败是否随回答路径收敛。
- `cli.py:130-131` 的 `dataset build` 仍只打印/构建 b0/badcase（有意，regression 手工维护），
  与 handoff 允许的最小 wiring 不冲突。
