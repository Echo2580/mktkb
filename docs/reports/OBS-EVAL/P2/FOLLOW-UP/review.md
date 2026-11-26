# P2 剩余四项工程债 · 独立验收复核报告（review）

- 复核人：独立验收助手（全新上下文，未参与开发，不代表开发方）
- 日期：2026-11-21（Asia/Shanghai），复核窗口约 02:59–03:35
- 仓库：`D:\GPT项目\市场部AI知识库`｜分支 `codex/p2-e2e`｜HEAD `93486b6590c6542f34dd70d20a19b792c659f416`
- 干净候选检出：`D:\mktkb-clean-93486b6`（`git worktree`，detached，`git status --porcelain -uno` **0 项**）
- 解释器：`D:\GPT项目\市场部AI知识库\.venv\Scripts\python.exe`（3.12.7 / pytest 9.1.1）
- 性质：**独立离线核验**。未跑真实模型 / OCR / 外网请求；未跑浏览器端到端；未重跑主人亲验 7 项（会改验收实例数据）。
  本次复核**没有** `git add/commit/push/checkout/reset/stash/clean`，**没有**修改产品代码、被测测试或开发方报告；
  自建探针与证据全部写在仓库外 `D:\mktkb-fu-review\`，并复制一份到本目录 [`review-evidence/`](review-evidence/)。
- 一句话结论：**FU-1 / FU-3 独立成立，FU-4 独立成立，FU-2 成立但有保留，集成与干净检出的事实核对全部一致；
  发现 1 处需要开发方修正后才能交给主人的“亲验版本口径不实”（非产品缺陷），以及 4 处文档/测试卫生问题
  （补丁行尾成因、FU-2 失败码、`SHA256SUMS`/156 口径、已删除探针未随交付）。
  12 条集成失败经独立判定确为 `candidate.pipeline` 版本门，需重新冻结，不是代码回归。**

---

## 0. 结论表（先看这张）

| 项 | 独立结论 | 关键证据（我自己跑的） |
|---|---|---|
| A 现场与范围（HEAD / 改动面 / 禁止区 / 指纹） | **PASS** | HEAD/分支一致；9 个 tracked 改动中 7 个属本轮、2 个簿记件 mtime 早于本轮；`gate.py`/`p2_b0.py`/`p2_release_public.py`/`cli.py`/`var/**`/批准配置/`candidate-freeze.json` **零改动**；指纹 13/13 改后、7/7 改前摘要一致；补丁 `apply --check` exit 0，12/13 逐字节一致 |
| B FU-1 绑定实际 RAG 索引版本 | **PASS** | 同一探针：冻结候选上 产品 3 / RAG 4 / manifest 3 / gate **fail+version_binding**；修复树上 manifest 4 = 两条 trace 4 / gate **pass**；错绑 3 与 99 仍 fail；索引不可得→绑定不完整+门禁拒；漂移→`aborted/index_changed` 只发 1 轮。B0 回归 16 passed |
| C FU-3 正式入口默认回源 | **PASS** | 真实清单正例 `evidence_provenance=pass`（24 题/156 文件/15 trace/0 问题），四档、tally、6 条机械失败、D-011 披露行原样；对真实清单**临时副本**做 6 类单点合法篡改，正式入口全部 **blocked**（预期固定码），无一降级为 pending/pass；同一 6 类篡改在**冻结候选**上全部 **pass**（缺陷复现） |
| D FU-2 v3 单 run 派生 | **PASS-WITH-RESERVATIONS** | `derive-cards --help` exit 0；v2 命令集恰为 4 条且拒绝 `derive-cards`（`usage_invalid`, exit 3）；5 类非法输出根全部 `derive_output_in_forbidden_root` 且不建目录；合法仓外目录→`path_missing`（说明不是一刀切拒绝）。**保留**：正例出卡/确定性/五道校验我只复跑了开发方测试，未自建成功夹具；`cd backend` 下 1 条因夹具 CWD 依赖失败 |
| E FU-4 公开层路径脱敏 | **PASS** | 3 个合成样本（受限绝对路径 / 带空格 / 含换行异常串）经公开清洗 + 两个入口真实 `_emit`/`detail` 出口：受限路径原文 0 命中、无受限根名/密钥名、`holdout` 字样原因码与计数逐字保留、幂等；`frozen-digest.before/after` 聚合 `8695172a…` 相同；`H2-REBUILT-CARDS` 7/7 与 `git show HEAD:` **逐字节一致**；新数据件独立扫描 0 命中 |
| F 集成回归（428/12） | **PASS（事实核对一致）** | 复跑同一集合：**428 passed / 12 failed**，exit 1，123.10s；12 条 = positive 7 + negative 1 + real_ncu 4；逐条原因经夹具探针确认：唯一阻断行 `candidate.pipeline: release_version_mismatch`，合成夹具**没有** provenance 行、真实清单 provenance=**pass**；干净候选同一批 **42 passed**（15+27） |
| F 干净检出核验 | **PASS** | 47/47 冻结工件摘要与字节一致（缺 0、不符 0）；2/2 台账前缀一致；批准配置 `b1094cc7…`、`gate-result.real-ncu.json` `d4c98f92…` 一致；B0 准入与工作树**字节相同**，freeze 记的 `2226fa20…` 经 `p2_b0.payload_sha256()` 复算一致 |
| G 亲验交接（地址/版本/模式） | **PASS-WITH-RESERVATIONS** | 地址与模式属实：`127.0.0.1:8177/api/v1/healthz` → 200、`127.0.0.1:5173/` → 200，启动脚本为 RAG offline / OCR off / 无模型凭据 / 独立数据目录。**但“版本=原核收候选”不实**：按同一启动方式实测 `import mktkb` 解析到 `D:\GPT项目\市场部AI知识库\backend\src`（修复树），不是干净检出（见 §2.7.2） |

> 判定纪律说明：凡我没有实际验证的，一律标 `BLOCKED` 或写进 NOT-RUN，不给 PASS；“开发方测试通过”只作为复跑事实记录，
> 不作为我自己的独立结论依据（FU-2 成功分支即属此类，已在表中明示）。

---

## 1. 复核范围、方法与现场核对

### 1.1 范围与方法

先读任务书（§6 干净检出、§7 验收线）与开发方 `report.md` + 四份 `dev-report.md` + `owner-acceptance.md` +
`candidate-fingerprint.json`，再按“**先复现、后验证**”的顺序做四类动作：

1. **Git 取证**：HEAD、改动面、禁止区、逐文件 SHA-256（改前用 `git cat-file blob HEAD:<path>` 取原始字节）。
2. **自建探针**（仓库外，`D:\mktkb-fu-review\probes\`）：FU-1 入口级探针、FU-3 真实清单篡改探针、
   FU-2 CLI 面/输出根守卫探针、FU-4 脱敏探针、指纹/补丁/干净检出具验脚本。**每个探针都在冻结候选与修复树上各跑一次**，
   用来区分“修复前缺陷”与“修复后行为”。
3. **复跑**开发方测试与集成集合（作为事实核对，不作为唯一依据）。
4. **边界核对**：网络闸门、出站路径、日志/证据扫描、亲验实例的地址与版本。

### 1.2 现场核对（对应任务书 A）

```
$ git rev-parse HEAD
93486b6590c6542f34dd70d20a19b792c659f416
$ git branch --show-current
codex/p2-e2e
$ git status --porcelain --untracked-files=no
 M .claude/handoffs/_index.md
 M backend/src/mktkb/evaluation/p2_release_gate.py
 M backend/src/mktkb/evaluation/p2_runner.py
 M backend/src/mktkb/evaluation/product_adapter.py
 M backend/tests/evaluation/test_p2_live_wiring.py
 M backend/tests/evaluation/test_p2_runner.py
 M docs/reports/OBS-EVAL/P2/T207-QUALITY-REPAIR/manager.md
 M tools/p2_h2_controlled_execute.py
 M tools/p2_h2_v3_controlled_execute.py
```

- **9 个 tracked 改动**，其中 7 个是本轮修复文件（与 `candidate-fingerprint.json` 的 7 个 modified 完全对应）；
  另 2 个是 `.claude/handoffs/_index.md`（mtime `2026-11-18 22:50:33`）与
  `docs/reports/OBS-EVAL/P2/T207-QUALITY-REPAIR/manager.md`（mtime `2026-11-19 00:38:48`），
  **早于本轮修复文件（02:27–02:45）**，内容也只在追加历史簿记，可判定为开工前既有在途改动，与本轮无关。
- **禁止区零改动**（命令 `git status --porcelain -- <敏感路径>` 输出为空）：
  `backend/src/mktkb/evaluation/gate.py`、`p2_b0.py`、`p2_release_public.py`、`cli.py`、
  `var/**`、`docs/evaluation/gate_v0_3_approved.json`、`docs/reports/OBS-EVAL/P2/candidate-freeze.json`。
- 未跟踪区有大量历史证据目录（`?? docs/reports/...`、`?? .claude/handoffs/...`）与一个历史遗留怪目录
  `%SystemDrive%/`（内含搜狗输入法缓存，mtime `2026-11-11/11-12`）——**与本轮无关**，仅作为工作树整洁度观察记录。
- 新文件 6 个（2 个产品模块 + 4 个测试）+ 新增报告目录，与 `report.md` §2/§6 声明一致。

### 1.3 指纹与补丁（我自己复算）

```
# 13 个文件改后摘要 + 字节：全部与 candidate-fingerprint.json 一致（MISMATCH_COUNT=0）
# 7 个 modified 的“改前”摘要：用 git cat-file blob HEAD:<path> 取原始字节复算 → 7/7 一致（BEFORE_MISMATCH=0）
```

| 类别 | 我的结果 |
|---|---|
| 改后 SHA-256 / 字节 | **13/13 一致** |
| 改前 SHA-256（HEAD blob 原始字节）/ 字节 | **7/7 一致** |
| `candidate.patch` 洁净重放（仓库外 `git init` + 7 个 HEAD blob + `git apply`） | `apply --check` **exit 0**、`apply` exit 0、**12/13 逐字节一致** |
| 第 13 个（`p2_release_gate.py`） | 补丁产物 27,392 B 全 LF；工作树 28,011 B 全 CRLF；**CRLF→LF 归一后完全相同**（与开发方 §6 结论一致） |

证据：`review-evidence/evidence/patch-roundtrip.json`、`review-evidence/evidence/clean-checkout.json`。

> 提示（不影响结论）：洁净重放必须先把 scratch 仓库 `core.autocrlf` 设为 `false`（本机 system 级为 `true`），
> 否则 `git apply` 会把行尾改成 CRLF、13 个文件全不一致——我第一次跑就踩到这个坑，已按仓库自身配置修正后复跑。

---

## 2. 逐项核验

### 2.1 FU-1 · 通用 P2 入口绑定实际 RAG 索引版本（B 项）

**自建探针**：`review-evidence/probes/fu1_probe.py`（Mock chat、无网络；夹具沿用“先灌历史版，再以 `document_ref`
发布同一资料新版本，再灌第三份文档”的真实换版形状；探针自己构造 plan/授权/数据集，不复制开发方测试代码）。
同一探针在**冻结候选**与**修复树**各跑一次：

```
$ .\.venv\Scripts\python.exe -X utf8 D:\mktkb-fu-review\probes\fu1_probe.py --root <CHECKOUT> --label <L> --out <JSON>
# 冻结候选 D:\mktkb-clean-93486b6 → exit 0（行为=修复前）
# 修复树  D:\GPT项目\市场部AI知识库 → exit 0（行为=修复后）
```

| 观测 | 冻结候选（改前） | 修复树（改后） |
|---|---|---|
| `product_revision()` / `index_status()["index_revision"]` | **3 / 4**（两套计数器确实不同） | **3 / 4** |
| `run_manifest.json.index_revision` | **3**（= 产品计数，错） | **4**（= RAG 索引版本） |
| `binding.index_revision` / `complete` / `missing` | 3 / true / `[]` | 4 / true / `[]` |
| 逐轮 trace `index_revision`（rag / legacy） | **4 / 3**（不等） | **4 / 4**（都等于 manifest） |
| 硬门禁 `trace_integrity` | **fail**，`hard_failures=["trace_integrity"]`，`version_binding`（mismatched=`index_revision`），`exit 1` | **pass**，无 `version_binding`（整体 `exit_code=3`=既有 `EXIT_UNKNOWN`，因最小夹具另有 unknown 项） |
| `config_hash` 由组件重算 | 一致 | 一致（口径未放宽） |

**反例**（同一探针，在修复树上把 manifest 的 `index_revision`/`binding.index_revision` 改成错值再进硬门禁）：

| 错值 | `trace_integrity` | `version_binding` 行 | mismatched | exit |
|---|---|---|---|---|
| 3（产品计数） | **fail** | 2 行 | `["index_revision"]` | 1 |
| 99（任意值） | **fail** | 2 行 | `["index_revision"]` | 1 |

**缺证**（`index_status().ready=False`）：

| 观测 | 冻结候选 | 修复树 |
|---|---|---|
| manifest `index_revision` | **3（猜了一个数）** | **null** |
| `binding.complete` / `missing` | true / `[]` | **false / `["index_revision","trace_identity"]`** |
| `binding.config_hash` / `trace_identity_bound` | 有值 / true | **null / false** |
| trace 身份字段（run_id/config_hash/manifest_sha256/pipeline_version） | 全部写满 | **全部 null**（`index_revision` 仍为产品检索自己写的 4，属产品观测，非评测补写——与 dev-report 口径一致） |
| 进硬门禁 | 接受 | **拒绝**：`run_manifest_incomplete: manifest 缺少 ['index_revision','config_hash']` |

**漂移**（首轮作答后真实删一份文档）：

| 观测 | 冻结候选 | 修复树 |
|---|---|---|
| `status / stop_code` | **succeeded / –（混合版本 run 被当成功）** | **aborted / index_changed** |
| failure stage / 已发轮次 / `requests.jsonl` 行数 | – / 2 / 2 | `index_after_turn` / **1** / **1** |

**B0 兼容**：`backend/tests/evaluation/test_p2_b0.py` → **16 passed / exit 0**；该测试文件与
`p2_b0.py` 均为 HEAD 字节（未改）；`test_p2_runner.py:1470` 的 B0 漂移断言 `("aborted","b0_index_changed")`
位于唯一改动 hunk 之外，逐字未变；B0 注册工件 `var/eval/baselines/7981d4afc2d1/*` 与干净检出字节相同（§2.6）。

**结论：PASS。** 这是本次四项里证据最强的一项：缺陷在冻结候选上可复现（且“缺证时猜数”“漂移仍成功”两个
副作用也被我的探针独立发现），修复后正反例、缺证、漂移四类行为全部符合任务书要求，且没有动门禁去“让它过”。

证据：`review-evidence/evidence/fu1-fixed-tree.json`、`fu1-clean-prefix.json`。

### 2.2 FU-3 · N/C/U 正式入口默认回源（C 项）

**自建探针**：`review-evidence/probes/fu3_probe.py`。用生产脚本 `wire_real_ncu.py::build_inputs()` 组真实
N/C/U 门禁输入（24 题 = N8/C6/U10），再对**真实清单的临时副本**逐次只做一处合法篡改，重算清单摘要并同步
selection authority，最后走**正式入口** `evaluate_release_gate()`。仓库文件全程只读。

**正例（真实清单原样）**：

```
decision=blocked  counts={pass:38, blocked:1, observed:10}  pending=0
唯一 blocked 行 = candidate.pipeline（release_version_mismatch）
evidence_provenance = pass：
  cases_checked=24, files_checked=156, files_verified=156, traces_checked=15,
  u_real_cases=1, u_local_cases=9, problem_count=0, source_unavailable=[]
四档（evidence_manifest 行 detail.tiers）：ADOPTED 7/2/9；ADOPTED_WITH_BINDING_PROOF 1/4/1；
  FAIL 0/0/0；UNKNOWN 0/0/0
tally：tallies.formal=pass（N8/C6/U10）、tallies.unconditional=observed（7/2/9）
6 条原机械失败保留：N01、C01、C02、C05、C06、U01 均 trace_integrity:version_binding
D-011 披露行：hard_gate_min_sample.run_level_subset = observed（update_delete 计划 10 / run 级已评 1，含主人 D-011 授权文字）
evidence_manifest = pass：SHA256SUMS {verified:17, mismatch:0, missing:0}、scope_cases=15、
  tallies_declared 与 recomputed_pass 均为 N8/C6/U10；156 个逐题证据文件由 evidence_provenance 行核（files_verified=156）
```

**负例（六类；正式入口、真实清单副本）**：

| 篡改（单点、其余合法） | 门禁决定 | provenance 决定 / 原因 | 是否降级为 pending/pass |
|---|---|---|---|
| N01 题目摘要改成 `e*64`（合法十六进制、内容错配） | **blocked** | blocked / `provenance_failed`；`QUESTION_HASH_MISMATCH`（+`TRACE_CASE_MISMATCH`） | 否 |
| 证据路径改成批准根内**不存在**的路径 | **blocked** | blocked / `EVIDENCE_PATH_MISSING` | 否 |
| 证据路径改成**越界绝对路径** `C:\Windows\win.ini` | **blocked** | blocked / `EVIDENCE_PATH_OUT_OF_ROOT` | 否 |
| 同 run 两题**互换 trace_id** | **blocked** | blocked / `TRACE_CASE_MISMATCH`（+`TRACE_IDENTITY_MISMATCH`） | 否 |
| U 的 **R 档**加 L 档字段（`test_file`） | **blocked** | blocked / `U_TYPE_MIXED` | 否 |
| U 的 **L 档**加 R 档字段（`run_id`） | **blocked** | blocked / `U_TYPE_MIXED` | 否 |

**缺陷复现（关键对照）**：同一 6 类篡改，在**冻结候选** `D:\mktkb-clean-93486b6` 上重跑：
`decision` 全部为 **pass**（38/0/9），且**不存在** `evidence_provenance` 行——即修复前“正常送检却带病通过”，
与任务书描述的缺口完全吻合。

**复跑**：`test_p2_fu3_provenance.py` → **21 passed**（含依赖本机历史 run 的真实清单集成用例，未被 skip）。

**结论：PASS。** 正例的四档/tally/6 条机械失败/D-011 披露行逐值保留，负例全部 fail-closed，且“默认执行”
这一点由我自己的真实清单篡改在正式入口复现，不依赖开发方测试。

证据：`review-evidence/evidence/fu3-fixed-tree.json`、`fu3-clean-prefix.json`。

### 2.3 FU-2 · v3 单 run 离线派生（D 项）

**复跑**（仓库根）：`test_p2_fu2_derive_cards.py` → **19 passed / exit 0**（含正例出卡、五道校验负例、
非法输出路径、四场景合成、确定性）。

**CWD 敏感性（我自己复现并判定）**：

```
$ cd D:\GPT项目\市场部AI知识库\backend
$ ..\.venv\Scripts\python.exe -m pytest tests\evaluation\test_p2_fu2_derive_cards.py -q
→ 1 failed, 18 passed（失败用例 test_four_synthetic_derived_runs_compose_with_official_validators）
→ mktkb.evaluation.p2_holdout_scenarios.ScenarioError: scenario_ingest_invalid
```

判定：**这是测试卫生问题，不是产品缺陷，也不是本轮新引入的约定**。理由是同一套夹具所属的
`test_p2_holdout_scenarios.py`（HEAD 未改）在 `backend` 目录下 **34 failed / 50 passed**、在仓库根
**84 passed**；说明“夹具按仓库根相对路径解析”是仓库既有约定，FU-2 的新用例只是复用了该夹具。
影响：CI/开发者若习惯在 `backend/` 下跑 pytest 会看到 1 条红；README 的标准调用在仓库根，故不影响交付结论。
**建议**：把该用例改为不跨模块依赖（或对夹具路径用 `ROOT` 绝对化），与既有 34 条一并作为历史测试债处理。

**自建 CLI 探针**：`review-evidence/probes/fu2_cli_probe.py`。

| 检查 | 我的实测 |
|---|---|
| `p2_h2_v3_controlled_execute.py derive-cards --help` | **exit 0**（子命令存在，`--out-dir/--binding/--run-index/...` 齐全） |
| v3 命令集 | `{plan-private, check-only, run, derive-cards}` |
| v2 入口 `derive-cards --help` | **exit 3**，`usage_invalid`，`choose from 'plan-private', 'preflight', 'run', 'recompute'`（**v2 命令集与拒绝码未变**） |
| 非法输出根：仓库子目录 | `derive_output_in_forbidden_root`，exit 2，**未建目录** |
| 非法输出根：`<repo>\tmp-x\..\__review_derive_out__` | 同上 |
| 非法输出根：大小写变体 `<repo>\DOCS\__review_derive_out__` | 同上 |
| 非法输出根：`<repo>\var\__review_derive_out__` | 同上 |
| 非法输出根：尾斜杠 | 同上 |
| 合法仓外目录 + 不存在的 binding | `path_missing`（说明守卫先过、进入输入校验，不是一刀切拒绝） |
| 仓库目录是否被写入 | 探针前后仓库顶层无新增目录 |

**保留（PASS-WITH-RESERVATIONS 的原因）**：`derive-cards` 的**成功分支**（合成 v3 单 run 出卡、五道校验全过、
四场景合成、确定性写盘）我**没有**自建独立夹具复现——这部分我只做了“复跑开发方 19 条测试”，属开发方测试级证据；
任务书 D 项要求的四条我均已独立完成。真正受限真件的端到端派生（FU-2 的 B-1/B-3）仍为 NOT-RUN。

证据：`review-evidence/evidence/fu2-cli-fixed-tree.json`。

### 2.4 FU-4 · H2 输出及分享材料路径脱敏（E 项）

**复跑**：`test_p2_fu4_safe_output.py` → **24 passed / exit 0**。

**自建探针**：`review-evidence/probes/fu4_probe.py`。三个**合成**样本：
① 合成的 Windows 绝对受限路径（含受限根名 + `.fernet` 名）；
② 带空格的路径（含 `.key` 名）；
③ 含换行的异常串（Traceback 中内嵌 3 个绝对路径）。

| 样本 | 公开清洗后 | 受限片段残留 | 幂等 | 清洗后自扫描 |
|---|---|---|---|---|
| ① 合成受限绝对路径 | `<redacted-path:absolute:286cbdf70b6a>` | **0** | 是 | `total=0, clean=true` |
| ② 带空格路径 | `<redacted-path:absolute:7a94b3550d58>` | **0** | 是 | clean |
| ③ 含换行异常串 | 3 个路径全部记号化 | **0** | 是 | clean |

不只调清洗函数，还喂给**两个受控入口的真实公开出口**（`_emit` 默认 / 严格、v2 `_emit`）：

- 三处出口的公开 JSON 中，三个样本原文、受限根名、带空格目录名、密钥文件名 **全部 0 命中**；
- `error_code`、`counts`、`reason_codes`（含 `holdout_hard_failure_unverified`）、`thresholds_approved=false` **逐字保留**（未误伤固定码/阈值）。

**原冻结工件未改**：

| 检查 | 我的结果 |
|---|---|
| `FU4/evidence/frozen-digest.before.json` vs `.after.json` | `scan_tree_sha256` 均为 `8695172aba511426f004995e6755fb8caac2fc2996c7e6b15769bccc93e31c75`；`scan_roots`、`scanned_text_files=2181`、14 个 `focus_files` **逐值相同** |
| `H2-REBUILT-CARDS` 与 `git show HEAD:` | **7/7 文件全部被跟踪且逐字节相同**（`cards-index.json`、`h2-composition-aggregate.json`、`h2-source-proof{,.full}.json`、`report.md`、`review.md`、`derive_v3_cards.py`） |
| 新公开产物独立扫描（FU2+FU4 数据件 10 个，排除 scripts） | `windows_abs/unc/key/env/restricted_marker` **全 0** |

**结论：PASS。** 冻结快照的聚合一致是开发方产出的证据，我用“7/7 与 HEAD 字节一致 + 独立扫描 0 命中”做了
不依赖其脚本的第二来源核对。

证据：`review-evidence/evidence/byte-and-scan.json`（探针原始输出见 `D:\mktkb-fu-review\evidence\fu4-fixed-tree.json`）。

### 2.5 集成回归（F 项）

**复跑命令**（按报告 §4 的 21 个文件显式展开，仓库根）：

```
$ .\.venv\Scripts\python.exe -m pytest <21 files, -q -p no:cacheprovider -rf>
→ 428 passed, 12 failed, 1 warning in 123.10s（exit 1）
```

12 条失败 = `test_p2_release_gate_positive.py` **7** + `test_p2_release_gate_negative.py` **1** +
`test_p2_release_gate_real_ncu.py` **4**，与报告数字完全一致。

**逐条确认“都是版本门”**（不接受“断言是 blocked≠pass 就算”）：

1. 失败断言语义：断言均为 `assert <decision> == pass/pending` 或 `cli.main(...) == 0`，实际得到
   `blocked` / `3`（`EXIT_UNKNOWN`）。
2. **合成夹具探针**（`review-evidence/probes/gate_fixture_rows.py`，直接 import 出厂的
   `test_p2_release_gate_fixtures.build_complete_inputs`，不复制夹具）：
   - 修复树：三种夹具全部 `blocked`，**唯一 blocked 行 = `candidate.pipeline: release_version_mismatch`**；
     其余非 pass 行都是 `observed`；**不存在 `evidence_provenance` 行**（说明 FU-3 没有参与这些失败）。
   - 冻结候选：同一夹具 **decision=pass**，无任何 blocked 行。
3. **真实清单侧**：我的 FU-3 探针在同一真实清单上得到 `blocked`，`blocked_rows=["candidate.pipeline"]`、
   `evidence_provenance=pass`——4 条 real_ncu 失败同源。
4. **流水线摘要因果**：`pipeline_source_sha256()` 冻结候选 = `28aae43c4696…`、修复树 = `2aa9177b96fc…`；
   该函数显式包含 `p2_runner.py` / `product_adapter.py`（源码已读），所以 FU-1 的修复**必然**改变该摘要。
5. **基线对照**：在干净检出跑同一批 3 个文件 → **42 passed**（positive+real_ncu 15、negative 27，exit 0）。

**结论：PASS（事实核对一致）。** 12 条失败是“候选字节 ≠ B0 准入字节”的既有版本门，**不是代码回归**；
同时也不应替它开脱——**该候选必须重新冻结并重建 B0 准入后才可能变绿**，这属主人决定（D-A）。

### 2.6 干净检出核验（F 项）

`D:\mktkb-clean-93486b6`：HEAD = `93486b6…`、tracked 改动 0；已备 `var/eval/baselines/7981d4afc2d1`、
`T209-PREP`、`T207-RETEST-20261119`、外部历史 run `D:\mktkb-p2-run\t207\{R1,R2,R4}\data`。**无 BLOCKED**。

| 检查 | 我的结果（自建 `clean_checkout_check.py`） |
|---|---|
| `candidate-freeze.json → frozen_artifacts`（47） | **47/47 摘要+字节一致**（missing 0 / mismatch 0） |
| `records_append_only`（manager-decisions / manager-acceptance） | **2/2** 前缀 SHA-256 一致（两文件均已追加增长，前缀未变） |
| 批准配置 `docs/evaluation/gate_v0_3_approved.json` | 一致（`b1094cc7…`） |
| `CROSS-SCENARIO-GATE/gate-result.real-ncu.json` | 一致（`d4c98f92…`） |
| B0 准入 `b0-admission.json` | 干净检出与工作树**字节相同**；freeze 记的 `2226fa20…` 经 `p2_b0.payload_sha256()` 复算 = `2226fa208aec…`，**同口径吻合** |
| 干净候选门禁测试（positive + real_ncu + negative） | **42 passed / exit 0** |

> 一个口径说明（不影响结论）：`candidate-freeze.json` 的 `head` 字段记的是 `97b0066…`，而当前分支 HEAD 是
> `93486b6…`。`97b0066..93486b6` 是“P2 收口并发布冻结候选”那一个提交（387 文件），freeze 的 `worktree` 段也记了
> `tracked_modified: 47`——即冻结的是当时的**工作树字节**，随后被 `93486b6` 收录。因此“在 `93486b6` 干净检出上
> 复验 47 件”是正确做法，实测 47/47 一致也印证了这一点。

### 2.7 边界与诚实性 / 亲验交接（G 项）

#### 2.7.1 零真实调用的可核事实

| 检查 | 结果 |
|---|---|
| 4 个新测试文件是否带网络闸门 | **都带**：均 `import`/`pytestmark = usefixtures("t09_network_guard")`（复用既有验收级闸门，未私造） |
| `derive-cards` 是否有出站路径 | 入口 `_install_network_guard()` 劫持 `socket.connect/connect_ex/create_connection`，非 loopback 直接 `RuntimeError("v3_entry_network_blocked")`；`_dispatch_derive_cards` 输出 `network = guard.snapshot()`（external/local 计数）；派生只做文件读取+解密+分类，无 HTTP 客户端 |
| 日志/证据是否含真实密钥或受限路径原文 | 我对 FOLLOW-UP 全目录自扫描：`restricted_marker=0`；4 处 `.key`/`.fernet` 命中全在 `FU2/evidence/scripts/repro_v3_reject.py`（合成文件名）；`env_file` 6 处为说明文字或合成 `.env`；无密钥值、无凭据 |
| 我自己的最小复核产物 | 未产生真实调用；探针全程 Mock/只读；外网 0（探针在本地进程内跑，无 HTTP 客户端） |

发现的两处**非受限但值得注意**的公开层内容（不影响 FU-4 判定，供外发时裁剪）：
`FU1/evidence/*.log` 含开发机临时目录绝对路径与本机用户名（`C:\Users\dell1712\AppData\Local\Temp\...`）；
`owner-acceptance.md` 含亲验实例的测试账号口令明文（`admin` / `OwnerAccept-20261122` 等，属交付给主人的入口信息）。

#### 2.7.2 亲验地址、模式与**版本口径**（重点发现）

```
$ Invoke-WebRequest http://127.0.0.1:8177/api/v1/healthz  → 200（15 B）
$ Invoke-WebRequest http://127.0.0.1:5173/                 → 200（758 B）
进程：12868 = python -B -m uvicorn mktkb.main:create_app --factory --host 127.0.0.1 --port 8177
      36172 = node ...\市场部AI知识库\frontend\node_modules\...\vite.js
```

- 地址、端口、运行模式（RAG offline / OCR 关闭 / 无模型凭据 / 独立数据目录 `D:\mktkb-accept-93486b6`）
  与 `owner-acceptance.md` 及启动脚本一致 → 这部分 **PASS**。
- **但“版本 = 原核收候选 93486b6”不成立**。`start-acceptance.ps1` / `start-backend.ps1` 只 `Set-Location`
  到干净检出、**没有**把该检出的 `backend/src` 放进 `sys.path`；而 venv 里唯一的 `mktkb` 是 editable 安装，
  `.pth` 指向**主仓库修复树**：

```
.venv\Lib\site-packages\__editable__.mktkb-0.1.0.pth
  → D:\GPT项目\市场部AI知识库\backend\src
```

  按启动脚本的完全相同条件实测（cwd = 干净检出、`PYTHONPATH` 为空）：

```
$ cd D:\mktkb-clean-93486b6
$ .\.venv\Scripts\python.exe -B -c "import mktkb, mktkb.evaluation.product_adapter as pa; print(mktkb.__file__); print(pa.__file__)"
D:\GPT项目\市场部AI知识库\backend\src\mktkb\__init__.py
D:\GPT项目\市场部AI知识库\backend\src\mktkb\evaluation\product_adapter.py
```

  即：在**已记录的启动方式**下（cwd=干净检出、无 `PYTHONPATH`、同一 venv），进程实际解析到的是**修复树字节**
  （含 FU-1/FU-3 的 evaluation 改动），不是冻结候选。启动脚本与 `backend.log` 中都没有设置 `PYTHONPATH` 的痕迹；
  若要主张“确实跑的是干净检出”，唯一可能是操作者 shell 曾额外导出 `PYTHONPATH`（无任何记录），因此该主张**目前不可核**，
  按现状应判为“版本披露不实”。
  对主人今天要看的 7 项 API 级检查，差异只落在评测/CLI 代码路径（API 面不可见），**预期行为无差别**；
  但这违反任务书 §6.1“输出**实际**启动目录、提交/候选摘要”的要求，属于**交付缺陷（文档/配置级，低—中）**，
  需要一行修正后重启再核：`$env:PYTHONPATH = "$root\backend\src"`（或改用不含 editable `.pth` 的独立 venv）。
- 我未重跑主人亲验 7 项（会写验收实例数据）→ 该部分 **NOT-RUN**；`evidence-owner-acceptance-probe.json`
  仅为开发方自测记录，我不据此判 PASS。

---

## 3. 与开发方报告不一致之处

| # | 位置 | 开发方说法 | 我的实测 | 性质 |
|---|---|---|---|---|
| 1 | `owner-acceptance.md` §一 / `report.md` §1、§6 | “版本 = 原核收候选 93486b6；启动目录 = 干净检出” | 进程实际 `import mktkb` 解析到**修复树** `...\市场部AI知识库\backend\src`（editable `.pth`；启动脚本未设 `PYTHONPATH`） | **交付缺陷**（配置/披露），需修正后重启复核 |
| 2 | `report.md` §6 补丁往返 | “该文件（`p2_release_gate.py`）工作树 CRLF、**HEAD blob 为 LF**，`core.autocrlf` 口径所致” | HEAD blob **本身就是 CRLF**（26904 B 中 600 个 CRLF）；仓库 local `core.autocrlf=false`（system 为 true）。补丁产物是 LF（27392 B）。**“12/13 逐字节 + 1 个仅行尾不同”的结论我复现了**，但成因描述不对 | 文档不准确（结论不受影响） |
| 3 | `report.md` §3 FU-2 已知瑕疵 | 从 `backend` 目录跑该条报 `ScenarioError(scenario_full_dataset_required)` | 实测稳定报 **`scenario_ingest_invalid`**（`p2_holdout_scenarios.py:338`） | 文档不准确（不影响“CWD 敏感”这个事实） |
| 4 | `FU3/dev-report.md` §3 | 保留项写作“`SHA256SUMS` **156/156** 命中” | `SHA256SUMS` 实为 **17 行**（`verified:17, mismatch:0, missing:0`）；**156** 是逐题 `evidence_sha256` 文件数，由 `evidence_provenance` 行核（`files_verified=156`）。两件事被写在一句话里 | 文档口径混淆（两处数字本身都对，不影响结论） |
| 5 | `report.md` §1 干净检出 | 47/47、2/2、批准配置、真实门禁结果、B0 准入一致 | **全部复现一致**（含 `2226fa20…` 规范化 payload 说明） | 一致 |
| 6 | `report.md` §4 集成 | 428 passed / 12 failed，12 条全是版本门 | **一致**，且我用夹具探针把“唯一阻断行 = candidate.pipeline”钉死 | 一致 |
| 7 | `FU1/dev-report.md` §1 | 改前复现引自已删除的 `test_zzprobe_fu1.py` | 交付物里确实没有该探针（不可复跑）；我用自建探针独立复现了同一缺陷，并额外发现“缺证猜数/漂移仍成功” | 证据可复跑性不足（已由我补齐） |

---

## 4. 真实缺陷 / 版本门 / 环境依赖 分类

**真实缺陷（需开发方处理）**

1. **亲验实例版本口径不实**（§2.7.2）：一行 `PYTHONPATH`（或独立 venv）即可修，但必须重启并重跑自测探针；
   在修正前，`owner-acceptance.md` 的“原核收候选”表述不可作为主人亲验的依据。
2. **FU-2 新用例的 CWD 依赖**（§2.3）：`test_p2_fu2_derive_cards.py::test_four_synthetic_derived_runs_compose_with_official_validators`
   在 `backend/` 下必红。它与既有 34 条同源（既有夹具约定），但**出现在本轮新增文件里**，属新交付的测试卫生债。
3. **文档若干处不准确**（§3 #2/#3/#4/#7）：补丁行尾成因、FU-2 失败码、`SHA256SUMS` 与 156 的口径混淆、
   已删除探针未随交付——不影响技术结论，但会误导后续复核。

**版本门（不是缺陷，需重新冻结）**

- 12 条集成失败：`candidate.pipeline: release_version_mismatch`
  （`bound=28aae43c…` vs `candidate=2aa9177b…`），根因是 `pipeline_source_sha256()` 显式包含
  `p2_runner.py`/`product_adapter.py`，FU-1 修复必然改摘要。正确处置：受影响项独立复验 → **重新冻结 + 新 B0 准入** → 主人确认。
  在此之前，任何“修复树已全绿”的说法都不成立；反过来，把这 12 条当代码回归也不成立。

**环境依赖（不是缺陷）**

- 真实清单回源与 real_ncu 用例依赖本机历史材料（`D:\mktkb-p2-run\t207\{R1,R2,R4}\data`、`T207` 批次、`var/eval/baselines/7981d4afc2d1`）。
  本机齐备，故无 BLOCKED；换机器缺这些材料时应记 BLOCKED 而非失败。
- 仓库测试约定“在仓库根运行”（既有 34 条同类失败即证）。

---

## 5. 残余风险与未覆盖项（NOT-RUN）

**残余风险**

| # | 风险 | 说明 |
|---|---|---|
| R1 | FU-4 默认模式仍保留**非受限**绝对路径 | 开发方已披露（FU4 §9 R-1）；我实测：受限路径与密钥名 0 残留，但普通仓外工作目录会原样出现。分享副本应走 `derive-cards` 的 strict 模式 |
| R2 | 脱敏是“形状 + 受限根集合”驱动，不是语义驱动 | 相对路径 + 受限根名 + 非 key/cipher 后缀（如 `mktkb-p2-holdout/cards/a.json` 这种相对写法）不会命中（我读源码确认 `path_kind` 对相对路径返回 None）。实际公开出口以绝对路径为主，风险低 |
| R3 | `candidate.patch` 不能字节级复现 1/13 文件 | 该文件行尾在打补丁时被归一为 LF；**逐字节权威只有 `candidate-fingerprint.json`**（开发方也已如此声明）。若将来用补丁重建候选，需固定该文件的字节口径 |
| R4 | 亲验实例数据隔离只能“文档级”确认 | 启动脚本与数据目录一致；运行期实际 env 我无法读取（无 psutil/句柄工具），未做进程级取证 |
| R5 | `historical-leaks.json` 登记的 746 件历史泄露 | 按任务书“只登记不改”，外发副本必须按清单排除；我未逐件复核该清单完整性（只抽查了根级计数） |
| R6 | FU-1 的“绑定=索引版本”语义只覆盖评测侧 | 历史 run（如 T207 的 `index_revision_binding=11` vs `trace=12`）仍按 D-005 证明采信，口径未变；这是有意保留，不是缺陷 |

**NOT-RUN（我未执行，不得计为通过）**

1. 主人亲验 7 项（登录/上传发布/问答来源/缺字段/换版/删除历史/权限）——会写验收实例数据；且实例版本口径待修正。
2. 浏览器端到端（Playwright）与构建产物级前端证据。
3. 任何真实模型 / OCR / 外网调用、供应商账单核对。
4. `derive-cards` 成功分支的**独立夹具**与真实受限批次的端到端派生（FU-2 B-1/B-3）。
5. 四 run 真 binding 的 CLI 组合（同上）。
6. 修复候选的重新冻结与**新 B0 准入**（需主人 D-A 决定与真实 B0 执行）。
7. 历史泄露清单 746 件的逐件复核。

---

## 6. 技术意见（只给建议，发布/冻结由主人决定）

**建议：可以接收为“进入独立冻结 / 亲验流程的候选”，但附三个前置条件与一个保留。**

- **成立、可进入后续流程**：FU-1、FU-3、FU-4 经我独立正反例验证成立且 fail-closed 方向正确；
  FU-2 的命令面、路径守卫、v2 兼容成立（成功分支为开发方测试级证据）。
- **前置条件 1（必须）**：修正亲验实例的 `mktkb` 导入路径并重启，然后按 `owner-acceptance.md` 重跑一次自测探针，
  把“实际加载路径/版本”写进交接页。**在此之前不要把当前实例作为“原核收候选”交给主人。**
- **前置条件 2（必须）**：按任务书 §6.4 走“受影响项定向复验 → 重新冻结（含新 B0 准入）→ 主人确认”，
  12 条版本门才算处置完毕；在此之前该修复树**不是**已核收候选。
- **前置条件 3（建议）**：修掉 FU-2 那条 CWD 依赖，并更正 `report.md` 的三处表述（补丁行尾成因、FU-2 失败码、删掉的探针）。
- **保留**：FU-2 的成功分支我未自建独立夹具；若主人要求“四项全部独立正反例”，需再补一次真件或独立合成夹具的派生正例。

---

## 7. 自建探针位置与复跑方式

探针与原始证据默认在仓库外 `D:\mktkb-fu-review\`；为便于复核，已**复制**到本目录
[`review-evidence/`](review-evidence/)（`probes/` 8 个脚本、`evidence/` 10 份 JSON）。
`review-evidence/probes/` 内含合成检测字面量（受限根名、`.key` 名）——与外发口径一致，分享时应按
`*/probes/*` 排除；`evidence/` 内只含本机路径与合成样本，不含真实受限路径或密钥。

| 目的 | 命令（仓库根或指定 cwd） |
|---|---|
| FU-1 正/反/缺证/漂移（可对任一 checkout 跑） | `.\.venv\Scripts\python.exe -X utf8 D:\mktkb-fu-review\probes\fu1_probe.py --root <CHECKOUT> --label <L> --out <JSON>` |
| FU-3 真实清单正例 + 6 类篡改（只读真实清单） | `.\.venv\Scripts\python.exe -X utf8 D:\mktkb-fu-review\probes\fu3_probe.py --root <CHECKOUT> --out <JSON>` |
| FU-2 CLI 面与非法输出根 | `.\.venv\Scripts\python.exe -X utf8 D:\mktkb-fu-review\probes\fu2_cli_probe.py --root <CHECKOUT> --python <PY> --out <JSON>` |
| FU-4 合成样本 + 两个入口真实出口 | `.\.venv\Scripts\python.exe -X utf8 D:\mktkb-fu-review\probes\fu4_probe.py --root <CHECKOUT> --out <JSON>` |
| 指纹 / H2 字节比对 / 公开产物扫描 | `.\.venv\Scripts\python.exe -X utf8 D:\mktkb-fu-review\probes\byte_and_scan.py --root <CHECKOUT> --out <JSON>` |
| 干净检出 47 工件 / 2 前缀 / 配置 / B0 | `.\.venv\Scripts\python.exe -X utf8 D:\mktkb-fu-review\probes\clean_checkout_check.py --freeze-root <REPO> --clean <CLEAN> --worktree <REPO> --out <JSON>` |
| 门禁合成夹具“到底哪一行阻断” | `.\.venv\Scripts\python.exe -X utf8 D:\mktkb-fu-review\probes\gate_fixture_rows.py --root <CHECKOUT> --out <JSON>` |
| `candidate.patch` 洁净重放 | `.\.venv\Scripts\python.exe -X utf8 D:\mktkb-fu-review\probes\patch_roundtrip.py --repo <REPO> --out <JSON>` |

复跑顺序建议：先 `clean_checkout_check.py`（便宜）→ `fu1_probe` 两边各一次 → `fu3_probe` 两边各一次 →
`fu2_cli_probe` → `gate_fixture_rows` 两边 → 最后跑集成集合（约 2 分钟）。

---

## 附录 A · 本次复核的执行清单（命令 → 退出码 → 计数）

| # | 命令（摘要） | 退出码 | 关键计数 |
|---|---|---|---|
| 1 | `git rev-parse HEAD` / `git status --porcelain -uno` | 0 | HEAD 一致；tracked 改动 9（7 本轮 + 2 既有簿记） |
| 2 | 13 个文件 SHA-256 + 7 个 HEAD blob 复算（PowerShell/Get-FileHash + git cat-file） | 0 | 13/13、7/7 一致；mismatch 0 |
| 3 | `patch_roundtrip.py` | 0 | `apply --check` 0；12/13 逐字节；第 13 个归一后相同 |
| 4 | `fu1_probe.py`（冻结候选 / 修复树） | 0 / 0 | 见 §2.1 表 |
| 5 | `pytest test_p2_fu{1,2,3,4}_*.py`（仓库根） | 0 | **69 passed**（5/19/21/24） |
| 6 | `pytest tests/evaluation/test_p2_fu2_derive_cards.py`（backend cwd） | 1 | 18 passed / **1 failed**（`scenario_ingest_invalid`） |
| 7 | `pytest tests/evaluation/test_p2_holdout_scenarios.py`（backend / 根） | 1 / 0 | 34 failed・50 passed / **84 passed** |
| 8 | `pytest test_p2_b0.py` | 0 | **16 passed** |
| 9 | `pytest test_p2_live_wiring.py::test_live_mode_binds_actual_rag_index_revision` | 0 | 1 passed |
| 10 | `fu3_probe.py`（修复树） | 0 | 正例 pass 38/1/10 + provenance pass；6 类篡改全 blocked |
| 11 | `fu3_probe.py`（冻结候选） | 0 | 正例 pass 38/0/9；6 类篡改全 **pass**（复现缺陷） |
| 12 | `fu2_cli_probe.py` | 0 | 5 类非法根全 `derive_output_in_forbidden_root`；v2 4 命令不变 |
| 13 | `fu4_probe.py` | 0 | 3 样本 0 残留；3 处公开出口 0 命中 |
| 14 | `byte_and_scan.py` | 0 | H2 7/7 与 HEAD 一致；新数据件 10 个 0 命中 |
| 15 | 集成集合 21 文件 | 1 | **428 passed / 12 failed**（123.10s） |
| 16 | 干净检出门禁 3 文件 | 0 | **42 passed**（15 + 27） |
| 17 | `clean_checkout_check.py` | 0 | 47/47、2/2、config/gate-result 一致、B0 字节相同 |
| 18 | `gate_fixture_rows.py`（修复树 / 冻结候选） | 0 / 0 | blocked（仅 candidate.pipeline）/ pass |
| 19 | 健康检查 + 监听端口 + 进程命令行 | 0 | 200 / 200；8177、5173 |
| 20 | 启动条件导入解析模拟（cwd=干净检出） | 0 | `mktkb.__file__` → **修复树** |

---

*本报告由独立验收助手一次性写就；未改动开发方的 `report.md` 与各 `dev-report.md`，未改动任何产品代码或测试。*
