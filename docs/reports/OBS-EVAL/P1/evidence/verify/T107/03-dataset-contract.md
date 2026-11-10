# T107 独立复算：数据集契约与向后兼容（handoff §6.1/§6.2）

## A. b0/badcase 旧 blob vs 新 blob vs 工作区

方法：`git cat-file blob <rev>:<path>` 取原始字节 → `sha256`；再用 HEAD 代码
`load_cases` / `cases_to_jsonl` / `dataset_version` 复算规范 JSONL。

| 数据集 | 40901b5 sha256 | 36fe095 sha256 | 工作区 sha256 | 规范 JSONL==文件 | dataset_version |
| --- | --- | --- | --- | --- | --- |
| b0 | `bd4f0f7ccc6e9f50ba630598c01b3519804447d4e0f3bfbc2facd54a5a521e4f` | 同左 | 同左 | True | `b0:b0-2026-11-04:bd4f0f7ccc6e` |
| badcase | `e5f0662af3f2bf51ac9354cf467ab55be9bd3b97444ae2ba7d359d3d907b371a` | 同左 | 同左 | True | `badcase:badcase-2026-11-04:e5f0662af3f2` |

- b0/badcase 文件内均不含 `source_err_id`；`CaseSpec.to_dict()` 键集合仍为 `CASE_FIELDS`。
- 结论：规范字节与 `dataset_version` 与父 commit `40901b5` 完全一致。

## B. regression 数据集

`fixtures/evaluation/regression.jsonl`（7 行，UTF-8，`ensure_ascii=False`，无 BOM，`\n` 行尾）：

- `sha256=760fb06576ce991f0f9af6b13a75ed6ec0794dbb61262fdb275cfa082ae06562`
- `dataset_version=regression:regression-p1-2026-11-05:760fb06576ce`
- `cases_to_jsonl(load_cases(...)) == 文件字节`：True；每行均为合法 JSON 对象
- `suite` 全为 `regression`；`split` 全为 `dev`；`label_version` 全为 `regression-p1-2026-11-05`
- `stratum`：defect-t101 / t102 / t103 / t104 / t105 / t106（6 组）；case_id RG001–RG007
- `source_err_id`：ERR-20261104-01…07，7 项各 1 条，无遗漏/重复
- `expected_sources` / `relevant_units` 中无 `chunk_id` / `unit_id`；字段经 `validate_case` 全量通过

## C. 校验拒绝（独立探针，非调用测试）

对 `load_cases` 直接构造临时 JSONL：

| 输入 | 结果 |
| --- | --- |
| regression 行删去 `source_err_id` | REJECTED：regression 套件必须提供 source_err_id |
| regression 行含 `unexpected` 字段 | REJECTED：case 含未知字段 |
| `expected_sources[].chunk_id="abc"` | REJECTED：含不允许字段 chunk_id |
| `expected_sources[].unit_key=<uuid>` | REJECTED：不允许写入 chunk_id/unit_id 等不透明 id |
| 两行相同 `case_id` | REJECTED：case_id 重复 |
| b0 原始行 | ACCEPTED |

对应实现：`dataset.py:77`（`OPTIONAL_CASE_FIELDS`）、`dataset.py:255`（仅非 None 时追加）、
`dataset.py:362-365`（regression 强制 `source_err_id`）、`dataset.py:397-399`（重复 case_id）。

## D. 受保护文件未被本 commit 改动

```text
git diff --stat 40901b5..36fe095 -- fixtures/evaluation/b0.jsonl fixtures/evaluation/badcase.jsonl docs/evaluation/gate_v0_1.json
（无输出，exit 0）
git status --porcelain -- fixtures/evaluation docs/evaluation
（无输出）
```

`docs/evaluation/gate_v0_1.json` 的 `hard_gate_min_sample` 仍为 `{"b0":32,"badcase":13}`，`status=unapproved`。
