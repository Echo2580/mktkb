# P2 正式跨场景门禁 · 独立验收报告（任务 4）

2026-11-21（Asia/Shanghai）。**全新独立验收窗口**：不参与开发、不修改被验收方交付物与源码。
工作树 `D:/GPT项目/市场部AI知识库`，分支 `codex/p2-e2e`，接手锚点 HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`（核验一致）。
Python `.\.venv\Scripts\python.exe` 3.12.7 / pytest 9.1.1。**零真实请求**：本窗口全部命令只读本地工件，网络闸门实测 `EXTERNAL=0`（§9.2）。
本窗口只写了两处：本文件与 `.tmp-t4review-isolated/`。未 commit / push / merge / 切分支 / stash / 通配符删除。

> **本文件有四轮结论。** 当前生效的结论是 **§14「D-011 专项确认」：`确认通过（带保留）`**，并回答"D-011 是否构成判据放宽"（见 §14.0）。
> §0–§11 是第一轮 FAIL 原文；§12 是返工 T4-R1 复验；§13 是 H2 接线后的最终核（PASS-WITH-RESERVATIONS）。历史段落均保留取证。

## 0. 独立结论（第一轮，已被 §复验 T4-R1 取代）

**FAIL** —— 阶段一、D-004、B0 回归、v3 清单核对全部复现；但 **D-005 的 U01（R2）绑定行在门禁里被算出后丢弃**：它实际判定为 `blocked / release_inputs_invalid`，却不出现在 `rows[]` 中，导致总门停在 `pending` 而不是 `blocked`，且**伪造 U01 绑定证明不会被拒**（fail-open）。报告 §9.4 的 R2「改写 trace 行 = 1」也与原库实测（0）不符。

一句话：交付物的绝大多数声明可独立复现，但"三份 run 的 binding 全 pass"不成立，且这条缺陷正好落在 D-005 唯一要保护的 U01 上。

## 1. 逐项验收表

| # | 事项 | 我的命令 | 实际输出 | 与被验收方一致 | 判定 |
| --- | --- | --- | --- | --- | --- |
| 1 | 模板输入 → 待交付 | `python -m mktkb.evaluation.cli p2-release-gate --inputs .../inputs.template.json --out .tmp-t4review-isolated/gate-template.json` | **exit 4**；`decision=pending`；`counts={pass:9,blocked:0,pending:19,observed:0}`；`reason_codes=["release_pending_input"]` | 一致 | PASS |
| 2 | 合成齐备 → 通过 | `python .tmp-t4review-isolated/probe_cli_pass.py`（内部 `cli.main([...])`） | **exit 0**；`decision=pass`；`counts={pass:32,blocked:0,pending:0,observed:2}`；`release_allowed=false` | 一致 | PASS |
| 3 | 阶段一产物可复算 | 同上，比对 `gate-result.phase1.json` | 我产出 SHA-256 `0ce0cff3…d512ca` = 交付件 SHA-256，`Compare-Object` 差异 **0 行** | 一致 | PASS |
| 4 | 真实 N/C/U | `P2_RELEASE_NCU_OUT=.tmp-t4review-isolated/gate-real-ncu.json python docs/.../wire_real_ncu.py` | **exit 4**；`decision=pending`；`counts={pass:23,blocked:0,pending:13,observed:3}`（39 行） | 一致 | PASS |
| 5 | 真实 N/C/U 产物可复算 | 同上，比对 `gate-result.real-ncu.json` | 仅 `inputs_sha256` 一行不同（临时目录路径），其余逐行相同，字节数同为 34186 | 一致 | PASS |
| 6 | v3 `SHA256SUMS` | `python .tmp-t4review-isolated/probe_hashes.py` | 17 行全命中，`mismatch=0 missing=0`；`SHA256SUMS` 自身 `746fa663…c55b01` | 一致 | PASS |
| 7 | 四档 | 同上 + 独立重数 `manifest.json.cases[].adopt` | `ADOPTED` N7/C2/U9；`ADOPTED_WITH_BINDING_PROOF` N1/C4/U1；`FAIL` 0；`UNKNOWN` 0 | 一致 | PASS |
| 8 | 两行 tally | `inspect_gate.py` | `tallies.unconditional`（observed，N7/8·C2/6·U9/10）与 `tallies.formal`（pass，N8/8·C6/6·U10/10）都在，label 各自写明 | 一致 | PASS |
| 9 | 6 条证明档 `trace_integrity` | `probe_ncu_tiers.py` | 6 条（N01/C01/C02/U01/C05/C06）全为 `status=fail`，`mechanical_gate_failures` 逐条留痕；"被写成 pass 的证明档" 计数 **0** | 一致 | PASS |
| 10 | D-004 代码 | 读 `gate.py:1620-1727` + `git diff HEAD -- gate.py` | 候选集合 = `retrieved.unit_ids` ∪ `evidence[].unit_id`；三个拒绝分支相对 HEAD **零改动**（diff 只有新增块） | 一致 | PASS |
| 11 | D-004 自写负例 | `probe_d004.py` | 见 §2 | 一致 | PASS |
| 12 | D-005 重算 | `probe_binding.py` | R1 27→0、R4 2→0、R2 2→0（`rag_meta.revision` 由我自行 sqlite 只读读出 12/4/6） | **部分不一致**（R2 改写行数） | FAIL |
| 13 | D-005 伪造负例 | `probe_binding.py` | 6 条全部被拒，原因码固定 | 一致 | PASS |
| 14 | D-005 双披露 | `inspect_gate.py` / `probe_u_binding.py` | R1/R4 行内 `original_mechanical`+`corrected_view` 都在；**R2 无行** | **不一致** | FAIL |
| 15 | B0 回归 | `python -m mktkb.evaluation.cli baseline p2-admit --run var/eval/runs/p2-t209-b0-20261120-02/p2-run --gate-config docs/evaluation/gate_v0_3_approved.json --out .tmp-t4review-isolated/b0-admit-review.json` | **exit 0**；`evidence_sha256=2226fa20…cea8b5d`；`trace_integrity/citation_required/exact_value_contract=pass`；`hard_failures=[]`；`p2_release_status=blocked_pending_n_c_u_h2_evidence` | 一致 | PASS |
| 16 | `hard_gate_min_sample.unmet` | `inspect_gate.py` | 固定行存在：`pending` / `["hard_gate_min_sample_unmet"]` / `{suite:"update_delete", evaluated:1, required:10}`；`u.hard_gates` 同步 pending；`hard_gates` 汇总 pending | 一致 | PASS |
| 17 | H2 行状态 | `inspect_gate.py` | 10 条 H2 行全部 `pending` + `PENDING-TASK2`；无任何 pass/blocked 伪造 | 一致 | PASS |
| 18 | 冻结候选摘要清单 | `probe_hashes.py`（跑完所有命令后**再跑一次**） | 21/21 命中，`mismatch=0 missing=0`；两次一致 | 一致 | PASS |
| 19 | 定向回归 | 见 §9.1 | 27 / 9 / 15 / 21 / 84 / 32 passed，全部 exit 0 | 一致 | PASS |
| 20 | 零真实请求 | 自建 `sitecustomize.py` socket 闸门 | 5 次带闸门运行 `EXTERNAL=0`（§9.2） | 一致 | PASS |
| 21 | 原件保护 | `git diff --stat -- docs/evaluation`；mtime | `docs/evaluation` 相对索引 **0 改动**（其中文件均为未跟踪的既有新增）；任务 1/3 交付 mtime 早于本窗口 | 一致 | PASS |
| 22 | 我自写 3 条新负例 | `probe_more_negatives.py` | 全部被拒，固定原因码见 §7 | 一致 | PASS |

## 2. D-004 独立验证

### 2.1 代码（`gate.py` 现版本 `e04990db…`，148546 B）

`_gate_citation_required`（1620–1727）里候选接地集合先取 `outcome.retrieved[].unit_ids`，再由 D-004 追加 `outcome.evidence[].unit_id`（1696–1704）。三个拒绝分支在 `git diff HEAD -- gate.py` 中**完全没有出现**，即相对 HEAD 逐字未变：

* `citation_missing`（无 citations）1671；
* `citation_not_unit_level`（有 citation 但无 `unit_ids`）1684，且**在接地集合构造之前**判定，不会被 D-004 绕过；
* `citation_not_in_evidence`（`cited - evidence_units` 非空）1714，`evidence` 里原样列出越界 `unit_ids`。

`git diff HEAD` 中 `gate.py` 共 20 行新增，其中 9 行是 D-004 块，另 11 行是**前序未提交工作**（`P2_APPROVED_GATE_CONFIG_PATH` 常量与 `write_gate_proposal` 保护），与 D-004 无关；报告 §13 只声明本轮 D-004 改动，与本窗口观察不冲突。

### 2.2 自写负例（`probe_d004.py`，均实跑）

```
neg1（引用单元既不在 evidence 也不在 retrieved）:
  citation_required=fail  failures=['citation_not_in_evidence']  hard=True
  evidence={'unit_ids': ['11111111-...-111111111111'], 'evidence_units': 1}
neg2（citation 无 unit_ids）:
  citation_required=fail  failures=['citation_not_unit_level']  hard=True
  evidence={'citation_index': [0]}
neg3（完全无 citations，补验第一个分支）:
  citation_required=fail  failures=['citation_missing']  hard=True
```

### 2.3 `case_rows` 依赖（缺省方向实测为更严）

```
pos(with case_rows):    citation_required=pass  failures=[]
pos(no case_rows):      citation_required=fail  failures=['citation_not_in_evidence']
                        evidence={'unit_ids': ['11111111-...'], 'evidence_units': 0}
```

代码侧同向：`p2_scoring.outcome_to_dict()`（594–625）**不输出 `evidence` 键**，`build_gate_rows(case_rows=None)` 时 `outcome.evidence` 恒为空 → 候选集合退化回 `retrieved` → **更早 fail，不会误放行**。报告 §16.1 的方向性声明成立。

### 2.4 真实 U01 重跑（fail → pass）

`probe_u01.py`，R2 全题重算，approved 配置，`case_rows` 有无对照：

```
case_rows=None: citation_required=fail   citation_not_in_evidence
                case=U01 evidence={'unit_ids':['072d28f2-b403-4af3-9fe9-31b9e8714dbf'],'evidence_units':0}
case_rows=raw : citation_required=pass   failures=[]
U01 原始 product: retrieved=[]、evidence=[{unit_id: 072d28f2-...-31b9e8714dbf}]、sources=[072d28f2-...]
```

与报告 §13「R2 citation_required：fail → pass」一致，且我另取 `outcome.retrieved=[]`、`outcome.evidence` 有该单元作为"候选集合变动"的直接证据。

## 3. D-005 独立验证

### 3.1 加载路径确实从原始工件重算（不是信任调用方）

`p2_release_binding.py`：

* `read_rag_revision()`（92–111）用 `sqlite3.connect("file:...?mode=ro", uri=True)` 读 `rag_meta.revision`；文件缺失/读不出/非整数分别给固定原因码。
* `product_turn_revisions()`（114–128）从 `cases.jsonl` 逐轮回读 `product.revision`。
* `validate_binding_proof()`（215–287）先做 `run_id`/规则/schema 校验，再把 `recorded`、`attested`、`db_sha256`、`cases_sha256`、`per_turn`、`values_sha256`、`precedent[].sha256` 逐项与 `rebuilt` 比对，最后 `declared != rebuilt` 直接拒（`fields` 列出差异）。**没有任何一处采信调用方自报布尔**。

### 3.2 我用原库独立复算（`probe_binding.py`）

我不用其模块函数读版本，而是自己开 sqlite 读 `rag_meta.revision`，再让门禁双跑：

| run | manifest `index_revision`（recorded） | `rag_meta.revision`（我自己读 / 模块读） | 原始 `version_binding` 失败 | 修正视图失败 | 改写 trace 行 | 轮次/逐轮 product revision |
| --- | --- | --- | --- | --- | --- | --- |
| `p2-t207-r1-20261111-01` | 11 | 12 / 12 | **27**（C01,C02,N01,Q01–Q24） | **0** | 25 | 52 轮，全 11 |
| `p2-t207-r2-20261111-01` | 3 | 4 / 4 | **2**（C05,U01） | **0** | **0**（报告写 1） | 2 轮，全 3 |
| `p2-t207-r4-20261111-01` | 5 | 6 / 6 | **2**（C05,C06） | **0** | 1 | 3 轮，全 5 |

原始失败数 **27 / 2 / 2** 与修正视图 **0** 全部复现；**R2 的改写行数报告写 1、实测 0**（`D:\mktkb-p2-run\t207\R2\data\observability\qa-traces.sqlite3` 里 `traces.index_revision` 只有 `'4'` 共 2 行，`update ... where index_revision='3'` 命中 0 行）。

### 3.3 伪造负例（6 条，全部被拒）

| 负例 | 结果 |
| --- | --- |
| N1 伪造 `attested_index_revision`（4→6，并把 `rag_source.read_value` 一起改成 6，自洽） | `release_binding_attestation_invalid`，`{declared:6, actual:4}` |
| N2 把 R1 证明**原样**套到 R2 | `release_identity_mismatch`（绑定证明属于另一个 run） |
| N3 把 R1 证明的 `run_id` 改成 R2（其余保留 R1 值） | `release_binding_attestation_invalid`（`attested` 12 ≠ 4） |
| N4 `attested == recorded`（无修正却称已修正） | `release_version_mismatch` |
| N5 抹掉原始机械结果（只给修正后） | `release_evidence_missing` |
| N6 修正视图仍有失败 | `release_binding_attestation_invalid` |

题面要求的 2 条（伪造 `attested`、A 证明套 B run）均被拒且原因码固定。

### 3.4 双披露：R1/R4 满足，R2 不满足（缺陷）

`gate-result.real-ncu.json` 中只有 **2 条** `binding.*` 行：

```
binding.p2-t207-r1-20261111-01  pass  rewritten=25  original=27  corrected=0
binding.p2-t207-r4-20261111-01  pass  rewritten=1   original=2   corrected=0
```

**没有 `binding.p2-t207-r2-20261111-01`**。我直接调用门禁用的同一个函数，得到被丢弃的那一行：

```
assess_binding(u_real) -> {"row_id":"binding.p2-t207-r2-20261111-01",
  "decision":"blocked","reasons":["release_inputs_invalid"],
  "detail":{"cause":"rewritten_trace_rows 必须是不小于 1 的整数"}}
included in gate rows? False
```

根因（`p2_release_gate.py` 273–310）：`_assess_u` 先 `rows.append(binding_row)`（296–297），随后 **296 行那句被 304 行 `rows = list(assess_u(...))` 整个覆盖**，U run 的绑定行（含它的阻断结论）被丢弃——死赋值。
连带后果：

1. `validate_binding_proof` 要求 `rewritten_trace_rows >= 1`，而 R2 实测 0 → 该证明按现契约**不成立**，报告"三份 run 的 binding 全 pass"不成立（applicability 是三行，binding 只有两行）。
2. 若这一行被保留，总门应为 **`blocked`**（任一 blocked → blocked），而不是现在输出的 `pending`。**23 pass / 0 blocked 的头部计数掩盖了一条 blocked 行。**
3. fail-open：我把 `u.real.binding_proof` 改成伪证（`attested` 4→6 且 `read_value` 同步、更新 sha256），重跑门禁仍是 `pending / 23 pass / 0 blocked`，`binding.*` 行仍是 r1/r4 两条——**U01 的绑定证明可被随意篡改而不被发现**。这正是 D-005 唯一要保护的用例。

另：证明文件本身（`binding-proofs/binding-p2-t207-r2-....json`）是双披露的（`original_binding_failures=[C05,U01]`、`corrected=[]`、`rewritten=0`）；缺失的只是**门禁输出行**。

## 4. B0 回归实测

```powershell
.\.venv\Scripts\python.exe -m mktkb.evaluation.cli baseline p2-admit `
  --run var\eval\runs\p2-t209-b0-20261120-02\p2-run `
  --gate-config docs\evaluation\gate_v0_3_approved.json `
  --out .tmp-t4review-isolated\b0-admit-review.json
```

* **exit 0**
* `evidence_sha256 = 2226fa208aec7db84ab69e5f7a068e94322414d38b90c14399979b96fcea8b5d`（与题面给定值、与报告 §13 **逐字符相同**）
* `gate_status = {trace_integrity: pass, citation_required: pass, exact_value_contract: pass, 其余 5 项 not_applicable}`；`hard_failures = []`；`exit_code = 0`；`unknown_count = 0`；`min_sample = 32`；`scored_count = 40`
* `b0 = {planned:40, executed:40, passed:38, ocr_planned:8, ocr_executed:8, ocr_passed:7, exact_planned:24, exact_passed:24}`
* `p2_release_status = blocked_pending_n_c_u_h2_evidence`；`p2_release_allowed = false`
* 两次独立运行（带/不带网络闸门）输出**字节相同**（SHA-256 `67652aad…c757b`）。

## 5. `hard_gate_min_sample.unmet` 实际输出

```json
{"row_id":"hard_gate_min_sample.unmet","decision":"pending",
 "reasons":["hard_gate_min_sample_unmet"],
 "detail":{"marker":"PENDING-MASTER-DECISION",
  "evidence":{"suite":"update_delete","evaluated":1,"required":10,
   "approved_config":"docs/evaluation/gate_v0_3_approved.json", ...}}}
```

* `u.hard_gates`：`pending`，`reasons=["release_sample_below_min"]`，`detail.evidence={min_sample:10, expected_min_sample:10, scored_count:1}`。
* `hard_gates` 汇总：`pending`，`reasons=["release_sample_below_min"]`，`detail={pending_sources:["update_delete"], cause:"u_sample_scope"}` —— **既不是 pass 也不是 blocked**。
* 批准配置侧一致：`hard_gate_min_sample.update_delete = 10`（`docs/evaluation/gate_v0_3_approved.json`）。

## 6. 我自写的 3 条新负例（`probe_more_negatives.py`）

基线：合成齐备输入 → `decision=pass, counts={pass:32,blocked:0,pending:0,observed:2}`。

| # | 我构造的负例 | 结果 |
| --- | --- | --- |
| N7 | 伪造 B0 注册表条目：把 `var/eval/baselines/7981d4afc2d1` 复制到隔离目录、改 `baseline.json` 的 `run_id` 并**把摘要改成自洽新值**，`b0.baseline_root` 指向副本 | `blocked` / **`release_baseline_unregistered`**（"基线登记目录不是规范登记处"） |
| N7b | 同版本错摘要：`b0.baseline_sha256` 换成 admission 摘要 | `blocked` / **`release_digest_mismatch`**（`{declared:07d2b1e3…, actual:09cf747c…}`） |
| N8 | H2 卡顺序打乱（`base_b0` ↔ `base_b0_plus_v01`） | `blocked` / **`release_identity_mismatch`**（`h2.cards 顺序/场景 id 与冻结顺序不符`，`{index:0, expected:"base_b0", observed:"base_b0_plus_v01"}`） |
| N9 | 把 `ADOPTED_WITH_BINDING_PROOF` **折成无条件 `ADOPTED`**（复制 NCU v3 目录、改 6 条 case 的 `adopt`、把 tallies 改成 8/6/10 与 0/0/0、**重算整份 `SHA256SUMS`** 让摘要自洽） | `blocked` / **`release_identity_mismatch`**，`cause=manifest_cross_check_failed`，逐题 `{"case_id":"N01","tier":"ADOPTED","mechanical":1,"failing":["trace_integrity"]}` … |

N9 特别值得记：即使把 SHA 清单重算到自洽，交叉核对仍按"机械失败非空 + 声明无条件档"判为篡改，说明四档不是靠自报摘要通过的。

## 7. 冻结候选摘要清单 drift

`probe_hashes.py` 解析 `report.md`「冻结候选摘要清单」表，逐项实算 SHA-256 与字节数：

* **21 行，drift = 0**（mismatch 0 / missing 0）。
* 在所有命令跑完之后**再跑一次**，仍 21/21 命中 → 本窗口（以及交付方）没有使交付件漂移。
* 抽查身份：`gate.py e04990db52d72c06dcd4e87fea8f80644171fd5b686810bc0fa6aa3fa8c831b7`（148546 B）、`p2_release_gate.py c32c727a…`、`test_p2_gate.py 712fb0c3…`、`gate-result.real-ncu.json 0fcb7b01…`（34186 B）。

## 8. H2 行状态

`gate-result.real-ncu.json` 中 H2 相关共 10 行：`h2`、`h2.composition`、`h2.source_proof`、`h2.coverage`、`h2.strata`、`h2.quality`、`h2.hard_failures`、`h2.required_axes`、`h2.non_required_axes`、`h2.card_verified` —— **全部 `pending` + `reasons=["release_pending_input"]` + `detail.marker="PENDING-TASK2"`**。`pending` 段 `{"h2":"PENDING-TASK2"}` 同步。未发现任何 H2 行被伪造成 pass 或 blocked 后停手；模板结果（28 行）中 H2 同样是 10 行 pending。

## 9. 回归与零请求

### 9.1 定向回归（全部带网络闸门，`-p no:cacheprovider`，`PYTHONDONTWRITEBYTECODE=1`）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `pytest backend/tests/evaluation/test_p2_gate.py -q` | **0** | 27 passed（含 D-004 三条） |
| `pytest backend/tests/evaluation/test_p2_score_run.py -q` | **0** | 9 passed |
| `pytest backend/tests/evaluation/test_diff_release_gate.py -q` | **0** | 15 passed |
| `pytest backend/tests/evaluation/test_baseline_portability.py -q` | **0** | 21 passed（题面给的 `backend/tests/unit/...` 路径不存在，与报告 §6 第 4 条一致） |
| `pytest backend/tests/evaluation/test_p2_holdout_scenarios.py -q` | **0** | 84 passed |
| `pytest ...test_p2_release_gate_{fixtures,positive,negative,real_ncu}.py -q` | **0** | **32 passed**（10+20+2；`fixtures.py` 单独跑 exit 5 = 该文件只有 helper，无 test，属正常） |

被验收方报的 21+ 条负例集中在 `test_p2_release_gate_negative.py`（20 passed，覆盖报告 §4.2 的 #1–#21）与 `test_p2_gate.py` 的 3 条 D-004 用例，**均独立复跑通过**；报告 §4.2 的 #22–#24 在 `test_p2_gate.py` 内。

### 9.2 零真实请求证据

自建 `.tmp-t4review-isolated/netgate/sitecustomize.py`（经 `PYTHONPATH` 在解释器启动时接管 `socket.connect/connect_ex/sendto/create_connection/getaddrinfo`；非回环目标直接 `PermissionError` 并计数，退出时落盘 JSON）：

| 带闸门运行 | EXTERNAL | LOOPBACK |
| --- | --- | --- |
| `wire_real_ncu.py`（真实 N/C/U） | **0** | 0 |
| `baseline p2-admit`（B0 回归） | **0** | 0 |
| 5 个定向回归文件 | **0** | 0 |
| 4 个 `test_p2_release_gate_*` 文件 | **0** | 0 |
| `probe_cli_pass.py`（合成通过 + 负例） | **0** | 0 |

唯一出现的回环连接是 `test_p2_holdout_scenarios.py` 内 3 次 `127.0.0.1`（本地夹具，非外部）；全部运行 `EXTERNAL=0`。
另：仓库自带 `backend/tests/acceptance/support/netguard.py::t09_network_guard` 也被 `test_p2_release_gate_*` 用作 fixture，与我的闸门互为独立证据。

### 9.3 原件保护

* `git diff --stat -- docs/evaluation` → **0 行**；`git diff --name-only -- docs/evaluation` → 空。该目录下出现的都是**未跟踪的既有新增**（`gate_v0_3_approved.json` 等，前序任务产物），不是本任务修改。
* 任务 3 交付：`NCU-RELEASE-EVIDENCE` 17/17 SHA 命中（§1 第 6 行）；mtime 最新为 `2026-11-21 00:02:20`，早于本窗口开始（00:08）。
* 任务 1 交付：`H2-DOC-REBUILD` 5 个文件，其中 `review.md` mtime `2026-11-21 0:09:24` 属**另一只读窗口 t1-review** 的写入（题面已说明其在场），其余文件早于本窗口；本窗口未写该目录。
* `backend/src` 的 ` M` 清单与接手时一致（本窗口未触碰任何源码/测试）：我只读取，未写入。

## 10. 我不认同被验收方的地方

1. **「三份 run 的 applicability/binding 全 pass」（报告 §6.4、§14）不成立。**
   `applicability` 确有 3 行；`binding` 只有 2 行（R1、R4）。R2（U01 所在 run）的绑定行被 `_assess_u` 丢弃，而它自己算出的是 `blocked / release_inputs_invalid`。
2. **头部计数 `23 pass / 0 blocked` 掩盖了一条 blocked 行**，总门因此停在 `pending` 而非 `blocked`。这不是口径选择，是死赋值（296 行 append 被 304 行覆盖）。
3. **报告 §9.4 表里 R2「改写 trace 行 = 1」与实测不符（实测 0）。**
   实测依据：R2 的 `traces` 表只有 2 行且 `index_revision` 均为 `'4'`（RAG 计数），`update ... where index_revision='3'`（recorded=3）命中 0 行。这也解释了为什么该证明过不了 `rewritten_trace_rows >= 1`。
4. **契约与证据的自相矛盾未被披露**：`validate_binding_proof` 要求 `rewritten>=1`，而 R2 的自然结果是 0；两者不能同时成立。正确做法要么放宽该字段（"trace 已全部为 attested 值，无需改写"也算证明成立），要么明确 U01 的绑定证据不成立并如实阻断——**不能靠丢行让它看起来通过**。
5. **fail-open**：伪造 `u.real.binding_proof` 后门禁输出完全不变，说明 U01 的 D-005 证据当前没有任何实际约束力。这与 D-005「必须重算校验、不得靠自报」的要求方向相反。
6. 次要：`docs/evaluation/gate_v0_3_approved.json` 处于**未跟踪**状态（前序任务遗留）。它被本门禁当作批准配置钉死，冻结送审时若只按 git 提交取件会漏掉这份输入，建议经理在冻结清单里显式标注"未跟踪但必须入包"。

以上 1–5 是同一根因的两面（丢行 + 该行本身为 blocked），修法很小（`rows.extend(assess_u(...))` + 处理 R2 的 `rewritten=0` 契约），但**结论级影响明确**：当前输出不能作为"U01 绑定已通过"的证据。

## 11. `NOT-VERIFIED` 清单

| 项 | 原因 |
| --- | --- |
| 报告 §13「D-004 前工作树 `10235099…`（147965 B）」 | 该中间态**未提交、git 不可重建**，无法独立复核；只能确认现状 `e04990db…` 与 HEAD `7e54fbf6…` 的差异（`git diff HEAD`）与 D-004 描述一致 |
| 报告 §16.2 同一行的"由改后文件精确反推" | 同上，反推过程不可验证 |
| R1/R2/R4 的 6 个绑定字段"全等"（D-002 依据） | 本窗口只复算了 `index_revision` 与逐轮 product revision；其余 5 个字段（`dataset_version`/`pipeline_version`/`config_hash`/`manifest_sha256`/`mode`）未逐条对表 |
| T900 层（发布决定、账本、Ragas 辅助诊断） | 不在任务 4 验收范围，未验 |
| H2 真实四场景卡/组合/来源证明 | 任务 2 未交付（`PENDING-TASK2`），只验了"结构+三视图+负例"，未对真实 H2 结论作断言 |
| `p2_release_inputs.py` 钉死的 B0 三摘要常量与登记处的长期一致性 | 只验了当前值命中；"重登记需改代码"的设计后果未做破坏性验证 |
| `test_p2_release_gate_fixtures.py` 作为独立文件的可执行性 | exit 5（无 test 收集），属预期；未把其 helper 当测试计入通过数 |
| 工作区其余 470+ 条既有未提交改动 | 按题面"原样保留"，未逐条审计；只核了被禁止改动的四类路径 |

---

### 附：本窗口实际写入的路径

* `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/review.md`（本文件）
* `.tmp-t4review-isolated/`（探针、日志、临时输出、复制件；验收结束后仅清理此目录）

`git status --short` 中属于本窗口的条目：`?? docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/`（该目录整体未跟踪，内含本文件与交付件）、`?? .tmp-t4review-isolated/`。除此之外没有新增/修改任何文件。

## 12. 复验 T4-R1（返工后复验，2026-11-21 00:27–00:5x）

同一窗口复验，未采信返工自述；全部结论来自本轮实跑。零真实请求（`EXTERNAL=0`），未 commit/push，未覆盖交付件（`wire_real_ncu.py` 输出写到本窗口隔离目录）。

### 12.0 复验结论

**PASS-WITH-RESERVATIONS** —— 上轮 4 条 FAIL 逐条**已闭**，且新不变量、零改写契约、U01 证明约束都用我自造的负例独立验证过（不是靠跑他们的测试）。保留项：① 总门仍 `pending`（H2 `PENDING-TASK2` + `hard_gate_min_sample.unmet`），**H2 未接线意味着总判定尚未完成**，本包只证明"门禁机制正确且不再 fail-open"，不是"P2 可发布"；② 返工报告 §4.1/§4.2 的计数（30/20）未随返工更新，且"新增 5 条用例"与实际 +3 不符；③ 少量口径细节见 §12.9。

### 12.1 上轮 4 个 FAIL 项：逐条对账

| # | 上轮 FAIL 项 | 本轮实测 | 是否已闭 |
| --- | --- | --- | --- |
| 1 | `_assess_u` 覆盖 `rows`，R2 的 `binding.<run_id>` 行被丢弃；"三份 run binding 全 pass"不成立 | `p2_release_gate.py:305` 已是 `rows.extend(...)`；实跑输出 **3 条 `binding.*` 行**（R1/R2/R4 全 pass）+ 3 条 `applicability.*` 行；无 `rows.completeness` 行 | **已闭** |
| 2 | 被丢弃的那行真值为 `blocked / release_inputs_invalid`（`rewritten_trace_rows>=1` 错误契约），总门被从 blocked 抬成 pending | R2 现为 **pass**：`rewritten=0 / total=2 / zero_rewrite_legal=true`、`rows_not_at_attested=0`、`post_update=0`；我自造的 4 种篡改都使总门 **blocked**（见 §12.3/§12.4） | **已闭** |
| 3 | 报告 §9.4 表里 R2「改写 trace 行 = 1」与原库实测 0 不符 | 我用独立 SQL 复核：R2 `traces` 2 行全在 `index_revision='4'`（=attested），`not_at_attested=0` → **改写 0**；新报告 §9.4 已改为 0 并注明"零改写合法" | **已闭** |
| 4 | U01 的 D-005 证据 fail-open：伪造/删除证明后输出不变 | 伪造 → `blocked / release_binding_attestation_invalid`；删除 → `blocked / release_binding_proof_missing`；套用 R1 证明 → `blocked / release_identity_mismatch`；去掉 `rag_db`（trace 库仍在）→ `blocked / release_binding_proof_missing`。四种都从 24/0/13/3 变成 **23 pass / 1 blocked** | **已闭** |

补充：报告新增 §「返工 T4-R1」逐条披露了这 4 条缺陷与改动点，与本轮实测吻合（除 §12.9 的计数问题）。

### 12.2 新不变量（`release_rows_incomplete`）正反例

| 场景 | 构造方式 | 结果 |
| --- | --- | --- |
| **正例·不误伤** | 正常输入（真实 N/C/U） | 3 对行齐全，**无** `rows.completeness` 行，`release_rows_incomplete` 不出现，总门 `pending` |
| 正例·待交付 | `inputs.template.json`（public/u/h2 全 pending） | 28 行，**无** completeness 行，exit 4 |
| 正例·合成齐备 | 合成完整输入 | 37 行，**无** completeness 行，`decision=pass`、`pass=32`、`observed=5`（3 条 `binding.*` 因"无 rag_db 且无 trace 库"记 observed，属新契约预期） |
| **反例 A·丢 binding 行** | monkeypatch 让 `assess_binding` 对 U run 返回 `(None, None)`（复刻上轮 bug） | `blocked`；`rows.completeness` = `{"cause":"run_rows_missing","evidence":{"run_id":"p2-t207-r2-…","missing":["binding.p2-t207-r2-…"]}}`，原因码 `release_rows_incomplete` |
| **反例 B·丢 applicability 行** | monkeypatch 过滤掉 U run 的 `applicability.*` 行 | `blocked`；同一固定行，`missing=["applicability.p2-t207-r2-…"]`，`release_rows_incomplete` |
| 复原 | 撤掉 monkeypatch | 回到 `pending`、24/0/13/3，无 completeness 行（不残留状态） |

结论：不变量既**不误伤**齐全输入，也能**抓住**任意一侧缺行，且失败方向是 `blocked`（不是 pending）。

### 12.3 `zero_rewrite_legal` 不是自报：三 run 独立读数

我自己开 trace 库（`select count(*) ... where index_revision != ?` 等），与证明里的 `gate_replay` 逐项比对：

| run | recorded / attested | 我的 SQL（total / at_attested / at_recorded / 第三值 / not_at_attested） | 证明（total / rewritten / not_at_attested / post_update） | 一致 | zero_rewrite_legal |
| --- | --- | --- | --- | --- | --- |
| R1 | 11 / 12 | 52 / 27 / 25 / 0 / 25 | 52 / 25 / 25 / 0 | ✅ | false |
| R2 | 3 / 4 | 2 / 2 / 0 / 0 / **0** | 2 / **0** / 0 / 0 | ✅ | **true** |
| R4 | 5 / 6 | 3 / 2 / 1 / 0 / 1 | 3 / 1 / 1 / 0 | ✅ | false |

伪造负例（全部被拒）：

```
F1 R1 声称 rewritten=0（实际 25）      -> release_binding_attestation_invalid（declared != rebuilt，fields=[gate_replay]）
F2 R2 声称 rewritten=1（实际 0）      -> release_binding_attestation_invalid
F3 R2 rewritten=0 但 not_at_attested=1 -> release_binding_attestation_invalid
   （detail {"rewritten":0,"not_at_attested":1}，即"改写行数与不在 attested 上的行数不符"）
第三值负例：把 R2 trace 库复制后改 1 行为 '99'
   -> release_binding_attestation_invalid（cause 含"第三种版本"，detail {rewritten:0, not_at_attested_before:1, not_at_attested_after:1}）
```

即：零改写必须由"库里本来就没有非 attested 行"证明，伪造成 0 会在重算时暴露；出现第三版本值直接拒。

### 12.4 全量实跑（隔离目录，不覆盖交付件）

```
P2_RELEASE_NCU_OUT=.tmp-t4review-isolated/gate-real-ncu.json python .../wire_real_ncu.py
-> exit 4；decision=pending；counts={pass:24, blocked:0, pending:13, observed:3}；rows=40
-> binding: r1 pass / r4 pass / r2 pass（rewritten 25 / 1 / 0）
-> applicability: r1/r4/r2 三行全 pass
-> 两行 tally: tallies.unconditional（observed，N7/8·C2/6·U9/10）、tallies.formal（pass，N8/8·C6/6·U10/10）
-> evidence_manifest: pass，SHA256SUMS verified=17 / mismatch=0 / missing=0
```

与我 0.2 版交付件逐行比对：**只有 `inputs_sha256` 一行不同**（临时目录路径），其余行相同 → 交付件可复算。

### 12.5 B0 回归

```
.\.venv\Scripts\python.exe -m mktkb.evaluation.cli baseline p2-admit `
  --run var\eval\runs\p2-t209-b0-20261120-02\p2-run `
  --gate-config docs\evaluation\gate_v0_3_approved.json --out .tmp-t4review-isolated\b0-admit.json
```

**exit 0**；`evidence_sha256 = 2226fa208aec7db84ab69e5f7a068e94322414d38b90c14399979b96fcea8b5d`（不变）；
`trace_integrity / citation_required / exact_value_contract = pass`，其余 5 项 `not_applicable`；
`hard_failures=[]`、`exit_code=0`、`unknown_count=0`、`min_sample=32`、`scored_count=40`；
`40/40 执行、38/40 正确、24/24 精确、OCR 8/8（7 通过）`；`p2_release_status=blocked_pending_n_c_u_h2_evidence`。

### 12.6 测试

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `pytest test_p2_release_gate_{fixtures,positive,negative,real_ncu}.py -q`（合并） | **0** | **35 passed**（10 + 22 + 3；`fixtures.py` 单独跑 exit 5 = 只有 helper，属预期） |
| `pytest test_p2_gate.py -q` | 0 | 27 passed |
| `pytest test_p2_score_run.py -q` | 0 | 9 passed |
| `pytest test_diff_release_gate.py -q` | 0 | 15 passed |
| `pytest test_baseline_portability.py -q` | 0 | 21 passed |
| `pytest test_p2_holdout_scenarios.py -q` | 0 | 84 passed |

三条新增用例我读过并确认**非空断言**：`test_zero_rewrite_claim_without_legal_zero_is_rejected` 先断言原证明 `rewritten>=1` 再改 0 并期望 blocked；`test_missing_binding_row_is_caught_by_completeness_invariant` 用 monkeypatch 丢行并断言 `rows.completeness`；`test_u01_binding_proof_forgery_delete_and_cross_run_are_rejected` 用真实工件三连断言（本机有库，**未 skip**，实跑 3 passed）。

### 12.7 冻结候选清单（22 项）

`probe_hashes2.py` 解析表格逐项实算：**22 行，mismatch 0 / missing 0**（跑完所有命令后再验一次仍 0）。
新增行在位：`docs/evaluation/gate_v0_3_approved.json` = `b1094cc726230be2ec22ec811d34a948ea4a2fe03aab2c0fcc4f20c99764d961`，**5785 B**，与表一致；
`git ls-files --error-unmatch` **exit 1 → 确认该文件未跟踪**；报告 §冻结候选清单下方确有"未跟踪，冻结时必须显式纳入（`git add -f` 或按表取件）"的说明。
其余身份：`p2_release_gate.py 89d8b44b…`（25682 B）、`p2_release_binding.py 0aa8a1ca…`（26867 B）、`p2_release_model.py 3aab5f06…`（14173 B）、`gate-result.real-ncu.json 576be734…`（38015 B）；`gate.py` 仍 `e04990db…`（返工未碰）。
NCU v3 `SHA256SUMS` 17 行仍 17/17 命中。

### 12.8 `min_sample` / `hard_gates` / H2 状态（未变 pass）

* `hard_gate_min_sample.unmet`：**pending**，`["hard_gate_min_sample_unmet"]`，`{suite:"update_delete", evaluated:1, required:10}`，`marker=PENDING-MASTER-DECISION`。
* `u.hard_gates`：**pending**（`release_sample_below_min`）。
* `hard_gates` 汇总：**pending**，`{pending_sources:["update_delete"], cause:"u_sample_scope"}` —— 未变 pass，也未改 blocked。
* H2 十行：全部 `pending` + `PENDING-TASK2`（`h2`/`composition`/`source_proof`/`coverage`/`strata`/`quality`/`hard_failures`/`required_axes`/`non_required_axes`/`card_verified`）。

**H2 未接线 = 总判定未完成**：`technical_gate=pending`、`release_allowed=false`、`owner_release_decision=not_decided`。本包当前只证明"门禁机制正确、无 fail-open"，**不构成 P2 通过或可发布**；任务 2 的四张 v0.2 卡 + 组合 + 同批来源证明到位前，总门不可能 pass。

### 12.9 仍存在的不一致 / 保留项

1. **报告 §4.1「30 passed」与 §4.2「20 passed」未更新**：实测现在是 **35**（§0、§返工已写 35）与 **22**（negative 文件）。属文档内部计数未同步。
2. **"新增 5 条 T4-R1 用例"与实测不符**：上一轮我实测 32 passed（10+20+2），本轮 35（10+22+3）→ **实际新增 3 条**（2 条 negative + 1 条 real_ncu）。"5 条"疑似沿用旧报告的 30 计数。
3. `rows.completeness` 的 `row_id` 对多个 run 缺失时会**重复同 id**（每 run 一行），行去重/展示口径未定义；当前单 run 缺失场景无影响，建议后续若要多 run 汇总时再规范。
4. `zero_rewrite_legal` 是**派生布尔**（`rewritten==0`），不是独立证据；它的可信度来自同行的 `rows_not_at_attested`/`post_update_not_at_attested` 与加载时重算（我已独立核过），但单看该布尔不能作为证据。
5. 合成齐备用例的 `observed` 由 2 变 5（3 条合成 run 的 `binding.*` 记 observed）。行为符合新契约，但报告 §4.1 未同步说明，读表的人可能以为新增了 3 条观察项含义不明。
6. `H2` 仍为 `PENDING-TASK2`（外部依赖，不计缺陷）；`docs/evaluation/gate_v0_3_approved.json` 仍**未跟踪**（已入清单并标注，冻结时仍需人工确保取件）。

### 12.10 本轮 NOT-VERIFIED

| 项 | 原因 |
| --- | --- |
| 返工前的 `p2_release_gate.py`/`p2_release_binding.py` 旧版本 | 均为未跟踪文件的就地修改，git 不可重建；我以**上一轮实测输出**（报告与日志）作为对照基线 |
| `test_u01_binding_proof_...` 在无历史库机器上的行为 | 本机有 `D:\mktkb-p2-run`，未触发 skip 分支；skip 逻辑只读了代码（`skipif not (RAG_ROOT/"R2").is_dir()`） |
| 真实 H2 聚合结果 | 任务 2 未交付，仍 `PENDING-TASK2` |
| 多 run 同时缺行时 `rows.completeness` 的行去重行为 | 未构造该场景（单 run 缺失已验） |

### 12.11 本轮实际写入 / 清理

* 只写 `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/review.md` 与 `.tmp-t4review-isolated/`（末尾按题面**只清这一个目录**，逐路径 `Remove-Item -LiteralPath`，无通配符）。
* `wire_real_ncu.py` 的输出全部指向隔离目录，**未覆盖** `gate-result.real-ncu.json`（该文件 SHA 已由交付方更新为 `576be734…`，与我复算一致）。
* `git status --short`：472 → 473（新增我的隔离目录）→ 清理后回落到 472；`docs/evaluation` 相对索引 **0 改动**；`gate.py` 仍 `e04990db…`；任务 1 的 `H2-DOC-REBUILD` 五个文件字节数与 mtime **未变**（最新仍是 t1-review 写的 `review.md` 00:09:24）；任务 3 的 NCU 17/17 未变。

## 13. 最终核（H2 接线后，2026-11-21 00:36–01:0x）

同一窗口，未采信返工自述；全部结论来自本轮实跑。零真实请求（7 次带闸门运行 `EXTERNAL=0`），未 commit/push，未覆盖交付件。

### 13.0 最终结论

**PASS-WITH-RESERVATIONS**。

**"技术门禁机制是否已可交给 T900 独立总验收" → 可以，但带保留。**
理由：门禁的判定机制本身已闭环——入口可复算、H2 真实聚合已接入且逐行判定与证据相符、无 fail-open（我自造的哈希互换/丢行/伪造证明全部被阻断）、B0 与五项回归不变、冻结清单 drift 0。保留项**不在机制**，而在：① `technical_gate` 仍 `pending`（唯一实质待办是主人对 U 样本口径的书面裁定），T900 必须把 pending 当"未通过"；② 报告 §0/§6.4/§7 有三处"H2 仍 pending"的过时表述，与其自身 JSON 矛盾；③ D-001 边界使 `card_file_sha256` 在仓内不可复算（只能验"不等于聚合哈希"）；④ C25 历史 1 的落点指错（在任务 2 报告 §5，不在任务 3）。

### 13.1 最终 JSON 复跑一致性

```
P2_RELEASE_NCU_OUT=.tmp-t4review-isolated/gate-final.json python .../wire_real_ncu.py
-> exit 4
```

| 项 | 我复跑 | 交付件 | 一致 |
| --- | --- | --- | --- |
| `decision` | `pending` | `pending` | ✅ |
| `counts` | `{pass:36, blocked:0, pending:3, observed:8}` | 同 | ✅ |
| `reason_codes` | `["hard_gate_min_sample_unmet","release_sample_below_min"]` | 同 | ✅ |
| 行数 / 行 id 集合 | 47 / 全等 | 47 | ✅ |
| 逐行内容差异 | 仅 `inputs` 行（其 `detail.inputs_sha256` 取决于临时目录路径） | — | 可解释 |
| 顶层差异 | 仅 `inputs_sha256`（`dffd345e…` vs `9374f4ac…`） | — | 可解释 |
| `technical_gate` / `release_allowed` / `owner_release_decision` | `pending` / `false` / `not_decided` | 同 | ✅ |

即：**除临时路径派生的一行外，交付件可逐字段复算**（47 行中 46 行完全相同）。

### 13.2 全部非 pass 行（没有第二条独立 pending）

**pending = 3 行，同一条根因**（U 组 run 级样本 1 < 批准 10）：

| 行 | reasons | 说明 |
| --- | --- | --- |
| `u.hard_gates` | `release_sample_below_min` | `PENDING-MASTER-DECISION`，`scored_count=1 / min_sample=10` |
| `hard_gate_min_sample.unmet` | `hard_gate_min_sample_unmet` | 固定行，`{suite:"update_delete", evaluated:1, required:10}` |
| `hard_gates` | `release_sample_below_min` | 汇总行，`{pending_sources:["update_delete"], cause:"u_sample_scope"}` |

* 严格说出现 **2 个原因码字符串**，但二者是同一事实的两种表述；**不存在第二条独立 pending**（无 H2 pending、无 U01 引用 pending）。
* **`blocked = 0` 且没有被掩盖的 blocked**：`reason_codes` 里没有任何 `release_*` 阻断码；我另用 6 种篡改（见 §13.4、§12.3、§13.7）验证过任何真实缺陷都会把总门打到 `blocked`。

**observed = 8 行**（只展示、不参与总门）：`u.overlap`、`u.citation`、`tallies.unconditional`、`h2.identity.original`、`h2.identity.release`、`h2.annotation_metadata`、`h2.non_required_axes`、`h2.card_verified` —— 名称与语义相符，未被抬成 pass。

### 13.3 H2 逐行判定是否与证据相符

| 行 | 判定 | 我的核对依据（自读三个输入文件 + 独立复算） | 相符 |
| --- | --- | --- | --- |
| `h2.aggregate` | pass | 聚合：`total=30 executed=30 passed=29 failed=1 errors=0`；`turns 36/36`、`not_started=0`、`status=complete`、`hard_failures=0`、`required_unknowns=0`、`verified=true`、`threshold_met=true`；strata 汇总回滚 30/29/1/0 | ✅ |
| `h2.cards_index` | pass | `order` = 四场景冻结顺序；`case_count` 12/8/5/5；四个 `card_sha256` 互不相同；每卡 `validate…=pass`、`verified=true`、`hard_failures=0` | ✅ |
| `h2.card.base_b0` / `_plus_v01` / `pre_v05…` / `post_v05…` | pass ×4 | `card_file_sha256` 来自 cards-index、`card_aggregate_sha256` 来自聚合，两者**逐卡不等**；`case_count`/`turns_executed` 与聚合一致（12/14、8/10、5/6、5/6） | ✅ |
| `h2.source_proof` | pass | `batch_binding` 三摘要齐；4 个 `plan_sha256` 互不相同；`status=succeeded`；`derived_card_sha256` 与聚合 `aggregate_sha256` 逐场景相等；`original.gate_config_hash` 全为 `d1097573…`；`derived_scorer.source_sha256` = 我自行按仓库源码算出的 `0bbe9f88…`；`zero_call` 0/0/false；`batch_authority` 文档存在且 SHA 命中 `14d9322e…` | ✅ |
| `h2.coverage` | pass | 30 题 / 36 回合 / `not_started=0` / `complete` | ✅ |
| `h2.strata` | pass | `paraphrase 10, multi_turn 5, negative 5, stale_conflict 5, cross_doc_security 5` | ✅ |
| `h2.quality` | pass | `passed=29 ≥ 24`，`failed=1` | ✅ |
| `h2.hard_failures` | pass | 聚合 `hard_failures=0`，四类 kind 全 0（且聚合校验对非 0 会先拒，属 fail-closed 后的如实行） | ✅ |
| `h2.required_axes` | pass | `required_unknowns=0`、四轴 `violations=0`、每轴 `passed+not_applicable+unknown+violations = 30` | ✅ |
| `h2.identity.original` | **observed** | `gate_config_hash=d1097573…`（批次当时的 unapproved 模板），与发布层分列 | ✅ 如实 |
| `h2.identity.release` | **observed** | `gate_config_hash=7fa6f47a…`（获批配置），注明"不得互相覆盖" | ✅ 如实 |
| `h2.annotation_metadata` | **observed** | 原样展示 `quality_readiness=BLOCKED`、`runtime_axis_evidence_produced=false`、`thresholds_approved=false`、`blocks=["holdout_threshold_unapproved"]` | ✅ 如实 |
| `h2.non_required_axes` | **observed** | `non_required_unknowns=0`、`c25={axes:[],count:0}`、`count_matches=true` | ✅ 如实 |
| `h2.card_verified` | **observed** | `aggregate_verified=true`、`cards_verified=[true,true,true,true]`，只展示不改总门 | ✅ 如实 |

**无异议**：H2 的 17 行判定与其证据一致；没有把 observed 抬成 pass，也没有把 pass 降级掩盖。唯一要注记的是"证据来源"：卡本体依 D-001 留在仓外，`h2.card.*` 验的是**聚合外层**（文件哈希声明 + 聚合哈希 + 逐卡校验结论），不是卡内容本身——这是既定边界，不是本轮的判定错误。

### 13.4 两套哈希：确实是两套，且互换被拒

* **两套值不同**：`cards-index.card_sha256` = `14888a0f…`、`ccc9c12c…`、`15286a96…`、`8e95138d…`；`聚合/proof.derived_card_sha256` = `6fd2a94c…`、`0d993f5d…`、`f8798049…`、`0fb46ecb…`。四对逐对不等。
* **门禁没有混用**：`card_file_sha256` 只出现在 `h2.cards_index` / `h2.card.*` 的文件槽；`card_aggregate_sha256` 只出现在聚合槽，且来源证明的 `derived_card_sha256` 是与**聚合**比对（`_validate_source_proof` line 285），不是与文件哈希比对。
* **互换负例（我自造，非跑其测试）**：

| 变体 | 结果 |
| --- | --- |
| S1：只把 cards-index 里 base_b0 的 `card_sha256` 换成聚合值 `6fd2a94c…` | **blocked**，`release_identity_mismatch`，`h2.cards_index` 行 blocked（cause `card_file_sha_equals_aggregate`） |
| S2：cards-index 与聚合**两侧一致互换**（文件槽 ← 聚合值、聚合槽 ← 文件值） | **blocked**，`release_digest_mismatch`，`h2.aggregate` 行 blocked（cause `source_proof_card_aggregate_mismatch`） |

两种换法都被拒，且拒绝点在正确的层（S1 在索引一致性、S2 在证明↔聚合一致性）。

### 13.5 `# D` 四项元数据：只作注解，未被误判

`annotation.quality_readiness=BLOCKED`、`runtime_axis_evidence_produced=false`、`thresholds_approved=false`、`blocks=["holdout_threshold_unapproved"]`：H2 无一行因此 blocked/pending；唯一相关行 `h2.annotation_metadata` 是 **observed**。
实现侧是"必须等于既定注解值、否则 `aggregate_metadata_unexpected` 拒"——即它防的是**把注解翻成 true**，而不是据此判失败；这与"注解不参与门禁判定"一致（`p2_release_h2_aggregate.py:164-171`，注释写明"不参与判定，阈值由发布层施加"）。

### 13.6 `non_required_unknowns=0` 被接受；C25 历史 1 的落点

* 门禁对 `non_required_unknowns` 只做 `require_int` + 与轴 unknown 合计的回滚校验 + 与来源证明 `c25.count` 相等校验；**代码里没有"预期 1"**，所以 0 被正常接受，未因此判失败（实测 `h2.aggregate`/`h2.non_required_axes` 均正常）。
* `h2.non_required_axes` 的 `c25` 是**派生值** `{axes:[], count:0}`（本批四轴 `required>0`，故无"非必需轴"这一类）；历史 `live unknown=1` 只出现在该行 note 文本里。
* 我用全目录检索确认：**C25 的历史 1 实际单列在任务 2 报告 `H2-REBUILT-CARDS/report.md` §5 的"历史 vs 派生"双列表中**（历史 `unknown/forbidden_source_unmappable = 1`，派生 `not_applicable = 0`）；**任务 3 的 `NCU-RELEASE-EVIDENCE/**` 里没有 C25 条目**。所以门禁 note 写的"由任务 3 单列"是**指错落点**（应为任务 2 报告 §5）——文本瑕疵，不影响判定。

### 13.7 五项保留修复：逐条实测

| 上轮保留项 | 本轮实测 | 是否修好 |
| --- | --- | --- |
| 报告 §4.1 计数 30 → 应 35 | 现文本："**35 passed**；H2 接线后为 38"，我实测 38 | ✅ |
| 报告 §4.2 计数 20 → 应 22 | 现文本："**22 passed**"；我实测 negative 文件 23（H2 接线再加 1），该句仍写 22 | ⚠ 见下 |
| "新增 5 条" → 应 3 | 现文本："**新增 3 个用例函数（覆盖 5 个负例场景；32→35）**" | ✅ |
| `rows.completeness.<run_id>` 多 run 负例 | 我同时丢 R1+R2 的 binding 行：产出 **2 条不同 id** 的 `rows.completeness.p2-t207-r1-…` / `…-r2-…`，均 blocked `release_rows_incomplete`，`pass=34 / blocked=2`；复原回 pending | ✅ |
| `zero_rewrite` 对象化同行呈现 | 三条 binding 行都带对象：`{"legal":false,"rule":"rewritten == trace_rows_not_at_attested 且 post_update_not_at_attested == 0","trace_rows_not_at_attested":25,"post_update_not_at_attested":0}`（R2 为 `legal:true`，25/1 对应 R1/R4） | ✅ |

关于 §4.2 的 22：该句描述的是"返工 T4-R1 时 negative 文件 22 passed"，而 H2 接线后又加了 1 条（现 23），句子本身没有错到需要改，但它与"当前 38 passed"并列时容易读成现状。**不构成缺陷，记一条文档口径提示。**

### 13.8 B0 / 回归 / 冻结清单

* `p2-admit` → **exit 0**，`evidence_sha256=2226fa208aec7db84ab69e5f7a068e94322414d38b90c14399979b96fcea8b5d`；`trace_integrity/citation_required/exact_value_contract=pass`，其余 `not_applicable`；`hard_failures=[]`；`40/40、38/40、24/24、OCR 8/8(7)`；`blocked_pending_n_c_u_h2_evidence`。
* 回归：`test_p2_release_gate_*.py` = **38 passed**（10 + 23 + 5；`fixtures.py` 单独 exit 5 属预期）；`test_p2_gate 27 / p2_score_run 9 / diff_release_gate 15 / baseline_portability 21 / p2_holdout_scenarios 84`，全部 exit 0。
* 冻结清单：**27 项，mismatch 0 / missing 0**（跑完全部命令后再验一次仍 0）。`gate_v0_3_approved.json` 在表内（`b1094cc7…`，5785 B），`git ls-files` exit 1 → **仍未跟踪**，表下"必须显式纳入"的说明仍在。
* 21 项 → 27 项的新增：`p2_release_h2_aggregate.py 1b7edd40…`、H2 四件（`f6465fcb…`/`096de42f…`/`f20661d2…`/`359c9554…`）、`wire_real_ncu.py 3a27f9da…`、`gate-result.real-ncu.json 1319cc35…` 等，与我实算一致。

### 13.9 零请求与原件保护

* 7 次带网络闸门运行（wire / admit / 4 个探针 / 10 个测试文件）**EXTERNAL=0**；`test_p2_holdout_scenarios` 内 3 次 `127.0.0.1` 为本地夹具。
* `git status --short`：474 行（承接态，含 `H2-REBUILT-CARDS/` 新目录）；我新增的只有 `?? .tmp-t4review-isolated/`；`docs/evaluation` 相对索引 **0 改动**；`gate.py` 仍 `e04990db…`；任务 1 `H2-DOC-REBUILD` 五文件字节数与 mtime 未变；任务 3 NCU `SHA256SUMS` 17/17 未变（本包报告亦声明"任务 1/3 未改动"）。

### 13.10 本轮保留项（提交 T900 时应一并转达）

1. **`technical_gate` 仍 `pending`**：唯一实质待办是主人对"U 组 run 级 1 是否可配 9 条本地控制"的书面裁定（`hard_gate_min_sample.unmet`）。T900 不得把本包读成"技术门已通过"。
2. **报告 §0 第 2 条的"剩余 pending"仍写 H2**（"H2 同批聚合（任务 2）+ min_sample"），与同段 `36/0/3/8` 及 §5 的"已解除"矛盾；§6.4 第 192 行、§7 第 196 行同样过时。§0 的计数、标题已更新，只有这几处括注/段落没跟上。
3. **§1 输入契约表**仍描述旧的"卡本体 `h2.composition` / `h2.cards[]`"契约，实际接线是 `h2.source_proof` + `h2.composition_aggregate` + `h2.cards_index` 三件聚合；表未同步（新契约写在 `p2_release_h2_aggregate.py` docstring 与 §H2 接线节）。
4. **`card_file_sha256` 在仓内不可复算**：卡本体依 D-001 留在保管环境，门禁只能验"文件哈希 ≠ 聚合哈希"与索引自身的字节绑定，不能验证"这个文件哈希确实是那张卡"。这是边界声明（`h2.card.*.detail.card_body_location` 已写明"仓外保管环境（本轮未读取）"），不是缺陷，但 T900 需知信任根在任务 2 的保管环境。
5. **C25 历史 1 的落点指错**（门禁 note 写"由任务 3 单列"，实际在任务 2 报告 §5）：文本瑕疵，建议改为"由任务 2 报告 §5 单列"。
6. `h2.hard_failures` / `h2.required_axes` 是"校验通过后的如实行"（对应字段在聚合校验阶段已 fail-closed），非独立复核；对 T900 无害，但不再重复计算一遍。

### 13.11 本轮 NOT-VERIFIED

| 项 | 原因 |
| --- | --- |
| H2 卡本体内容（题干/标签/逐题回答） | D-001 边界：卡本体在仓外，本包按设计不读；我只验聚合外层与来源证明 |
| 任务 2 的 `29/30` 质量分与 `verified=true` 的**重新计分** | 需卡本体与逐题证据；本轮只核聚合/索引/证明三者内部一致与身份 |
| `h2-source-proof.json`（审计视图，另一 schema） | 交付方声明"仅存档、不喂 `_validate_source_proof`"；我核了它与 full 版 batch_binding/C25 数值相同，但未按其 schema 单独校验 |
| 返工前旧版文件 | 未跟踪文件就地修改，git 不可重建；以第二轮实测输出为对照基线 |

### 13.12 本轮写入 / 清理

* 只改 `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/review.md`（新增本节 + 文首三轮索引）；其余全部在 `.tmp-t4review-isolated/`（末尾**只清这一个目录**，逐路径 `Remove-Item -LiteralPath`，无通配符）。
* `wire_real_ncu.py` 输出指向隔离目录，**未覆盖** `gate-result.real-ncu.json`（交付件 SHA `1319cc35…` 与本轮文件分工明确）。

## 14. D-011 专项确认（U 硬门样口径，2026-11-21 01:05–01:3x）

同一窗口，未采信返工自述。零真实请求（5 次带闸门运行 `EXTERNAL=0`），未 commit/push，未覆盖交付件。

### 14.0 结论

**确认通过（带保留）**。

**"D-011 是否构成判据放宽？" → 否（不构成未经授权的阈值放宽）；但它确实把"run 级样本要求"换成了"suite 计划题数覆盖"，属主人授权的覆盖口径变更，等效于一次受控放宽——因此必须保留固定披露行。**
依据：① 批准配置 `gate_v0_3_approved.json` 一个字节未改（`b1094cc7…`/5785 B），`hard_gate_min_sample` 与 `p2_standards` 全部数值与我上一轮记录逐项相同；② 覆盖判据只读配置的 `p2_standards.<suite>.total`，不接受任何自报；③ 门禁在 run 级子集上仍然真评估，"有失败/有非披露未知"照样阻断（我自造的非 citation 失败被拒）；④ 唯一实质变化是"1 条 run 级样本不再单靠数量判不足"，由 `hard_gate_min_sample.run_level_subset` 固定披露。**没有出现"数字不动、判定悄悄变宽"以外的隐藏放宽。**

### 14.1 复跑一致性：**字节一致**

| 运行 | SHA-256 | 字节 |
| --- | --- | --- |
| 我第 1 次 `wire_real_ncu.py`（`P2_RELEASE_NCU_OUT` 指隔离目录） | `e22ee349e61a5352da27930a067522f5584faf2e365033e2b1a74bb7d13476d2` | 52288 |
| 我第 2 次（同上） | 同 | 52288 |
| 交付件 `gate-result.real-ncu.json` | 同 | 52288 |

**三次字节完全一致**，exit **0**。原因是输出里 `inputs_sha256` 已被置 `null`（不再写入临时路径派生摘要），因此可复现性从"逐字段一致"提升到"逐字节一致"。字段核对：`decision=pass`、`technical_gate=pass`、`release_allowed=false`、`release_authority=owner`、`owner_release_decision=not_decided`、`counts={pass:38, blocked:0, pending:0, observed:9}`、`reason_codes=[]`、`pending={}`，47 行。

### 14.2 三条转 pass 条件：都真的在检查

读 `p2_release_public._hard_gate_row`（`u.hard_gates` 与 suite 硬门都用它）与 `p2_release_gate` 汇总：

1. **run 级子集门禁无失败**：`proof["hard_failures"]` 非空或 `exit_code==1` → **blocked `release_hard_failure`**；否则再查 `gate_status` 集合是否齐全（缺项即 blocked），以及任一 gate 不在 `{pass,not_applicable}` → **blocked `release_required_unknown`**（cause `hard_gate_unresolved`）。
2. **必需未知 0**：`unknowns` 里的 `check_id` 必须 ⊆ `{min_sample_not_met}`；出现任何其它 unknown → blocked（我实测见 14.4 N3b）。
3. **覆盖成立**：`min_sample_coverage()` 用**配置**的 `p2_standards.<suite>.total` 与 `hard_gate_min_sample` 比较，`covered=false` → `u.hard_gates` 转 pending + `hard_gate_min_sample.unmet` 固定行（见 14.4 N1）。

**最容易被绕过的是第 1 条里的"aggregate 行"**，不是 `u.hard_gates` 本身：
* `u.hard_gates` 对失败/未知是 fail-closed 的（我注入非 citation 失败 → blocked）；
* 但**汇总行 `hard_gates` 只看各来源的 `gate_status`，不看 `unknowns`**。我注入一个非披露 unknown（`gold_missing`）后，`u.hard_gates` = blocked `release_required_unknown`，而 `hard_gates` = **pass**（总门仍 blocked，因为任一 blocked → blocked）。这不构成 fail-open，但汇总行会与子行不一致，属可改进点。
* 另一个理论风险：`hard_gates` 是从 `gate_proof` 重算，而不是读取 `u.hard_gates` 行；若将来某次改动让子行转 pass 而 proof 未同步，汇总行不会自动跟随。当前两者来自同一 proof，实测一致。

### 14.3 覆盖判据读的是 `p2_standards.total`（不是自报）

* 代码：`p2_release_public.min_sample_coverage`（`:345-369`）——`planned = int(getattr(standards, attribute))`，`attribute` 来自 `_SUITE_STANDARDS_ATTR`（`update_delete → update_delete_total`）；`required` 来自 `config.min_sample_for(...)`。函数签名里**没有任何"调用方声明计划数"的参数**，`run_level_evaluated` 只进披露字段。
* 输入契约侧：我往清单根加 `hard_gate_min_sample={"suite_planned_cases":10,"total":10}` → **blocked `release_inputs_invalid`**（严格键集合拒绝自报字段），见 14.4 N2。
* N2b（配置 `total=9` + 自报 10）同样先被契约拒掉；**N1（仅配置 `total=9`）** 则如实判"覆盖不成立 → pending"。两者合起来证明：**计划数只有一个来源——批准配置**。

### 14.4 我自造的负例（5 组，含 1 组与返工方不同的失败注入）

| 编号 | 我的构造 | 实际输出 |
| --- | --- | --- |
| N1 | 把**配置对象**的 `p2_standards.update_delete.total` 改为 9（配置原件不动，仅内存） | **pending**；`counts=36/0/3/9`；`u.hard_gates` pending `release_sample_below_min`；`hard_gate_min_sample.unmet` pending；`hard_gates` pending；helper 返回 `{suite_planned_cases:9, required:10, covered:false}` |
| N2 | 清单根塞自报字段 `hard_gate_min_sample={suite_planned_cases:10,total:10}` | **blocked**，`release_inputs_invalid`（0 pass / 1 blocked） |
| N2b | N1 + N2 同时 | **blocked**，`release_inputs_invalid`（自报先被拒，覆盖判据根本没机会被"说服"） |
| **N3（我自造，非返工方那条）** | 在 U 的 gate proof 里注入**非 citation** 的失败：`security_leak=fail` + `exit_code=1` | **blocked**；`counts=36/2/0/9`；`u.hard_gates` blocked **`release_hard_failure`**、`hard_gates` blocked **`release_hard_failure`** |
| N3b | 在 U 的 proof 里注入**非披露 unknown**（`gold_missing`） | **blocked**；`u.hard_gates` blocked `release_required_unknown`；**但 `hard_gates` 仍 pass**（见 14.2 的可改进点） |
| N4 | 把固定披露行从 rows 中过滤掉 | **仍 pass**（`observed` 由 9 变 8）→ 该行**只是展示**，没有任何不变量强制它存在 |

结论：N1/N2/N2b 复现了返工方的 ①②，**N3 是我自己换了一个门禁（security_leak 而非 citation）**，同样被阻断；N4 暴露的是"披露行可被删而不影响判定"的展示层风险。

### 14.5 配置未改

| 项 | 实测 |
| --- | --- |
| `docs/evaluation/gate_v0_3_approved.json` SHA-256 | `b1094cc726230be2ec22ec811d34a948ea4a2fe03aab2c0fcc4f20c99764d961`（与 D-004 时记录**逐字符相同**） |
| 字节数 | 5785 |
| `hard_gate_min_sample` | `{b0:32, badcase:8, boundary:6, update_delete:10, regression:7, p2-holdout:30}` |
| `p2_standards` | b0 `total 40 / min_pass 36 / exact 24 / ocr 8`；negative `8/8`；boundary `6/6`；update_delete `10/10`；holdout `30/24`；strata 10/5/5/5/5 |
| git 状态 | 仍**未跟踪**（`git ls-files` 非 0），冻结清单 27 项仍在表内并标注必须显式纳入 |

### 14.6 披露行

`hard_gate_min_sample.run_level_subset`（**observed**）存在，detail 与声称一致：

```json
{"suite":"update_delete","suite_planned_cases":10,"required_min_sample":10,
 "run_level_evaluated":1,"basis":"suite_planned_cases","covered":true,"scored_count":1,
 "disclosed_limit":"U 的八项硬门禁在 1 条 run 级样本上评估，其余 9 条为本地控制",
 "authority":"主人 D-011：按 suite 计划题数计覆盖，不改配置数值、不放宽判据"}
```

`u.hard_gates` 行同时带 `min_sample_coverage{...}` 与 `disclosed{check:"min_sample_not_met", note:"…只披露不阻断"}`。
**但它是展示性的**：N4 证明把它从 rows 里删掉后总门仍 `pass`（`observed` 9→8），没有任何不变量（如 `rows.completeness`）保证该行存在。可接受，但要求后续任何行过滤/重构不得静默删除；建议像 §12 的完整性断言那样把它纳入不变量。

### 14.7 `release_allowed` 仍为 false

最终 JSON：`release_allowed=false`、`release_authority="owner"`、`owner_release_decision="not_decided"`、`notes` 仍写"技术门通过只作为 T900 独立验收输入，不构成发布决定"。口径修订**没有**把发布权翻成 true；`technical_gate=pass` 与发布决定仍是两件事。

### 14.8 B0 / 回归 / 冻结

* `p2-admit` → **exit 0**，`evidence_sha256=2226fa208aec7db84ab69e5f7a068e94322414d38b90c14399979b96fcea8b5d`；`hard_failures=[]`、`exit_code=0`；`trace_integrity/citation_required/exact_value_contract=pass`。
* `test_p2_release_gate_*.py` → **41 passed**（10 + 26 + 5），exit 0；`fixtures.py` 单独 exit 5 属预期。
* 五条：`test_p2_gate 27 / p2_score_run 9 / diff_release_gate 15 / baseline_portability 21 / p2_holdout_scenarios 84`，全部 exit 0。
* 冻结清单 **27 项 drift 0**（`mismatch 0 / missing 0`）；`gate.py` 仍 `e04990db…`；H2 四件与 `wire_real_ncu.py`（`3a27f9da…` → 本次未变）都在表内且命中。

### 14.9 零请求与原件保护

* 5 次带闸门运行（wire ×2 / D-011 探针 / admit / 测试）**EXTERNAL=0**；`test_p2_holdout_scenarios` 的 3 次 `127.0.0.1` 仍是本地夹具。
* `git status --short` 474 行（含我的隔离目录）；`docs/evaluation` 相对索引 **0 改动**；任务 1 `H2-DOC-REBUILD` 五文件字节数与 mtime 未变；任务 3 NCU `SHA256SUMS` 17/17 未变（本轮未再动）。

### 14.10 保留项（D-011 专项）

1. **披露行无强制不变量**（N4）：删掉它总门仍 pass。建议把 `hard_gate_min_sample.run_level_subset` 纳入与 `binding.<run_id>` 同级的行完整性断言。
2. **`hard_gates` 汇总不看 `unknowns`**（N3b）：子行 blocked 而汇总行 pass，总门靠子行兜住；建议汇总时把各来源 `unknowns`（除 `min_sample_not_met`）也计入。
3. **报告 §0 第 12 行仍是过时句**："剩余 pending：H2 同批聚合（任务 2）+ `hard_gate_min_sample.unmet`"，与同段"0 pending / pass"及交付 JSON 直接矛盾（此句在 §13 已提过一次，仍在）。§15 的说明已改成"D-011 后仅覆盖不成立时出现"，只有 §0 这一行没同步。
4. **口径本身**：`covered` 由"计划题数 10"成立，而八项硬门禁的真实评估面仍是 1 条 run 级样本——这是 D-011 授权的取舍，披露行已写明；T900 解读 `technical_gate=pass` 时必须同时读该披露行，不能理解成"10 条 run 级证据都过了门"。
5. 覆盖判据对 N/C/B0 同样换成"计划题数"（8≥8、6≥6、B0 40≥32），但 B0 另有 `b0.execution`（40/40 实执行）单独把关，N/C 的 `min_sample` 与计划题数相等（8/8、6/6），实际无变化——不构成放宽。

### 14.11 本轮 NOT-VERIFIED

| 项 | 原因 |
| --- | --- |
| "两次重跑字节一致"在**不同机器/不同 Python 补丁版**上的稳定性 | 我只在本机同解释器下跑了两次；跨环境可复现性未验（`inputs_sha256=null` 已消除主要路径依赖） |
| `hard_gates` 汇总在"子行 pass 但 proof 有 fail"这种不可能状态下的行为 | 需要构造与真实 proof 脱钩的输入，超出本轮范围 |
| D-011 的主人裁定原文 | 我只看到返工方转述与报告 §D-011；未读到 `manager-decisions.md` 的 D-011 原文条目（本轮未放开该文件的新增段落核对） |

### 14.12 本轮写入 / 清理

* 只改 `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/review.md`；其余在 `.tmp-t4review-isolated/`（末尾**只清这一个目录**，逐路径 `Remove-Item -LiteralPath`，无通配符）。
* 两次 `wire_real_ncu.py` 输出都指向隔离目录，**未覆盖**交付件（交付件 SHA `e22ee349…` 与我复跑一致）。
