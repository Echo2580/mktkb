# P2 剩余四项工程债 · 交付报告（开发自测）

日期：2026-11-21（Asia/Shanghai）｜分支 `codex/p2-e2e`｜基线 HEAD `93486b6590c6542f34dd70d20a19b792c659f416`
性质：**开发自测**。独立验收见同目录 `review.md`（由独立上下文复核）。零真实模型 / OCR / 外网 / 费用。

## 1. 结论

| 项 | 状态 | 一句话 |
|---|---|---|
| FU-1 通用入口绑定实际 RAG 索引版本 | **完成（开发自测）** | 复现 产品 3 / RAG 4 → 绑定 4；错绑仍失败；缺证与漂移 fail-closed；B0 口径不变 |
| FU-3 N/C/U 正式入口默认回源 | **完成（开发自测）** | 新增逐题回源并接进 `evaluate_release_gate`；13 类负例全部阻断；真实 v3 清单回源 0 问题 |
| FU-2 v3 单 run 派生进正式工具 | **完成（开发自测）** | `derive-cards` 子命令 + 五道校验 + 确定性写盘 + 路径拒绝；v2 命令集与拒绝码不变 |
| FU-4 H2 输出/分享路径脱敏 | **完成（开发自测）** | 公开出口 30 处回显点清洗；8 类合成样本硬命中 16→0；冻结件未改 |
| 集成回归 | 428 passed / **12 failed** | 12 条全部是 `candidate.pipeline` 版本门（候选摘要已变，需重新冻结），非代码缺陷 |
| 干净检出核验 | 通过 | 冻结候选 47/47 工件、2 项台账前缀、批准配置、真实门禁结果、B0 准入均逐字节一致 |
| 主人亲验 | 已就绪 | 原核收候选隔离实例：UI `127.0.0.1:5173`、API `127.0.0.1:8177`，见 [owner-acceptance.md](owner-acceptance.md) |

**未做（按授权边界）**：独立验收结论（见 `review.md`）、修复候选重新冻结/新 B0 准入、真实模型与 OCR 复验、
远端推送/合并/部署。原核收候选仍为今日亲验版本。

## 2. 现场与版本

| 项 | 值 |
|---|---|
| 开工核对 | 分支 `codex/p2-e2e`，HEAD `93486b6`（= 原核收版本）；工作树仅 2 个簿记文件有历史改动 + 大量未跟踪历史证据，未清理、未提交 |
| 干净检出 | `D:\mktkb-clean-93486b6`（`git worktree add --detach 93486b6`，非破坏性；未动当前工作树） |
| 修复树 | 当前工作树（未提交）：7 个已跟踪文件改动 + 6 个新文件，见 §6 |
| Python | `.venv\Scripts\python.exe`（3.12.7，pytest 9.1.1） |
| 私有材料 | 未打开 H2 密文、未读 `.env` 值、未触碰 `var/**` |

## 3. 逐项结果

### FU-1 通用 P2 路径绑定实际 RAG 索引版本

- **复现**（冻结候选）：发布换版夹具下 产品 3 / RAG 4；manifest 绑 3；RAG trace 4 → `trace_integrity=fail`、`version_binding`（[`FU1/evidence/repro-before-fix.log`](FU1/evidence/repro-before-fix.log)）。
- **修复**：`product_adapter.binding_index_revision()` = `QaIndexStatus.index_revision`（trace 同源）；不可得 → `None`（缺证）。
  runner 新增 `index_changed` 漂移停止码（通用路径每轮前后守卫；B0 仍用 `b0_index_changed`）。
- **正反例**：`backend/tests/evaluation/test_p2_fu1_index_binding.py` → **5 passed / exit 0**；
  真实模式隔离传输 `test_p2_live_wiring.py::test_live_mode_binds_actual_rag_index_revision` PASS（`outbound_network=0`）。
  覆盖：同值通过、产品计数错绑失败、任意错值失败、索引版本不可得（绑定不完整 + trace 不绑半套 + 门禁拒绝）、
  窗口内漂移 `aborted/index_changed`、同输入 config_hash 确定性。
- **B0 兼容**：`test_p2_b0.py` 全绿；B0 绑定值 4、漂移用例逐值不变；B0 注册工件字节未变。
- **命令**：`.\.venv\Scripts\python.exe -m pytest backend\tests\evaluation\test_p2_fu1_index_binding.py -q`（仓库根）。
- **证据**：[`FU1/dev-report.md`](FU1/dev-report.md)、`FU1/evidence/{repro-before-fix,after-fix}.log`。

### FU-3 N/C/U 正式入口默认回源校验

- **覆盖矩阵**：复用既有 `verify_manifest.py` 判定语义与正式门禁已有的 run 身份/四档/tally/SHA256SUMS；
  新增逐题回源（题目摘要三处内容比对、证据路径按批准根解析 + 摘要、trace 归属与身份、同 run 同题面 trace 互换、
  跨 run、重复 trace、U 的 R/L 类型混用、L 档受控测试映射与结果完整性、缺权威来源阻断）。
- **接入**：`evaluate_release_gate()` 加载到 `evidence_manifest` 时**默认**执行，异常折成阻断行（fail closed）。
- **正例**（真实任务 3 清单，只读）：`evidence_provenance = pass`，24 题 / 156 文件 / 15 trace / 0 问题；
  全门禁 `pass 38 / blocked 1 / observed 10`，唯一 blocked 为 `candidate.pipeline`（版本门）。
- **负例**：`backend/tests/evaluation/test_p2_fu3_provenance.py` → **21 passed / exit 0**，含"真实清单篡改一个
  合法十六进制题目摘要 → 正式入口默认阻断"与"与 `verify_manifest.py` 同判"两条。
- **保留**：6 条原机械失败（N1/C4/U1）、D-011 披露行、原证据与修正理由；原证据文件逐题声明 **156/156** 摘要命中
  （正式门禁另有 `SHA256SUMS` **17 行**整行重算——两者是不同口径：17 行是清单自身的哈希清单文件，156 是逐题
  `evidence_sha256` 声明的证据件数）。
- **命令**：`.\.venv\Scripts\python.exe -m pytest backend\tests\evaluation\test_p2_fu3_provenance.py -q`；
  `wire_real_ncu.py`（只读）见 `FU3/dev-report.md`。
- **证据**：[`FU3/dev-report.md`](FU3/dev-report.md)、`FU3/evidence/gate-{clean-93486b6,fixed-tree}.json`。

### FU-2 正式 H2 工具支持 v3 单 run 离线派生

- **复现**：改前 `derive-cards` 在两入口均不存在（exit 2 / `usage_invalid` exit 3）；旧入口拒绝 v3 单 run
  （`run_binding_invalid`、`real_sends=0`、0 出站）。
- **实现**：`tools/p2_h2_v3_controlled_execute.py` 新增 `derive-cards`（+870 行）：五道校验（历史计划与原执行身份、
  派生评分身份、场景/语料绑定、封存、回合完整性）+ 确定性写盘 + 严格脱敏；复用现有认证/分类/聚合/官方
  `validate_hard_evidence_scorecard` / `validate_hard_evidence_composition`。
- **自测**：`test_p2_fu2_derive_cards.py` **19 passed**（仓库根，exit 0）。正例：合成 v3 单 run 出卡 + 四场景合成
  （12/8/5/5、36 回合、total 30、status complete、release_ready false）。负例固定码：错误绑定、旧 schema、
  场景/子集变更、缺回合、重复回合、证据重复、封存缺失、场景重复。非法输出路径 10 例（仓库根/`..`/大写/尾斜杠/
  `.\`/`var`/原批次/冻结 holdout 根）全部 `derive_output_in_forbidden_root` 且不建目录；junction 指向仓库被真实拒绝。
- **兼容**：v2 命令集恰为 `plan-private/preflight/run/recompute` 不变；`code_changed_since_plan` 防护未动；
  评分配置（`min_pass=24 / hard_failures_max=0`）未动；既有受测定向 6 文件 160 passed。
- **确定性**：同输入两次运行卡/证明/摘要逐字节相同；换输出目录卡内容不变。
- **已知瑕疵（自测+独立复核发现，未改他人测试）**：`test_four_synthetic_derived_runs_compose_with_official_validators`
  对 **CWD 敏感** —— 从仓库根运行 19/19 通过；从 `backend` 目录运行该条失败，实测码 `scenario_ingest_invalid`
  （源于既有 `test_p2_holdout_scenarios.py` 封存夹具的仓库根约定：同条件下该文件从 `backend` 运行也会大面积失败）。
  仓库标准调用（README）为仓库根，故不影响结论，但属测试卫生债，登记待后续修（不改判据、不加 skip）。
- **证据**：[`FU2/dev-report.md`](FU2/dev-report.md)、`FU2/evidence/reproduction.json`、`FU2/evidence/derive-cards-evidence.json`。

### FU-4 H2 输出及分享材料路径脱敏

- **定位**：两个受控入口公开出口 30 处路径字符串回显点、32 处路径字段；封存包装器另有 10 处 `SystemExit` 文本。
- **实现**：新增 `backend/src/mktkb/evaluation/p2_safe_output.py`（331 行，只清洗公开层）；v2/v3 的 `_emit` 与
  结构化错误 detail 接线；`derive-cards` 新公开产物走严格模式。不发明新原因码（固定 reason code 含 `holdout` 字样逐字保留）。
- **前后对照**：8 类合成受限路径样本（受限根 / 批次根 / key·密文名 / 带空格 / UNC / 超长 / 换行 / 怪字符 / NUL）
  公开层硬命中 **16 → 0**；正常分支 6 → 1（仅保留非受限工作目录，兼容既有下游）；拒绝分支 0。
- **原冻结证据未改**：2181 个文本件两次 SHA-256 快照聚合完全相同；`H2-REBUILT-CARDS` 7 件与 HEAD 字节一致；
  历史泄露只登记（[`FU4/evidence/historical-leaks.json`](FU4/evidence/historical-leaks.json)），不改历史文件。
- **自测**：`test_p2_fu4_safe_output.py` **24 passed**（仓库根，exit 0）；新公开产物定向扫描六类计数全 0。
- **证据**：[`FU4/dev-report.md`](FU4/dev-report.md)、`FU4/evidence/redaction-proof.json`、`new-artifact-scan.json`、`source-echo-sites.json`。

## 4. 集成回归（受影响的定向集合）

```
cd D:\GPT项目\市场部AI知识库
.\.venv\Scripts\python.exe -m pytest backend\tests\evaluation\test_p2_fu{1,2,3,4}_*.py ^
  backend\tests\evaluation\test_p2_{runner,b0,gate,score_run,live_wiring,product_root_fix,evidence_capture}.py ^
  backend\tests\evaluation\test_p2_release_gate_{positive,negative,real_ncu}.py ^
  backend\tests\evaluation\test_p2_{eval_tool_repair_e2e,h2_docforbidden_identity,holdout_scenarios,h2_v3_controlled_entry,h2_controlled_entry}.py ^
  backend\tests\integration\test_p2_{public_controls,product_e2e}.py -q
→ 428 passed, 12 failed, exit 1（131.83s）
```

12 条失败全部落在 4 个 release-gate 文件，断言均为 `blocked != pass/pending`，首条阻断行恒为
`candidate.pipeline: release_version_mismatch {bound: 28aae43c…, candidate: 2aa9177b…}`：

| 基线（干净候选 `93486b6` + 已获准本地材料） | 修复树 |
|---|---|
| `test_p2_release_gate_positive.py` + `real_ncu.py`：**15 passed**；`negative.py`：**27 passed** | 7 + 4 + 1 失败，原因同上；其余 30 条通过 |

结论：除版本门外无回归。该门是"候选字节 ≠ B0 准入字节"的既有规则；本轮修复必然改变
`pipeline_source_sha256`（它显式含 `p2_runner.py` / `product_adapter.py`）。

另：`test_p2_capture_contract_v02.py::test_gap_rework_identity_unparsable_pagination_and_candidate_marker`
在**干净候选**上同样失败（预存在，与本轮无关），已单列。

## 5. 干净检出核验

`git worktree add --detach 93486b6`（`D:\mktkb-clean-93486b6`），只读复制已获准本地材料
（`var/eval/baselines/7981d4afc2d1`、`docs/reports/.../T209-PREP`、`T207-RETEST-20261119` 批次回执）后实测：

| 项 | 结果 |
|---|---|
| 冻结工件 `candidate-freeze.json` → `frozen_artifacts` | **47/47 摘要一致**（缺失 0、不符 0） |
| 台账前缀 `records_append_only`（manager-decisions / manager-acceptance） | **2/2 前缀摘要一致**（文件已追加，前缀未变） |
| 批准配置 `docs/evaluation/gate_v0_3_approved.json` | 摘要一致（`b1094cc7…`） |
| 真实门禁结果 `CROSS-SCENARIO-GATE/gate-result.real-ncu.json` | 存在且摘要一致（`d4c98f92…`），`decision=pass` |
| B0 准入 `var/eval/baselines/7981d4afc2d1/b0-admission.json` | 与工作树**字节相同**（`07d2b1e3…`）；freeze 记的 `2226fa20…` 是**规范化 payload 摘要**（同口径已复算一致） |
| 干净候选门禁对照 | `wire_real_ncu.py` → `decision=pass`、pass 38 / blocked 0 / observed 9 |

逐项可复现性标记（任务书 §6.1 要求）：

| 项 | 干净检出可复现 | 依赖已获准本地材料 | 未验证 |
|---|---|---|---|
| 47 个冻结工件摘要 | 是（纯 Git 内容） | 否 | — |
| 2 项台账前缀 | 是 | 否（文件本体在 Git，追加部分为历史记录） | — |
| 批准配置 / 真实门禁结果 | 是 | 否 | — |
| B0 准入 | 是（字节相同） | 是（`var/eval/baselines/7981d4afc2d1` 为仓外已登记材料） | 新 B0 执行 **NOT-RUN** |
| 门禁正/负例（15 + 27） | 是 | 是（`T209-PREP`、`T207-RETEST-20261119` 批次回执；外部历史 run `D:\mktkb-p2-run\t207`） | 真实模型/OCR 相关 **NOT-RUN** |

## 6. 修复候选指纹

完整清单见 [`candidate-fingerprint.json`](candidate-fingerprint.json)（含改前/改后 SHA-256 与字节数）。摘要：

| 文件 | 状态 | 改前 → 改后（SHA-256 前缀 / 字节） |
|---|---|---|
| `backend/src/mktkb/evaluation/product_adapter.py` | modified | `93d0e54f9b6e` → `d3bd4d8961bd` / 116375 → 117714 |
| `backend/src/mktkb/evaluation/p2_runner.py` | modified | `420e3b9db686` → `8c7fc54c3012` / 122464 → 125075 |
| `backend/src/mktkb/evaluation/p2_release_gate.py` | modified | `552d6ff7cfe4` → `7cf2cfe797a9` / 26904 → 28011 |
| `backend/src/mktkb/evaluation/p2_release_provenance.py` | **new** | — → `c309f8994490` / 25492 |
| `backend/src/mktkb/evaluation/p2_safe_output.py` | **new** | — → `1d3b29bd5104` / 11673 |
| `tools/p2_h2_v3_controlled_execute.py` | modified | `953fda08df6f` → `b5a20caf32f1` / 108460 → 145068 |
| `tools/p2_h2_controlled_execute.py` | modified | `2e442c6992ee` → `6cfcb724da36` / 150917 → 151498 |
| `backend/tests/evaluation/test_p2_fu1_index_binding.py` | new | — → `3eac899b113a` |
| `backend/tests/evaluation/test_p2_fu2_derive_cards.py` | new | — → `bc55fcf7ae5f` |
| `backend/tests/evaluation/test_p2_fu3_provenance.py` | new | — → `c1193d1827c0` |
| `backend/tests/evaluation/test_p2_fu4_safe_output.py` | new | — → `ab6007617654` |
| `backend/tests/evaluation/test_p2_runner.py` | modified | `23f1d004c470` → `cee84def437a`（仅 FU-1 断言口径） |
| `backend/tests/evaluation/test_p2_live_wiring.py` | modified | `c34a07537245` → `a3f4a44e90d4`（+64 行 live 绑定用例） |

未提交、未推送、未合并、未部署（工作树交付；`git status` 仅上述改动 + 本轮新增报告目录）。
**亲验版本 = 原核收候选**，修复候选需独立验收 + 重新冻结后另行交付。

可复核补丁：[`candidate.patch`](candidate.patch)（`git apply --check` exit 0；SHA-256 `13cb3e66f1e81034c23bab80e4bf604b98bd8710d3836ce5cbab9aca94d819ab`，257884 字节）。
补丁往返实测：在 `93486b6` 新检出上应用后，13 个文件里 **12 个逐字节一致**；`p2_release_gate.py` 内容一致
（`\r\n→\n` 归一后相同）但行尾风格不同 —— 该文件在 HEAD blob 与工作树**本来都是 CRLF**（各 600 / 619 处），
本仓库 `core.autocrlf=false`；补丁由通用换行文本生成，故落成 LF。**逐字节权威锁定以 `candidate-fingerprint.json` 为准**。

## 7. 分列口径（任务书 §7）

| 类别 | 结果 |
|---|---|
| 开发自测 | FU-1 5 + FU-1 live 1 + FU-2 19 + FU-3 21 + FU-4 24 = **70 条定向通过**；集成定向 428 passed |
| 独立离线核验 | 见 `review.md`（独立上下文复核；未跑真实调用） |
| 浏览器 | **NOT-RUN**（今日只提供 API 级验收实例；UI 外壳入口已就绪，未做浏览器自动化） |
| 历史真实（已冻结证据） | 只读核对：47/47 工件、2/2 前缀、真实门禁 `decision=pass`、B0 准入一致 |
| 新真实（本轮） | **NOT-RUN**：真实模型 0、OCR 0、外网 0、费用 0 |

## 8. NOT-RUN 清单

1. 修复候选的独立验收结论 → 见 `review.md`（不是"通过"的替代）。
2. 修复候选重新冻结 / 新 B0 准入 / 发布门禁放行 → 需主人决定，且需真实 B0 执行与新 GO。
3. 真实模型问答与 OCR 复验、供应商账单核对 → 需主人明确授权。
4. 受限 H2 真实批次端到端派生（FU-2 B-1）与四 run CLI 组合真件（B-3）→ 无授权真件。
5. 三张卡的真实分享副本再扫描 → 需生成分享副本的授权动作。
6. 浏览器端到端（Playwright）与构建产物级前端证据。

## 9. 待主人决定

| # | 事项 | 影响 |
|---|---|---|
| D-A | 是否接受"修复候选 → 重新冻结（含新 B0 准入）"的路径与费用 | 决定修复候选能否成为发布候选 |
| D-B | 是否把 `derive-cards` 的 `--compat` 默认值保持 v0.6、`_emit` 默认非 strict（FU-2 遗留风险 2/②） | 影响下游读取与批次兼容 |
| D-C | FU-4 默认模式是否升级为严格（会破坏既有下游读 `card_file.path`） | 影响分享副本安全面 |
| D-D | 是否授权 live 模型以完成亲验第 3/6 项（生成式问答 + 来源详情） | 影响亲验覆盖率与费用 |

## 10. 独立复核结论与处置

独立复核（全新上下文，`review.md` 511 行 + `review-evidence/`）结论：**建议接收为"进入独立冻结/亲验流程的候选"**，
FU-1/FU-3/FU-4/干净检出 = PASS，FU-2 = PASS-WITH-RESERVATIONS，集成 = 事实核对一致。它发现 4 项问题，处置如下：

| 复核发现 | 性质 | 处置 |
|---|---|---|
| 亲验实例实际 `import mktkb` 指向**修复树**（editable 安装），"版本=原核收候选"不实 | **交付缺陷（非产品缺陷）** | 已修：启动器设 `PYTHONPATH=<干净检出>\backend\src`，日志首行打印 `ACCEPTANCE_MODULE=…\mktkb-clean-93486b6\backend\src\mktkb\__init__.py`；重置数据后重跑探针 12 OK / 1 FAIL（同上），并入 [owner-acceptance.md](owner-acceptance.md) §五 |
| FU-2 新用例 CWD 依赖（从 `backend` 运行 1 条失败） | 测试卫生债 | 已在 §3 如实登记（不改他人测试、不加 skip）；仓库标准调用为仓库根 |
| 文档 4 处不准确（补丁行尾成因、FU-2 失败码、SHA256SUMS 口径、改前探针未随交付） | 文档缺陷 | 本报告已更正前三项；改前探针脚本已补入 [`FU1/evidence/scripts/repro_fu1.py`](FU1/evidence/scripts/repro_fu1.py) |
| 12 条失败=版本门，不得开脱 | 结论一致 | §4 明确写为"需重新冻结 + 新 B0 准入"，不当作回归、也不淡化 |

复核自建探针与证据：`review-evidence/`（8 探针 + 10 证据 JSON；原始件在仓库外 `D:\mktkb-fu-review\`）。
复核未跑项：浏览器、真模型、OCR、主人亲验 7 项中的 live 部分（均在 `review.md` 单列 NOT-RUN）。
