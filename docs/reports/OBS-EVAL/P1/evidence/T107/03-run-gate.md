# T107 证据 03：regression run → gate 与 min_sample fail-closed

## A. 初始 RED 全量 regression run 的 gate

命令（仓库根目录）：

```text
set PYTHONPATH=backend/src
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run <tmp>/t107-run
```

输出：

```text
gate exit_code=1 run_id=regression-local-20261105T144032858382Z-57a1d4fd suite=regression mode=local scored=7/None hard_failures=['security_leak', 'pagination_contract'] quality=unknown config_status=unapproved
wrote <tmp>/t107-run/gate.json
```

- `scored=7`（7 条 seed 全部进入 `evaluated_count`），`min_sample=None`（`gate_v0_1.json` 没有 regression 阈值）。
- `gate.json.unknowns` 含 `min_sample_missing`：
  `{"gate_id":"min_sample","check_id":"min_sample_missing","reason":"gate 配置没有该 suite 的 min_sample，样本充足性无法证明","evidence":{"suite":"regression"}}`。
- 退出码为 `1` 而非 `3`，是因为初始 RED 种子产生了**硬失败**（gate 设计：硬失败 1 优先于 unknown 3）：
  - `security_leak` / RG006 / `forbidden_value`：leaked `["店内外侧","40 张"]`（T105 指代倾倒全字段的旧行为）；
  - `pagination_contract` / RG003 / `pagination_contract_violation`：`给出所有内容` 触发 enumerate 但无分页数据（T102/T103 旧行为）。
- 这不是“静默通过”：门禁同时记录了 `min_sample_missing`，且硬失败本身拒绝放行。

## B. 干净 regression run 的同一 gate（证明缺阈值时 exit 3）

用临时合成语料（E11 一份）+ 一条可通过的 regression case 跑 `run_suite("regression","local")`，
再以同一 `gate_v0_1.json` 评估：

```text
case_status pass
gate_exit 3
hard_failures []
min_sample None
min_sample_unknowns [{'gate_id': 'min_sample', 'case_id': None, 'check_id': 'min_sample_missing', 'reason': 'gate 配置没有该 suite 的 min_sample，样本充足性无法证明', 'evidence': {'suite': 'regression'}}]
quality_status unknown
config_min_sample {'b0': 32, 'badcase': 13}
```

结论：regression 缺 `hard_gate_min_sample` 时按既有 fail-closed 语义 `unknown / exit 3`，不会静默通过。
该路径已固化为测试：
`backend/tests/evaluation/test_regression_suite.py::test_regression_run_and_gate_fail_closed_without_min_sample`
（断言 `gate.hard_failures == ()`、`gate.exit_code == 3`、存在 `min_sample_missing`）。

## 约束

- `docs/evaluation/gate_v0_1.json` 未修改（阈值审批是主人门，T112 才做）；`config_min_sample` 仍是 `{"b0":32,"badcase":13}`。
- 未调用真实 provider；gate 只读 run 产物与数据集，未写回门禁配置。
