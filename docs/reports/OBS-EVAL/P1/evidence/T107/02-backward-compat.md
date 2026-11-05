# T107 证据 02：契约扩展向后兼容（b0/badcase 字节不变）

## 变更口径

- `CASE_FIELDS` 仍是 21 个必填字段，**未增删**；新增 `OPTIONAL_CASE_FIELDS=("source_err_id",)`。
- `CaseSpec.to_dict()` 仅在 `source_err_id is not None` 时把它追加到 JSONL 末尾；b0/badcase 的
  `source_err_id` 均为 `None`，因此规范 JSONL 不出现该键，`dataset_version` 的 sha 口径不变。
- `validate_case` 只对 `suite=="regression"` 强制 `source_err_id`；b0/badcase 不要求、也不改写。

## 逐字节对照（改动前 → 改动后）

| 数据集 | 改动前 sha256 / dataset_version | 改动后 sha256 / dataset_version | 规范字节 round-trip |
| --- | --- | --- | --- |
| `b0.jsonl` | `bd4f0f7ccc6e9f50ba630598c01b3519804447d4e0f3bfbc2facd54a5a521e4f` / `b0:b0-2026-11-04:bd4f0f7ccc6e` | 同左 | `cases_to_jsonl(load_cases(...)) == 文件字节`：True |
| `badcase.jsonl` | `e5f0662af3f2bf51ac9354cf467ab55be9bd3b97444ae2ba7d359d3d907b371a` / `badcase:badcase-2026-11-04:e5f0662af3f2` | 同左 | 同上：True |

改动前数字来自执行前脚本（同一 `load_cases` / `dataset_version`），改动后由同一脚本复算；
`git diff --exit-code -- fixtures/evaluation/b0.jsonl fixtures/evaluation/badcase.jsonl` 退出码 `0`（无 diff），
`git status --short` 不含这两个文件。

## 测试锁定

- `backend/tests/evaluation/test_regression_suite.py::test_legacy_fixtures_keep_canonical_bytes_and_dataset_version`
  对 b0/badcase 同时断言：完整 sha256、`dataset_version` 字面值、`b"source_err_id" not in raw`、
  `cases_to_jsonl(...) == raw`、`to_dict()` 键集合恰为 `CASE_FIELDS`。
- `...::test_optional_field_only_appears_when_set` 断言：regression 行带 `source_err_id`；
  置空后 `to_dict()` 不再包含该键。
- 既有 `test_dataset.py` 的 b0/badcase 计数、strata、版本与 round-trip 断言未修改、未放宽。

## regression 新数据集（新建，非改动）

- `fixtures/evaluation/regression.jsonl`：7 行，UTF-8，`ensure_ascii=False`，`\n` 行尾。
- sha256 = `760fb06576ce991f0f9af6b13a75ed6ec0794dbb61262fdb275cfa082ae06562`
- `dataset_version = regression:regression-p1-2026-11-05:760fb06576ce`
