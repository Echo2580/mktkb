# T-R2-201D NOTES（C25 重建保真缺口：闭合）

日期：2026-11-17。范围：`r2`（run_index=2）封存证据的**零调用**重建；只跑质量面。
run：`p2-h2v3-20261115-r2-pre_v05_without_v07`；scenario `pre_v05_without_v07`；case 5 / turn 6。

> 只含固定码、布尔、计数、sha256、公开文档代号；不含题干、答案、实体值、业务数字原文、私有路径。

## 0. 结论

**A 闭合**：差异在 ref 侧版本绑定（source-map 输入口径），不在 citation 重建。取运行声明的
`p2-holdout-source-map/v0.2`（12 码）后 `reconstruction_match=5/5`、`ok=true`；判据/阈值/评分器/
case-plan 未改。详见 `C25-RECON-GAP.md`。

## 1. 产出与哈希

| 文件 | sha256 | 说明 |
|---|---|---|
| `work/r2_safe_project.py` | `1374247976bad531901d92a068e55db7e7e249e44cf53b002fedde6ca81cd6af` | 新版（改动清单 L） |
| `evidence/01-safe-projection/r2-quality-checks.json` | `2c322e16ef5b7fcc9444512c6b4f0138ad5a38b9026f0b8265ee649553ccad17` | `ok=true`、5/5 |
| `evidence/01-safe-projection/C25-RECON-GAP.md` | — | 缺口闭合说明 |
| `evidence/01-safe-projection/r2-adaptation-selftest.json` | `c8256c00fb4a039a5a4bdc51e9facddeeae7907e4a125f4d21263bdef5bfd6b0` | 重跑后**逐字节未变**（6/6 拒绝） |
| `evidence/01-safe-projection/r2-scoring-version-compare.json` | `3abbb59cfb7c2b4d5bf07b1cf9d92e3b54114e3b156e499c211a30a7a2fa4006` | 重跑后**逐字节未变**（`flip_count=0`） |
| `work/RECONSTRUCTION-GAP.md` | — | 改为"已闭合"记录（保留原始不一致表） |
| `docs/evaluation/p2-holdout-v3.source-map.json`（输入） | `03665c48c0716e45e0a6313c6f1823e6714c996d85254f01283fc0ef5ed2e8b8` | 运行声明口径 |
| `docs/evaluation/p2-holdout-v2.source-map.json`（驱动层默认） | `86c86767ce5f4251ff52589cca9d02882aa7f47e23caf7cde654133b8ea821b5` | 4 码（会丢 `D01`） |
| `fullverify-20261116/run/r2-final/v3-entry-sidecar.json` | `dfe81e780aea5b592cb65964037d97bd1cce80e1b09679bd97e5b4ad2950a3e3` | `scoring_map` 声明 |

其他关键不变项（与开工保护快照逐字相同）：`p2_scoring.py c3265f4f…`、`scorers.py 3f8ee170…`、
`p2_score_run.py 366e621b…`、`p2_hard_evidence.py 9861c44e…`、`p2_evidence_io.py 1c16a3da…`；
`case-plan.json fe874186…`（未改）。

## 2. 命令与退出码（均在**仓库根**执行）

```
.venv\Scripts\python.exe -X utf8 work\r2_safe_project.py --key <ev.key> --binding <run2.binding.json> ^
  --evidence-root <r2 evidence dir> --receipt <seal\run-receipt.json> --seal-manifest <seal\seal-manifest.json>
  exit 0        （改前：exit 1 + ok=false/reconstruction_mismatch）
.venv\Scripts\python.exe -X utf8 work\r2_selftest.py --key <..> --binding <..> --r1-binding <run1.binding.json> ^
  --evidence-root <..> --receipt <..> --seal-manifest <..>
  exit 0        （selftest_count=6, all_refused=true, positive_controls 6/6）
.venv\Scripts\python.exe -X utf8 work\r2_scoring_version_compare.py --key <..> --binding <..> ^
  --evidence-root <..> --receipt <..> --seal-manifest <..>
  exit 0        （flip_count=0）
```

- 私钥/密文/binding 只在进程内读；命令行参数由环境变量或显式路径传入，不写进任何产物。
- `--case-plan` / `--out-dir` / `--gap-path` 用默认值（相对 REPO 常量）。

## 3. 出站守卫（三进程一致）

`outbound_allowed=0`、`blocked_attempts=2`、`blocked_subprocess_attempts=1`、
`positive_control_attempts=3` 且 `positive_control_blocked=true`、`subprocess_guard_installed=true`。
零真实/离线产品请求；无 HTTP；未跑 pytest。

## 4. 改动登记（只动输入与报告；判据零改动）

- **L. source-map 口径**：`_score_cases` 在 `p2_holdout_v3_scoring.dispatched_scoring_map(V3_SOURCE_MAP)`
  作用域内取 map（与 `tools/p2_h2_v3_controlled_execute.py:2323` 同一条路），并加拒绝式门
  （`scoring_map_dispatch_unused` / `_schema_mismatch` / `_code_count_mismatch` /
  `_driver_default_mismatch`）；输出新增 `scoring_map`（7 个定长字段）。
- 新版文件头 docstring 的改动清单 A–K 逐条保留，新增 L 条说明。
- 未改：`source_forbidden`/`source_hit` 判据、`_version_source_checks`、`match_source_ref`、
  阈值、`case-plan.json`、任何 `backend/` 文件；报表侧除新增 `scoring_map` 与其键白名单外无改动。
- 自证：`version_number` 从 citation 移除后 C25 `source_hit` 立即 fail（locator-only 两头不成立），
  说明版本绑定是收紧；`assert_remap_closure=true`（v0.2 折过再被 v0.1 折，5 题逐值不变）。

## 5. 数字结论（改后）

- `reconstruction_match=true`、`scoring_paths_agree=true`、`scoring_version_explained=false`
- `checks_total=60` = 27 pass / 2 fail / 31 skipped；`checks_failed_total=2`（C29 `value_hit`,`source_hit`）
- 逐题：C08 pass / C14 pass / C19 pass / **C25 pass** / C29 fail
- C25：`source_forbidden=pass`、`source_forbidden_hit=0`、`source_hit=pass`
- `custody_ok=true`、`sealed=true`、`evidence_file_count=7`、`real_calls=29`（= case-plan）
- `scoring_map`：`schema=p2-holdout-source-map/v0.2`、`code_count=12`、`driver_default_code_count=4`、
  `served_by_dispatch=2`、`matches_run_declaration=true`

## 6. 已知口径分歧（不是新缺口）

`r2-scoring-version-compare.json` 的性质是"102a 结构 token 前后口径对照"，它按**驱动层默认 v0.1**
计分，因此其 C25 行仍是 `source_forbidden=fail`。该件 sha 与 201A 记录逐字节相同（未被改动），
**不代表**本包 citation 重建口径；C25 的重建结论以 `r2-quality-checks.json` 为准。改它的工具不在
本包授权内（只许改 `work/r2_safe_project.py`），故只在此登记。

## 7. NOT-RUN

1. 四轴（safety / cross_user / cross_entity / stale_source）重建：属 201B/201C，本包未跑。
2. pytest、真实/离线产品请求、HTTP 贯通：**NOT-RUN**（本阶段零调用；任务书明确不跑 pytest）。
3. 首次偏离（first-divergence）、数字来源归因、C29 身份键细节：NOT-RUN（需 201B/201C 面）。
4. 封存 envelope 的 `runtime_snapshot` 路径：本批 6 件为 `v0.2-live`，该字段**不存在**
   （v0.3 才有），故未使用；`product_response.sources[]` 这条"产品自报 locator"证据在本批不可用，
   本包因此用 `db_projection.units[].locator/version_number` + 运行声明的 v0.2 映射完成同构。

## 8. 冻结与回滚锚点（2026-11-17，响应并发保护指令）

- **冻结件**：`work/r2_safe_project.201d-final.py`，`103711 B`，sha256
  `1374247976bad531901d92a068e55db7e7e249e44cf53b002fedde6ca81cd6af`，
  与 `work/r2_safe_project.py` **逐字节相同**（无 BOM、CRLF）。
- **共享文件最后一次写入**：`2026-11-17T16:55:35+08:00`（= 冻结件字节）。**此后不再写**
  `work/r2_safe_project.py`；`r2-quality-checks.json` 即由该字节产出（可复现：重跑 sha 不变）。
- **201A 基线可字节复原**：`work/r2_safe_project.201a-baseline@492e4ef7.py`，`98644 B`，
  sha256 `492e4ef7b87dca517d9305e9f4d0ad0150a69341a1efd983152467496b34f409`（= 201A 基线）。
  复原法：对冻结件**反向应用改动清单 L 的 7 处编辑**（保持 CRLF、无 BOM）。核验：`py_compile` 通过；
  纯复算行为与 201A 一致 —— `exit 1`、`ok=false`、`error=reconstruction_mismatch`、
  26 pass / 3 fail / 31 skipped、C25=fail、其余 4 题逐项相同（零出站，`outbound_allowed=0`）。
- 说明：`work/_pin/` 中 201C 的快照 `r2_safe_project@9a38c4f8.py`（103717 B）是**本包的中间版**，
  不是 201A 基线；基线原件在仓库内无第二份副本（该目录未被 git 跟踪），上述复原件是唯一可核对的字节来源。

**相对 201A 基线（`492e4ef7…`）的逐项改动（仅输入口径 + 报表；判据零改动）**

| # | 位置 | 改动 | 触及判据 |
|---|---|---|---|
| 1 | 模块 docstring | 新增改动清单 L 说明（12 行） | 否 |
| 2 | 常量区 | +4 常量（`SCORING_MAP_PATH` / v0.2 schema / 12 码 / 驱动默认 4 码）+3 行注释 | 否 |
| 3 | 正则区 | +`SOURCE_MAP_SCHEMA_RE` | 否（仅出口字符串白名单） |
| 4 | `_safe_string` | +1 分支放行 `p2-holdout-source-map/v0.<n>` | 否（出口校验） |
| 5 | `ALLOWED_KEYS` | +8 键（`scoring_map` / `schema_version` / `code_count` / `driver_default_code_count` / `served_by_dispatch` / `resolutions` / `source_map_sha256` / `matches_run_declaration`） | 否（出口白名单） |
| 6 | `_score_cases` | +`wiring` 形参、返回 4 元组；函数体置于 `dispatched_scoring_map` 作用域；+6 处固定码拒绝；+`scoring_map` 记录。**除缩进外语句集合与 `score_public_case` 调用参数逐字未变** | **否** |
| 7 | `main` | +`import mktkb.evaluation.p2_holdout_v3_scoring as wiring`；调用传 `wiring`、解 4 元组、`except ToolError: raise`；输出文档 +`scoring_map` | 否 |

冻结件与复原件均**不含**任何题面/答案/实体值/业务数字/私有路径；出口仍只允许固定码、计数、布尔、sha256。
## 9. 口径一致性修正（2026-11-17，lead 指令：只做这一件）

### 9.1 旧文件为何不代表本包口径

`r2-scoring-version-compare.json` 是"102a 结构 token 前后口径"对照。它原先直接调
`score_run.load_holdout_source_map()` → 驱动层默认 **`p2-holdout-source-map/v0.1`（4 码）**，
而本轮 r2 运行由受控入口在 `dispatched_scoring_map` 作用域内以 **`v0.2`（12 码）**计分
（`run/r2-final/v3-entry-sidecar.json` → `scoring_map`）。差一个码（`D01`）就足以让 C25 的
forbidden ref 丢掉版本绑定，退化成 locator-only 命中——那正是 201D 闭合掉的假违规。
旧件因此**与 `r2-quality-checks.json` 不同口径**，不可并列引用。

### 9.2 处理（只改对照脚本与输出；判据/阈值/case-plan 未改）

`work/r2_scoring_version_compare.py` 改为在 `p2_holdout_v3_scoring.dispatched_scoring_map(proj.SCORING_MAP_PATH)`
作用域内取 map（本脚本只有这一个 map 消费者：ref remap；remap 用的是分发后的映射本体），并加 6 处固定码拒绝
（`scoring_map_dispatch_failed` / `_summary_failed` / `_unused` / `_schema_mismatch` / `_code_count_mismatch` /
`_driver_default_mismatch`），输出新增 `scoring_map`（与 quality-checks **同构 7 字段**）。
import 的判据模块身份与 201A 记录逐字相同（`c3265f4f`/`3f8ee170`/`9861c44e`/`366e621b`/`1c16a3da`）。

| 文件 | 改前 sha256 | 改后 sha256 |
|---|---|---|
| `evidence/01-safe-projection/r2-scoring-version-compare.json` | `3abbb59cfb7c2b4d5bf07b1cf9d92e3b54114e3b156e499c211a30a7a2fa4006` | `ca01727fdd4cb18504c9280c3eed3a3567a79c165faa500d58cb89b0fbd1f377` |
| `work/r2_scoring_version_compare.py` | `1b593ae365998fa3d810bacc2af10736d4bfa085f89c71612c3e3e94cd9dd195`（= 201A 原件，已定名存 `r2_scoring_version_compare.201a@1b593ae3.py`） | `77e40450fd16a4d9b8ee239ca033ad913412ddebcf1996c05ac3cafa57a198e7` |

新增 `scoring_map`：`schema_version=p2-holdout-source-map/v0.2`、`code_count=12`、
`driver_default_code_count=4`、`served_by_dispatch=1`、`resolutions=1`、
`source_map_sha256=03665c48…`、`matches_run_declaration=true`。

### 9.3 C25 行：改前 / 改后（逐字段）

| 字段 | 改前（v0.1 口径） | 改后（v0.2 口径） |
|---|---|---|
| `current_status` | fail | **pass** |
| `original_status` | fail | **pass** |
| `current_failed_check_ids` | `["source_forbidden"]` | `[]` |
| `original_failed_check_ids` | `["source_forbidden"]` | `[]` |
| `current_check_statuses.source_forbidden` | fail | **pass** |
| `original_check_statuses.source_forbidden` | fail | **pass** |
| `source_forbidden_hit` | 1 | **0** |
| `flip` / `first_diff_check_id` / `changed_check_ids` | false / none / `[]` | false / none / `[]` |

全文件级差：**8 条路径**——上述 7 条都在 `cases[3]`（C25）行内，另 1 条是新增 `scoring_map`；
其余 4 题逐字段未变。

### 9.4 核心结论：不变

- `flip_count = 0`（改前 0 → 改后 0），`flip_cases = []`；5 题 `first_diff_check_id` 全为 `none`，
  `changed_check_ids` 全为 `[]`（60 个检查项里 0 项因口径切换而改变）。
- **"102a 结构 token 只作用于 `value_no_fabricated`"的计数证据**：每题 `structural_key_count=8`（5 题共 40 个
  结构 token），但 `changed_check_ids` 全空 ⇒ 未翻转任何检查；`value_no_fabricated` 在两种口径下均
  **5/5 pass**。代码侧同源：两个加数器只进 `_value_checks` 的 `allowed_number_keys`/`structural_number_keys`
  （`scorers.py:678-679`），仅在 `value_no_fabricated` 分支被消费（`scorers.py:718-735`），
  装配点在 `p2_scoring.py:1003-1013`；`value_hit`/`source_*`/`kind_*`/`refusal_*` 不读这两个集合。
- 逐题改后状态：C08 pass / C14 pass / C19 pass / **C25 pass** / C29 fail（`value_hit`,`source_hit`）——
  与 `r2-quality-checks.json`（`2c322e16…`）**逐题一致**。

### 9.5 对 `R2-BASELINE.md §4` 的影响：无

§4 的三项结论逐项仍然成立且数字不变：`import_root_is_worktree=true`、判据模块 sha 逐字相同、
`flip=false / earliest=none`、`structural_key_count=8`×5、`value_no_fabricated` 5/5 pass。
§10 证据表引用该件时**未带 sha**，因此无需同步旧 sha。**本包未改动 `R2-BASELINE.md`**。
（唯一变化：产出这些结论的机器件 sha 由 `3abbb59c…` 变为 `ca01727f…`，C25 行随之与 quality-checks 同口径。）

### 9.6 守卫

`outbound_allowed=0`、`blocked_attempts=2`、`blocked_subprocess_attempts=1`、
`positive_control_attempts=3` 且 `positive_control_blocked=true`；零真实/离线产品请求，未跑 pytest。
`work/r2_safe_project.py` 字节未动（仍 `13742479…`，最后一次写入 `2026-11-17T16:55:35+08:00`）。