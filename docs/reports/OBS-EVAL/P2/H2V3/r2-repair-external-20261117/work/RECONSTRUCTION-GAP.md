# RECONSTRUCTION-GAP（r2 SAFE 投影器）——已闭合（T-R2-201D）

**状态：CLOSED（A 路径）。** 原始不一致（1/5）由 **source-map 输入口径**解释并闭合，判据未改。
闭合依据与字段清单见 `evidence/01-safe-projection/C25-RECON-GAP.md`；命令/退出码见
`evidence/01-safe-projection/NOTES-201D.md`。

本文件只含固定码与计数，不含题干/答案/来源正文/私有路径。

## 1. 原始记录（2026-11-17，T-R2-201A；保留不覆盖）

- mismatch_count: 1
- mismatch_cases: H2V3-C25

| case_id | case-plan | 改前重建 | 改后重建 |
|---|---|---|---|
| H2V3-C08 | pass | pass | pass |
| H2V3-C14 | pass | pass | pass |
| H2V3-C19 | pass | pass | pass |
| H2V3-C25 | pass | **fail** | **pass** |
| H2V3-C29 | fail | fail | fail |

改前 C25 失败面：`source_forbidden=fail`、`source_forbidden_hit=1`、`source_hit=pass`。
改后：`source_forbidden=pass`、`source_forbidden_hit=0`。

## 2. 闭合口径（固定码）

- 原因码：`source_map_driver_default_v01_missing_version_binding`
  （forbidden ref 的文档代号只在 `v0.2` 有版本绑定；`v0.1` 仅 4 码）。
- 生效条件（拒绝式门，缺一即失败）：`served_by_dispatch>=1`、`schema=p2-holdout-source-map/v0.2`、
  `code_count=12`、`driver_default_code_count=4`。
- 观测计数：`resolutions=2`、`code_count=12`、`driver_default_code_count=4`、
  `matches_run_declaration=true`。
- 反向自证：`version_number` 从 citation 移除后 C25 `source_hit` 立即 fail；
  `remap_closure` 对 5 题逐值不变。

## 3. 结构计数（改后，全为整数）

- case_count: 5
- envelope_count: 6
- turn_count: 6
- checks_total: 60
- checks_passed_total: 27
- checks_failed_total: 2
- checks_skipped_total: 31
- source_forbidden_hit（C25）: 0
- unsafe_code_count: 0

## 4. 缺口判读（改后仍通用）

- `sources_missing_unit` / `sources_missing_document_name` / `sources_unmapped_document` > 0：
  product.sources 无法从 db_projection 还原到单位级身份，评分侧来源身份不可信。
- `product_kind_missing` / `product_text_missing` > 0：answer_result/commit_observed
  事件缺 kind/text，评分行不完整。
- `kind_answer_commit_mismatch` / `text_answer_commit_mismatch` > 0：两处事件不一致，
  无法在不猜的前提下选定 product 字段。
- `envelope_read_failed` / `envelope_incomplete` / `envelope_turn_index_mismatch`：密文或
  case-plan 对不上，需重新核对封存链。
- （201D 追加）`scoring_map_dispatch_unused` / `scoring_map_schema_mismatch` /
  `scoring_map_code_count_mismatch` / `scoring_map_driver_default_mismatch`：评分输入没有
  按运行声明的 source-map 生效——此时重建与 case-plan 不可比，必须先修输入而不是解释差异。
