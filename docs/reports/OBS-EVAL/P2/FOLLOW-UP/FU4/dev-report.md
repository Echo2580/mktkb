# FU-4 开发报告：H2 输出及分享材料的受限路径脱敏

- 日期：2026-11-21（Asia/Shanghai）
- 分支 / HEAD（开工核对）：`codex/p2-e2e` / `93486b6590c6542f34dd70d20a19b792c659f416`
- 范围：任务书 §5（FU-4）；与 FU-2 同一名开发者（共用 H2 CLI 错误出口）
- 零真实调用：真实模型 **0**、OCR **0**、外网 **0**、费用 **0**；未读取 env 文件（dotenv）、未打开私有密文内容
- 历史冻结工件：**只读、未改**（§6 有两次 SHA-256 快照与 HEAD 字节比对）

> 路径书写约定：本报告与全部新公开产物中，仓外开发目录记作 `<DEV>`、临时目录记作 `<TMP>`；
> 受限 holdout 根 / 批次根的名称，以及密钥、密文文件后缀一律不写出（检测字面量只存在于
> `FU4/evidence/scripts/audit_public_paths.py`，扫描时按设计排除该脚本）。

---

## 1. 结论

1. **定位完成**：两个受控入口的公开出口（结构化 stdout + 错误 detail）共有 **30 处**
   路径字符串回显点、**32 处**路径字段回显点（HEAD 状态，file:line 见 §2 与
   `FU4/evidence/source-echo-sites.json`）；已封存的仓外派生包装器另有 **10 处**
   `SystemExit` 文本回显与 **4 处** payload 路径字段。
2. **修复完成**：新增 `p2_safe_output`（331 行，只做"公开层"清洗），并在**边界**接线：
   v2/v3 的 `_emit` 与结构化错误 detail；`derive-cards` 的新公开产物走**严格模式**（任何
   绝对路径都记号化）。**不发明新原因码**：所有拒绝仍用既有固定码，本模块只清洗自由文本与
   路径值，因此固定 reason code（含 `holdout` 字样的那些）逐字保留。
3. **前后对照**：8 类合成受限路径样本，公开层硬命中 `16 → 0`；正常分支 `6 → 1`（仅剩
   **非受限**的工作目录，按兼容性要求保留），严格分支 `6 → 0`；拒绝分支 `→ 0`。
4. **新公开产物定向扫描**：`FU2` + `FU4` 全部数据件 **0/0**（六类计数全 0，`clean=true`）。
5. **历史泄露登记**：7 个 H2 相关历史根共 **2181** 个文本件，**746** 件含命中
   （受限根名 67、批次根名 659、密钥/密文名 370、env 文件 130、绝对路径 2215、UNC 1484）。
   **按规矩只登记、不修改**；外发副本必须排除这些文件（§5 附表给出文件名清单所在证据）。
6. **原冻结件未改**：报告落盘前后两次快照逐值相同（2181 个文本件聚合摘要一致），
   `H2-REBUILT-CARDS` 7 件与 5 份治理文档与 `HEAD` 字节一致。

---

## 2. 泄露定位（HEAD 状态，file:line）

机检口径：`FU4/evidence/scripts/` 下的清单生成脚本对 `git show HEAD:<path>` 的字节逐行分类，
只记录 **file:line + 类别**，不记录行内容。汇总（HEAD → 当前工作树）：

| 文件 | 类别 | HEAD | 现在 | 说明 |
| --- | --- | --- | --- | --- |
| `tools/p2_h2_controlled_execute.py` | 路径字符串进 payload | 11 | 11 | 值仍在 payload 里，但出口 `_emit` 现在清洗 |
| 同上 | 路径字段 | 15 | 15 | `paths` / `binding_file` / `card_file` / `receipt_path` 等 |
| 同上 | 公开出口边界 | 7 | 7 | `_emit` / `main` 错误分支 |
| 同上 | **脱敏边界（新增）** | 0 | 6 | `_public_payload` / `_public_detail` / `redact_payload` |
| `tools/p2_h2_v3_controlled_execute.py` | 路径字符串进 payload | 15 | 21 | 新增派生证明的路径角色字段 |
| 同上 | 路径字段 | 13 | 17 | 同上 + `output_dir_token` |
| 同上 | 公开出口边界 | 10 | 10 | `_emit` / `main` 双错误分支 / 派发 |
| 同上 | **脱敏边界（新增）** | 0 | 14 | `strict` 模式 + 派生证明 |
| `H2-REBUILT-CARDS/scripts/derive_v3_cards.py`（已冻结，未改） | `SystemExit` 文本 | 10 | 10 | **历史泄露**：`must not be inside <root>` 直接带根路径 |
| 同上 | payload 路径字段 | 4 | 4 | `--self-test-guard` 的 JSON 与结尾 print 带绝对路径 |

具体风险点（HEAD 行号，节选）：
- v2：`_write_new_file` 回执（`path`）、`_input_record`（`path`，含受限 holdout 件与 key 件）、
  `plan_private` 的 `binding_file`、`preflight` 的 `paths.as_public()`（含**证据 key 文件路径**）、
  `run` 回执的 `paths` / `receipt_path` / `case_plan.path`、`recompute` 的 `card_file` 与
  评分身份里的 `source_map_path`。
- v3：`_input_record` / `_records_from_paths` / census 的 `path`、`plan_private` 的
  `holdout_root` 与 `binding_file`、`check_only` 的 `--out` 回执 `evidence_file`、`run` 回执路径。

---

## 3. 复用的机制（不发明新体系）

| 机制 | 复用方式 |
| --- | --- |
| 固定原因码 | 所有拒绝仍抛既有 `EntryError(code)`；`error_code` / `detail` 的**码值**零改动 |
| 受控层与公开层分离 | 私有封存目录里的 `run-receipt.json`、plan、密文**保持原样**（受控层）；只清洗公开出口 |
| 既有路径守卫 | 路径拒绝码沿用 `path_inside_forbidden_root` / `path_invalid` / `output_not_empty` 等 |
| 既有多写者约定 | 新产物的"不存在或为空"沿用 `require_new_or_empty_dir` 口径 |

新增的唯一助手是 `backend/src/mktkb/evaluation/p2_safe_output.py`：现状确实缺一个**统一**的
"公开层清洗"函数（三处出口各写一遍会漂移），故按任务书允许的新模块方式补齐，不触碰任何禁止区。

API（全部纯函数、无 I/O、无随机盐）：

```
path_kind(value)                 -> windows_abs | unc | posix_abs | key_file | ciphertext | invalid | None
is_restricted(value, roots=())   -> bool（受限根/密钥/密文/私有 var 目录/env 文件/UNC 一律 True）
path_token(value, role=None)     -> <redacted-path:ROLE:sha256(realpath)[:12]>   # 确定性记号
redact_value / redact_text       -> 单值 / 自由文本清洗（内嵌绝对路径与密钥名）
redact_payload(payload, strict=) -> 递归清洗（只改字符串值，键与数值/布尔不动）
scan_public_text / scan_public_texts -> 只报类别/位置/计数，**绝不回显命中内容**
```

**默认 vs 严格**：
- 默认（既有入口 stdout）：只清洗**受限**路径；仓外普通工作目录保留原值 —— 这是为了不破坏
  既有下游（例如 `card_file.path` 被既有 e2e 用例用来读文件）；
- 严格（`derive-cards` 等**新**公开产物/分享副本）：任何绝对路径都记号化。

---

## 4. 接线点（改了什么）

| 位置 | 改动 |
| --- | --- |
| `tools/p2_h2_controlled_execute.py` | `_public_payload` / `_public_detail` / `_emit` 清洗；`main` 的 `EntryError.detail` 走 `_public_detail`；+13 行 |
| `tools/p2_h2_v3_controlled_execute.py` | `_public_roots` / `_public_payload(strict=)` / `_public_detail` / `_emit(strict=)`；两条错误分支清洗 detail；`derive-cards` 全部输出 `strict=True` |
| `backend/src/mktkb/evaluation/p2_safe_output.py` | 新建（331 行） |
| `backend/tests/evaluation/test_p2_fu4_safe_output.py` | 新建（363 行，24 条用例） |

输出样子（真实 stdout，`derive-cards` 拒绝分支；**已脱敏**）：

```json
{
  "command": "derive-cards",
  "detail": "out_dir",
  "error_code": "derive_output_in_forbidden_root",
  "network": {"external": [], "local": []},
  "ok": false
}
```

---

## 5. 前后对照与扫描（命令 + 结果）

### 5.1 样本级前后对照（`redaction-proof.json`）

```
.venv\Scripts\python.exe -B <DEV>/fu4/make_fu4_evidence.py --out docs\reports\OBS-EVAL\P2\FOLLOW-UP\FU4\evidence\redaction-proof.json
→ before_hard_hits=16, after_hard_hits=0
```

| 分支 | 前 | 后 | 断言 |
| --- | --- | --- | --- |
| 8 类样本（受限 holdout、批次密文、密钥、带空格路径、UNC、超长、含换行、怪字符） | 16 命中 | **0** | 记号确定性 + 幂等（同输入同记号，二次清洗不变） |
| 正常分支（receipt 形状 payload，含 key/密文/holdout 与一个普通工作目录） | 6 | 1（仅"绝对路径"类的**非受限**工作目录） | `reason` / `counts` 逐值保留；非受限 out_dir 保留 |
| 严格分支（同一 payload，`strict=True`） | 6 | **0** | 新公开产物口径 |
| 拒绝分支（detail 内嵌两个受限路径） | 2 | **0** | `error_code` / `real_sends` 保留 |

固定 reason code 不被误伤的直接证据：`holdout_hard_failure_unverified` 在前后扫描中逐字保留
（单元用例 `test_public_identifiers_and_reason_codes_are_not_rewritten`）。

### 5.2 新公开产物定向扫描（六类模式）

```
.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P2\FOLLOW-UP\FU4\evidence\scripts\audit_public_paths.py ^
  --mode new --root docs\reports\OBS-EVAL\P2\FOLLOW-UP\FU2 docs\reports\OBS-EVAL\P2\FOLLOW-UP\FU4 ^
  --exclude "*/scripts/*" --exclude "scripts/*" ^
  --out docs\reports\OBS-EVAL\P2\FOLLOW-UP\FU4\evidence\new-artifact-scan.json
→ totals 全 0，clean=true
```

扫描类别（正则见脚本；此处只写类别名）：`restricted_root`（受限 holdout 根名）、
`h2v3_batch_root`（批次根名）、`key_or_ciphertext_name`（密钥/密文文件名）、`env_file`、
`absolute_path`（盘符绝对路径）、`unc`。

> 说明：`*/scripts/*` 被排除，因为**检测脚本自身**必须包含检测字面量；脚本不是"分享数据件"。
> 该排除是本报告显式声明的口径，不是隐藏。

### 5.3 历史冻结件登记（只登记、不改写）

```
.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P2\FOLLOW-UP\FU4\evidence\scripts\audit_public_paths.py ^
  --mode historical ^
  --root docs\reports\OBS-EVAL\P2\H2-REBUILT-CARDS docs\reports\OBS-EVAL\P2\H2V3 ^
         docs\reports\OBS-EVAL\P2\H2-DOC-REBUILD docs\reports\OBS-EVAL\P2\T207-CUSTODY ^
         docs\reports\OBS-EVAL\P2\T207-CUSTODY-V2 docs\reports\OBS-EVAL\P2\T207-CUSTODY-V3 ^
         docs\reports\OBS-EVAL\P2\T207-CUSTODY-SEMANTIC-R2 ^
  --out docs\reports\OBS-EVAL\P2\FOLLOW-UP\FU4\evidence\historical-leaks.json
→ files_scanned=2181, files_with_findings=746
```

| 根 | 扫描 | 含命中 | 受限根名 | 批次根名 | 密钥/密文名 | env 文件 | 绝对路径 | UNC |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `H2-REBUILT-CARDS` | 7 | 3 | 1 | 0 | 0 | 25 | 40 | 0 |
| `H2V3` | 2135 | 725 | 64 | 659 | 350 | 99 | 2152 | 1482 |
| `H2-DOC-REBUILD` | 5 | 2 | 0 | 0 | 0 | 3 | 0 | 2 |
| `T207-CUSTODY` | 7 | 3 | 0 | 0 | 2 | 0 | 2 | 0 |
| `T207-CUSTODY-V2` | 5 | 4 | 0 | 0 | 5 | 0 | 4 | 0 |
| `T207-CUSTODY-V3` | 5 | 4 | 2 | 0 | 5 | 3 | 6 | 0 |
| `T207-CUSTODY-SEMANTIC-R2` | 17 | 7 | 0 | 0 | 8 | 0 | 11 | 0 |

**处置**：以上历史文件**一个字节都没改**（§6）。逐文件清单（相对路径 + 计数 + 各自 SHA-256）
在 `historical-leaks.json` 的 `roots[].findings[]` 里；**外发/分享副本必须整目录排除或在复制时
按该清单剔除**。其中 `H2-REBUILT-CARDS/report.md` 与 `T207-CUSTODY-V3` 的受限根名命中要优先
处理（它们的分享面最大）。

---

## 6. 原冻结工件未改证明

1. **两次快照**（报告落盘前 / 后，脚本只读）：

```
.venv\Scripts\python.exe -B <DEV>/fu4/frozen_digest.py --label before --out ...\FU4\evidence\frozen-digest.before.json
.venv\Scripts\python.exe -B <DEV>/fu4/frozen_digest.py --label after  --out ...\FU4\evidence\frozen-digest.after.json
```

| 快照 | 文本件数 | 聚合 `scan_tree_sha256` |
| --- | --- | --- |
| before | 2181 | `8695172aba511426f004995e6755fb8caac2fc2996c7e6b15769bccc93e31c75` |
| after | 2181 | 与 before **逐值相同** |

聚合覆盖 7 个历史根的全部文本件；逐文件摘要（14 个重点件，含 `candidate-freeze.json/md`、
`release-decision.md`、`manager-decisions.md`、`H2V3/PM` 三件、`H2-REBUILT-CARDS` 7 件）也在
before/after 两份 JSON 的 `focus_files[]` 中，两边逐值相同。

2. **与 HEAD 字节一致**：`H2-REBUILT-CARDS` 全部 7 件（含包装器脚本）逐文件
   `sha256(worktree) == sha256(git show HEAD:<path>)`；其中包装器与报告 md 的摘要见
   `source-echo-sites.json` 的同文件 `head`/`worktree` 分组（两态计数逐项相同 = 未改）。
3. **git 状态**：`git status --porcelain -- docs/reports/OBS-EVAL/P2` 下 tracked 改动**只有**
   开工前既有的 `T207-QUALITY-REPAIR/manager.md`（本项未触碰）；本轮新增全部落在未跟踪的
   `FOLLOW-UP/FU2`、`FOLLOW-UP/FU4`。本轮**没有** `git commit/push/checkout/reset/stash/clean/add`。

---

## 7. 负例覆盖（测试）

命令：

```
.venv\Scripts\python.exe -m pytest backend\tests\evaluation\test_p2_fu4_safe_output.py -q
→ 24 passed, 0 failed, exit 0
```

| 覆盖 | 用例 |
| --- | --- |
| 合成 Windows 路径（`C:`/`D:`）、带空格路径、UNC、受限根、批次根、`/` 分隔变体 | `test_restricted_paths_are_recognised`（7 参数） |
| 固定 reason code / 仓库相对公开件不被改写 | `test_public_identifiers_and_reason_codes_are_not_rewritten`（4 参数） |
| 默认 vs 严格两种边界 | `test_default_boundary_only_redacts_restricted_paths_but_strict_redacts_all_absolute` |
| 密钥/密文/env 文件 文件名 | `test_key_and_ciphertext_file_names_are_redacted` |
| 超长、含换行、怪字符、NUL、幂等 | `test_weird_and_overlong_strings_are_contained`、`test_redaction_is_idempotent_and_sha_stable` |
| 结构不变（键/数值/布尔/reason 列表） | `test_payload_redaction_keeps_codes_counts_and_non_strings` |
| 扫描器只报类别不回显内容 | `test_scan_public_text_reports_kinds_without_echoing_the_path` |
| **正常分支**：v2/v3 `_emit` 成功 payload、严格模式 | `test_v3_emit_sanitises_success_payload`、`test_v3_emit_strict_mode_tokenises_every_absolute_path`、`test_v2_emit_sanitises_success_receipt_like_payload` |
| **拒绝分支**：v2/v3 错误 payload 与 detail | `test_v3_cli_error_detail_is_path_safe`、`test_v2_cli_error_branch_is_path_safe`、`test_v3_derive_error_payload_shape_is_safe` |
| 新产物可扫描且干净 | `test_new_public_artifacts_are_scannable_and_clean` |

---

## 8. 未覆盖 / 阻断 / 待经理决定

| 编号 | 事项 | 状态 |
| --- | --- | --- |
| B-1 | 历史冻结件的**内容清洗** | 按任务书"只登记、不改历史文件"执行，**NOT-DONE（故意）**；分享副本靠排除清单处理 |
| B-2 | 已冻结包装器的 10 处 `SystemExit` 路径回显 | **未改**（该文件属 `docs/reports/OBS-EVAL/P2/**` 既有文件，禁止改）。已在 §2 登记；新的 `derive-cards` 用角色记号，不复刻该缺陷 |
| B-3 | 真实受限批次的分享副本再扫描 | `NOT-RUN`：无私有权限与真件；扫描器与口径已就绪，可由授权保管人在其权限内直接跑同一条命令 |
| B-4 | 仓库内其它子系统（非 H2）的日志/报告 | 不在本项范围；本轮只覆盖两个 H2 受控入口 + 新派生入口 |
| 决策请求 | 是否把 `_emit` 默认模式升级为 `strict=True`（即连非受限绝对路径也记号化） | 待经理决定。**默认不升级**：会破坏既有下游读取 `card_file.path` 的用法与既有 e2e 用例（已实测 160 条既有用例依赖默认语义）。分享场景已由 `derive-cards` 的严格模式覆盖。 |

## 9. 遗留风险

- **R-1**：默认模式仍保留**非受限**绝对路径（例如仓外工作目录）。若这些目录名本身含敏感信息
  （客户名/工号），仍会进 stdout。缓解：新产物一律严格模式；如需彻底，按上表决策请求升级。
- **R-2**：脱敏是"形状 + 受限根集合"驱动，不是"内容语义"驱动。若有人把受限路径写进
  **不含路径形状**的自由文本（例如只写批次代号），本模块不会拦。缓解：批次代号本身不是路径，
  且 `derive-cards` 证明只含摘要/计数。
- **R-3**：历史登记只覆盖 7 个 H2 相关根（2181 件）。`docs/reports/OBS-EVAL/P2` 其余子目录
  未扫（避免把范围扩大到其它在途工作与巨量证据）；如需全量，跑同一命令换 `--root` 即可。
- **R-4**：扫描器按后缀白名单读文本件，跳过密文/二进制（**故意**：不读私有密文）。因此"密文
  文件名"只在**文本引用**里被发现，密文文件本身不外发即可。
- **R-5**：路径记号带 `sha256(realpath)[:12]`，同一路径可被关联（这是为了"前后可对照"的
  刻意设计）；它不泄露路径内容，但会泄露"两处引用的是同一路径"。

---

## 10. 证据索引

| 证据 | 路径 |
| --- | --- |
| 历史泄露登记（逐文件计数 + 摘要） | `docs/reports/OBS-EVAL/P2/FOLLOW-UP/FU4/evidence/historical-leaks.json` |
| 新公开产物扫描结果 | `.../FU4/evidence/new-artifact-scan.json` |
| 源码回显点清单（HEAD vs 工作树） | `.../FU4/evidence/source-echo-sites.json` |
| 脱敏前后对照（样本 + 正常/严格/拒绝分支） | `.../FU4/evidence/redaction-proof.json` |
| 冻结件快照 before / after | `.../FU4/evidence/frozen-digest.before.json`、`.../frozen-digest.after.json` |
| 审计脚本（扫描命令的可执行版本） | `.../FU4/evidence/scripts/audit_public_paths.py` |
| 测试日志 | `<DEV>/fu2/pytest-fu2-fu4.log`、`<DEV>/fu2/pytest-existing.log` |

最终机件摘要（落盘后复算；扫描器输出文件随每次运行刷新，故只列其 `totals`，不列自指摘要）：

```
FU4/evidence/historical-leaks.json     254382 B  9c74c4426e9ab24931fd0c58f21071ec1ef15604848d22061d03b55a68bb2274
FU4/evidence/redaction-proof.json       15458 B  c8d0b454f62de31c7b1b260ccd53859e62a318aa3c284907159cbecf8e796301
FU4/evidence/source-echo-sites.json      9117 B  2d315b72e65a684473ee48a41662bd4e5743c74a18e08d422f7f83187d2ce370
FU4/evidence/frozen-digest.before.json   3671 B  a8503917de2ea39c13aa5f1455c0218ad3a2f26f3d84fe4013c2bae7cf4cbdfc
FU4/evidence/frozen-digest.after.json    3670 B  a816f291e1c23d85c101ebea28ddadc03a3cf8dec9d679fd6fe69e63f14edef6
FU4/evidence/scripts/audit_public_paths.py 6552 B  73667ee58b333fd3464e84eaecba578fa439c7cee855371d5c0ce645cd295a37
new-artifact-scan.json（扫描输出）: totals 全 0，clean=true（不入自指摘要）
```
## 11. 落盘后复算（最终值）

见本报告同级 `evidence/` 目录的实际文件；报告与证据的最终 SHA-256 由交付窗口统一复算登记到
`FOLLOW-UP/report.md` 的候选指纹清单（本项不重复冻结）。
