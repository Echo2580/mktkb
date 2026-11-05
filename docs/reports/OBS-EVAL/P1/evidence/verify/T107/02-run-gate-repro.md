# T107 独立复现：regression run → gate（handoff §6.3/§6.4）

## A. 全量 regression run（local，默认语料 + 默认数据集）

```text
$env:PYTHONPATH="backend\src"; $env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite regression --mode local --out %TEMP%\t107-verify\run
```

结果：`run exit 0`，59.6s，`run_id=regression-local-20261105T145444537346Z-f28baa8a`，`cases=7`。

`run_manifest.json` 关键字段：

- `suite=regression`、`mode=local`、`scope=end_to_end`、`case_count=7`
- `dataset_version=regression:regression-p1-2026-11-05:760fb06576ce`
- `dataset_sha256=760fb06576ce991f0f9af6b13a75ed6ec0794dbb61262fdb275cfa082ae06562`
- `corpus_manifest_sha256=5f41b1b811a5fecb0c0beab1b5070540e3c622a175a59939e293cc9b17ec3218`
- `index_revision=49`

`summary.json`：`status_counts={"fail":7}`、`scored_count=7`、`error_count=0`。

逐条结果（与开发证据 01 的“修复前状态”表对照）：

| case | status | 实际 kind | 失败 checks | 与证据 01 一致 |
| --- | --- | --- | --- | --- |
| RG001 | fail | clarification | value_hit, value_no_fabricated, source_hit, kind_correct | 是 |
| RG002 | fail | ambiguous | value_hit, source_hit, kind_correct | 是 |
| RG003 | fail | clarification | value_hit, source_hit, kind_correct, pagination_total/returned/has_more | 是 |
| RG004 | fail | no_answer | kind_correct, refusal_unexpected | 是 |
| RG005 | fail | answer | kind_correct, refusal_expected | 是 |
| RG006 | fail | answer | value_forbidden, kind_correct | 是 |
| RG007 | fail | answer | kind_correct, refusal_expected | 是 |

回答文本亦与证据 01 摘要一致，例如：RG001“请补充要查询的商品名称或规格…”；
RG002“资料中有多个符合条件的对象…”；RG003“请补充要查询的门店…”；
RG004“资料‘物料领用通知’未收录…”；RG005“根据资料，启沣饮品（苏城）有限公司 市场部｜启市字〔2026〕41号”；
RG006“滨江店的宣传海报（标识：QF01）位于店内外侧，数量 40 张。”；
RG007“根据资料，第一条 新品指公司首次进入流通的单品…”。

## B. 同一 run 的 gate（初始 RED）

```text
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run %TEMP%\t107-verify\run
```

`EXIT_CODE=1`；stdout：

```text
gate exit_code=1 run_id=regression-local-20261105T145444537346Z-f28baa8a suite=regression mode=local scored=7/None hard_failures=['security_leak', 'pagination_contract'] quality=unknown config_status=unapproved
```

`gate.json`：`exit_code=1`、`hard_failures=['security_leak','pagination_contract']`、`min_sample=null`、
`unknowns` 共 80 条，其中含
`{"gate_id":"min_sample","check_id":"min_sample_missing","evidence":{"suite":"regression"}}`。

退出码优先级由 `backend/src/mktkb/evaluation/gate.py:3400-3403` 决定（`hard_failures` → 1 优先于 `unknowns` → 3）；
`min_sample_for` 缺配置返回 `None` 在 `gate.py:3331-3341` 转成 `min_sample_missing` unknown。

## C. 干净 regression run 的同一 gate（fail-closed，非静默通过）

脚本：`%TEMP%\t107_verify_clean_gate.py`（临时合成 E11 单文档语料 + 1 条可通过的 regression case，
case 带 `source_err_id=ERR-20261104-01`，`run_suite("regression","local")`，默认 `gate_v0_1.json`）。

```text
case_statuses=[["RGX01","pass",null]]
dataset_version=regression:regression-p1-2026-11-05:4e1ed00030ba
gate_exit=3  hard_failures=[]  min_sample=null
min_sample_missing_seen=true  config_min_sample={"b0":32,"badcase":13}
```

结论：regression 在 `hard_gate_min_sample` 缺省时走既有 fail-closed 语义（`unknown` / exit 3），
没有静默通过；`docs/evaluation/gate_v0_1.json` 未改（`min_sample` 仍只有 b0/badcase）。
