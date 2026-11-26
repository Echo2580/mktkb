# T209 正式 B0 索引版本绑定修复 · 独立验收报告

主人，结论先给：**`PASS`**。

零外发独立验收完成：任务书指定的六文件回归 **123 通过 / 0 失败 / 0 跳过**（进程退出 0，守卫实跑命中 0），定向用例 **4 通过**（参数化四例），独立正反探针 **8 个场景、82/82 项断言通过**，保护工件 **33/33 前后摘要一致**，冻结待验摘要 **9/9 前后一致**，工作树 `git status` 前后逐行相同。未发现需要交回返工的缺陷。缺陷最小复现一节因此为空，仅留一条**非阻断**的守卫使用观察（§8）。

- 分支 / HEAD：`codex/p2-e2e` / `97b0066726e5b8d6f94cbc0b63a890084550c106`
- 验收角色：独立验收 AI（非开发方）；授权范围：离线、零外发
- 证据目录：`var/eval/t209-prep/b0-ia-index-20261120T1820-4f2c9a1b/`（git 忽略，UTF-8）

---

## 1. 环境与冻结摘要（前后一致）

| 项 | 验收前 | 验收后 |
| --- | --- | --- |
| 分支 / HEAD | `codex/p2-e2e` / `97b0066` | 同 |
| `git status --porcelain` 行数 / 摘要 | 441 行 | 441 行，逐行相同（0 差异） |
| 任务书 9 项待验 SHA-256 | 见下，9/9 命中 | 9/9 逐字节相同 |
| 33 件保护工件 | 见 `protected-before.json` | 33/33 摘要相同，0 漂移 |

待验摘要（验收前后两次复算完全相同，落盘 `logs/frozen-after.txt`）：

```text
420e3b9db68691096fc2eece1c94449e8b34105783471c1a36a3c2367e2b4995  backend/src/mktkb/evaluation/p2_runner.py
23f1d004c47074f589c70ef81a62aecec75ef6f20ab9fc0cdf34aa01b0fc78cb  backend/tests/evaluation/test_p2_runner.py
93d0e54f9b6e564b12a120eb20babc64094df808b17582b8b54454daadb67459  backend/src/mktkb/evaluation/product_adapter.py
114158ef00f17570654a4b52a13254dd9d8f9d19493b787607b5b14336fa66a3  backend/src/mktkb/evaluation/p2_b0.py
102350994939fcd47b9c268cf732743a322b1b05bd282d563de06a354b1fec1b  backend/src/mktkb/evaluation/gate.py
b1094cc726230be2ec22ec811d34a948ea4a2fe03aab2c0fcc4f20c99764d961  docs/evaluation/gate_v0_3_approved.json
69cdc032630bd84074160f433cf3cc6308c946a2c8f0d95ac49d27fa0fd98ea3  var/eval/t209-prep/b0-dev-index-20261120/guarded.py
af7d8cec3c0908e7c4b4ac8c02bd057135aa6b88021ee29ffb7e319f5fd12f94  var/eval/t209-prep/b0-dev-index-20261120/verified.log
7f7c41e2e0c6f80db5777c516d172e95d4475f19c51073861fca9462a3f3afc9  var/eval/t209-prep/b0-dev-index-20261120/protected-before.json
```

保护工件复核（`logs/protected-after.json`）：33 项、0 mismatch，覆盖 attempt2 原件与 SQLite 旁文件、共享账本、预算、固定 GO、正式基线、`gate_v0_3_approved.json` 与 attempt2 报告。只算摘要，未读共享文件内容。

说明：本报告与证据目录位于 `var/`（git 忽略）和 `docs/reports/OBS-EVAL/P2/T209-PREP/`（整目录未纳入版本管理，`git status` 里本就是同一行 `??`），因此写入报告后 `git status` 仍是 441 行、0 差异；**没有任何已跟踪文件被改动**。

## 2. 任务书指定回归（实跑）

守卫入口按任务书要求先审阅、再复制到本证据目录、只把 `scratch` 改成本次唯一标识：

```text
cd backend
& ..\.venv\Scripts\python.exe -B -X utf8 <evidence>\guarded.py regression `
  tests/evaluation/test_p2_runner.py tests/evaluation/test_p2_b0.py `
  tests/evaluation/test_p2_gate.py tests/evaluation/test_baseline_portability.py `
  tests/evaluation/test_diff_release_gate.py tests/integration/test_p2_product_e2e.py
```

| 项 | 预期 | 实际 |
| --- | --- | --- |
| 通过 / 失败 / 跳过 | 全通过、无失败 | **123 passed** / 0 / **0**（56.40 s） |
| 进程退出码 | 0 | **0**（`PYTEST_EXIT 0`） |
| 守卫实跑命中 | 0 | **`GUARD_OPERATIONAL {} []`** |
| 守卫校准命中 | 8 项全中 | `{'network': 2, 'subprocess': 1, 'protected read': 2, 'unlisted read': 2, 'protected write': 1}` |

定向用例（任务书 §2 指定）：

```text
tests/evaluation/test_p2_runner.py::test_formal_b0_binds_ready_index_and_stops_on_drift
→ 4 passed（stable / not_ready / before_second / during_final 四参数），7.75 s，退出 0，实跑命中 0
```

**与开发自测的对照与跳过说明**：开发基线 `verified.log` 为 `122 passed, 1 skipped`，跳过的是 `tests/evaluation/test_p2_b0.py:321` 的 `test_formal_read_rejects_hardlinks`（`[WinError 5] 拒绝访问`，卷不支持建硬链接）。本次同一卷建链成功，该用例**实际执行并通过**，所以本次是 123 通过、0 跳过，合计用例数与开发一致（122+1=123），没有覆盖缺口。为免依赖卷行为，另加独立补验：在隔离目录成功建硬链接后读取保护工件，`read_member` 以 `B0Error: b0_link_rejected` 拒绝（`probes/hardlink_reject/probe.json`）。

六文件回归同时覆盖矩阵第 5 行的「正式 B0 准入 / P1 归档 / 差异 / 普通 P2 与合成 H2 身份·留存」：`test_p2_b0.py`（准入与正式入口同源校验）、`test_baseline_portability.py`（归档可移植）、`test_diff_release_gate.py`（差异门）、`test_p2_gate.py`、`test_p2_product_e2e.py`，全部在隔离 `tmp_path` 内执行。

## 3. 独立探针（8 场景，82/82 通过，各进程退出 0）

探针入口与开发守卫同一套（环境清洗、审计钩子、8 项校准、离线事件循环），只把末尾 pytest 调度换成场景调度；场景与开发用例分开写、注入点按本次重新选择：

| # | 场景 | 注入/做法 | 结果 | 证据 |
| --- | --- | --- | --- | --- |
| 1 | `three_path` | 公开样本 `V04_物品位置表_新版V3.xlsx` 先以 D01 名称发布，再用 `D01_物品位置表.xlsx` **替换同一份已发布资料**，加 D04；三题走产品路由 | **PASS** 15/15 | `probes/three_path/` |
| 2 | `gate_negative` | 复制场景 1 的 run，只把**一条** trace 的索引版本 +1，用**原 v0.3 已批准门禁**复算 | **PASS** 5/5 | `probes/gate_negative/` |
| 3 | `not_ready` | 灌库完成后把索引同步状态置为不可用（有效版本不可得），在绑定点前注入 | **PASS** 11/11 | `probes/not_ready/` |
| 4 | `pre_turn_drift` | 第 1 题已执行并结算后、第 2 题**预留前**改变索引版本（删除一份资料） | **PASS** 13/13 | `probes/pre_turn_drift/` |
| 5 | `final_turn_drift` | **最后一轮开始后**（该轮作答模型调用前）改变索引版本 | **PASS** 13/13 | `probes/final_turn_drift/` |
| 6 | `non_final_turn_drift` | 非最后一轮（第 2 题）响应产出后改变索引版本，核对后续停发 | **PASS** 13/13 | `probes/non_final_turn_drift/` |
| 7 | `cli_entry` | 正常 CLI `p2-run --mode live`，分别用 attempt2 的**旧源码绑定**与本次**新源码绑定** | **PASS** 10/10 | `probes/cli_entry/` |
| 8 | `hardlink_reject` | 独立硬链接拒绝补验（见 §2） | **PASS** 2/2 | `probes/hardlink_reject/` |

### 3.1 三路径正例：两套版本号确实不同，三条 trace 都跟实际索引版本一致

替换发布后、绑定前的产品实测（`index_status`）：

| 数值 | 实际值 | 含义 |
| --- | --- | --- |
| 业务库版本（`product_revision`） | **3** | 三次发布后的业务库修订号 |
| 实际 RAG 索引版本（`index_revision`） | **4** | 索引自身修订号（含一次换版写入） |
| 绑定进 manifest / summary / gate 的索引版本 | **4** | 与上一条相等 |
| 终态业务库版本 `adapter.product_revision()` | **3** | 与绑定值不等（正是 attempt2 的缺陷条件） |

三条问答路径的实际 trace（SQLite `qa-traces`）：

| 路径 | trace `index_revision` | 与绑定一致 |
| --- | --- | --- |
| `rag` | `4` | 是 |
| `legacy` | `4` | 是 |
| `legacy_with_rag_candidates` | `4` | 是 |

- `manifest.index_revision == summary.binding.index_revision == gate.binding.index_revision == 4`，`binding.complete=true`、`missing=[]`。
- 用**已批准的 v0.3 配置**（`gate_v0_3_approved.json`，config_hash 由 `load_approved_b0_config` 校验）复算 8 项硬门禁：`trace_integrity=pass`、`citation_required=pass`、`pagination_contract=pass`，其余 `not_applicable`（合成三题无 gold 值），`hard_failures=[]`。
- 出站：`adapter.provider_calls().outbound_network == 0`（chat 走 `httpx.MockTransport`，embedding/rerank 为离线假实现），守卫实跑命中 0。
- 门序 9 次 = 3 轮 × (`begin`→`confirm_before_send`→`settle_success`)，`requests.jsonl` 3 行，`cases.jsonl` 3 行。

### 3.2 门禁反例：原门禁仍然按 `version_binding` 报错

只把 P02（`legacy` 路径）trace 的 `index_revision` 从 `4` 改成 `5`，其余逐字节不动：

| 项 | 未改动副本 | 单条改动副本 |
| --- | --- | --- |
| `trace_integrity` | `pass` | **`fail`** |
| 失败检查 | 无 | `version_binding`，`mismatched=["index_revision"]`，仅 1 条（case `P02`） |

即：修复没有放宽门禁；两套版本号不同时，只要有一条 trace 不合绑定，原 v0.3 门照旧 fail closed。

### 3.3 停发与结算（三例）

| 场景 | 运行状态 / 停止码 / 阶段 | 已执行轮 | 预留 / 请求行 / 结算 | 下一轮 |
| --- | --- | --- | --- | --- |
| 首题前阻断 | `blocked` / `b0_index_not_ready` / `index_after_ingest` | 0 | 门序调用 **0** / 请求行 **0** / 产品问答行 **0** | 无 |
| 轮前漂移 | `aborted` / `b0_index_changed` / `index_before_turn`（P02） | P01 | 1 / 1 / 1 | P02 **无预留、无发送** |
| 最后一轮内漂移 | `aborted` / `b0_index_changed` / `index_after_turn`（P03） | P01–P03 | 3 / 3 / 3 | — |
| 非最后一轮内漂移 | `aborted` / `b0_index_changed` / `index_after_turn`（P02） | P01–P02 | 2 / 2 / 2 | P03 **无预留、无发送** |

- 首题前阻断：`manifest.index_revision=null`、`binding.complete=false`、`missing` 含 `index_revision`；失败清单元数据可读（`stage/stop_code/case_id/turn/item_id` 齐全）；`requests_sent=0`；灌库期 2 条合成回执按范围保留（`ingest_receipts`），无任何预留可核算。
- 轮前漂移：已执行 P01 的**响应、trace、结算**三件都在（`cases.jsonl` 有 `product`、trace `rag` 版本 `2`、结算 `P01:turn1:answer`），失败清单写明被阻断题 `P02` 与轮 `1`。
- 最后一轮内漂移：P03 的响应与结算在漂移检出前已落盘（3 条 trace 都是绑定版本 `2`，3 笔结算齐全），运行以 `aborted` + `index_after_turn` 收尾。
- 非最后一轮内漂移：P02 结算保留，运行立即停，P03 从未进入预留/发送。

### 3.4 正式入口与旧源码绑定

| 绑定 | 退出码 | 环境装载 | 发送门 | 输出目录 | 结果 |
| --- | --- | --- | --- | --- | --- |
| attempt2 旧源码绑定（`pipeline_source_sha256=6fbde812…06a2`） | **3** | **0 次** | **0 次** | 未创建 | `ERROR: B0Error: b0_plan_binding_mismatch` |
| 本次新源码绑定（`pipeline_source_sha256=28aae43c…e8e7`） | **3** | 1 次 | 1 次 | 未创建 | 抵达注入停止点：`{"error_code": "ia_cli_stop_point", "requests_sent": 0}` |

即：修复改变了正式计划的源码摘要（`6fbde812…` → `28aae43c…`），旧绑定在**环境装载与真实发送门之前**就被 `b0_plan_binding_mismatch` 拒绝；新绑定能通过同一套发送前校验并抵达注入停止点，`requests_sent=0`、`real_requests=0`。

## 4. 守卫校准与实跑命中

每次进程都先打印同一组 8 项校准命中，再清零计数；实跑（回归、定向、8 个探针）全部为 `GUARD_OPERATIONAL {} []`：

```text
GUARD_CALIBRATION {'network': 2, 'subprocess': 1, 'protected read': 2, 'unlisted read': 2, 'protected write': 1}
```

校准覆盖：网络 connect、DNS 解析、子进程、`.env` 读取、共享账本读取、固定 GO 读取、私有 H2 读取、隔离区外写入 —— 8 项全被拦下。实跑 0 命中即：无网络、无 DNS、无子进程、无凭据/共享文件/私有 H2 读取、无隔离区外写入。

## 5. 判定对照（任务书 §4）

| 判定条件 | 实际 |
| --- | --- |
| 矩阵全部满足 | 满足（§2、§3） |
| 关键反例按目标错误码阻断 | `b0_index_not_ready` / `b0_index_changed`(`index_before_turn`,`index_after_turn`) / `b0_plan_binding_mismatch` / `version_binding` 全部命中 |
| 回归无失败 | 123 passed / 0 failed / 0 skipped |
| 实际守卫命中与真实出站为 0 | 是（所有进程 `GUARD_OPERATIONAL {}`，`outbound_network=0`） |
| 保护工件前后摘要一致 | 33/33 一致 |

## 6. 边界自证（未触碰项）

- 未修改任何生产源码、仓内测试、正式门槛、Git 记录或历史工件；`git status` 前后逐行相同。
- 未读共享账本/预算/GO 内容，只算摘要；未写 `docs/evidence`、`var/eval/runs`、`var/eval/baselines`。
- 未发真实请求、未调额、未签新 GO、未接收正式基线、未做 P2 发布。
- 运行产物全部在隔离目录：测试临时目录 `backend/.pytest_cache/b0-ia-index-20261120T1820-4f2c9a1b/`，探针产物 `backend/.pytest_cache/<同名>/probes/`，关键工件复制回证据目录。
- attempt2 原件只做摘要复核，未打开内容、未重跑。

## 7. 偏差与局限

1. 探针运行器的门是**只记录门序的桩门**（`is_mock_gate=True`），并以 `p2_runner.is_real_p2_gate` 显式放行到正式 B0 分支：真实 `P2Gate` 被硬绑到共享账本（禁止读写的范围），离线无法构造。真实门/真实发送路径由仓内 CLI 同源校验用例（`test_formal_cli_and_direct_api_use_same_presend_validation`）与本次 `cli_entry` 的注入停止点覆盖，本次未做真实发送。这一点按任务书授权边界如实标注。
2. 合成三题无 gold 值，`exact_value_contract` 判 `not_applicable`；40 题正式 B0 的准入/归档/差异由仓内回归（`test_p2_b0.py` 等）覆盖，不在本次探针里重造 40 题。
3. 供应商为 Mock、OCR 关闭、embedding/rerank 为离线假实现，因此本次结论只覆盖**索引版本绑定与停发语义**，不构成对真实供应商链路的结论。

## 8. 非阻断观察（不构成缺陷，交经理留存）

首次六文件回归时，`--basetemp` 指向**上一轮已存在的** pytest 临时根，pytest 启动时用 Windows 长路径前缀（`\\?\`）删除旧目录，守卫按字面路径判定为「隔离区外写入」并拦下，导致 115 个用例在 setup 阶段报 `PermissionError`（进程退出 86、命中 230 次）。删除陈旧 basetemp 后，同一入口、同一目标得到 123 通过、命中 0。

- 性质：守卫的路径前缀归一化缺口（仅 `\\?\` 前缀下误判），与本次修复无关，也不放松任何保护。
- 复现与证据：`logs/debug2.txt`（记录完整 `\\?\` 路径与被拒动作）。
- 建议：复用守卫入口时使用**全新** basetemp 名（本次已改为每轮新名字）；若要长期复用，可考虑让守卫对 `\\?\` 前缀做一次 `resolve()` 归一化。

## 9. 证据路径

| 路径（相对 `var/eval/t209-prep/b0-ia-index-20261120T1820-4f2c9a1b/`） | 内容 |
| --- | --- |
| `guarded.py` | 开发守卫副本，仅 `scratch` 改为本次唯一标识（`581023c3…`） |
| `harness/probe_entry.py` / `harness/probes.py` | 独立探针入口与 8 个场景（`17f53529…` / `6d103d51…`） |
| `logs/state-before.txt` / `logs/state-after.txt` | 分支、HEAD、工作树状态（前后各 441 行，0 差异） |
| `logs/frozen-after.txt` | 9 项待验摘要复算 |
| `logs/protected-after.json` | 33 件保护工件复算（0 mismatch） |
| `logs/regression.log` | 六文件回归完整输出（`PYTEST_EXIT 0`、`GUARD_OPERATIONAL {}`） |
| `logs/directed.log` | 定向用例（4 passed，退出 0） |
| `logs/probe-*.txt` | 8 个探针的逐项 PASS/FAIL 与观测值 |
| `logs/probe-summary.txt` | 82/82 汇总 |
| `logs/debug1.txt` / `logs/debug2.txt` | 守卫 `\\?\` 观察的对照记录（§8） |
| `probes/three_path/` | `probe.json`、`run_manifest.json`、`summary.json`、`gate.json`、`cases.jsonl`、`requests.jsonl`、`qa-traces.sqlite3` |
| `probes/not_ready/`、`probes/pre_turn_drift/`、`probes/final_turn_drift/`、`probes/non_final_turn_drift/` | 同上七件（停发与结算证据） |
| `probes/gate_negative/`、`probes/cli_entry/`、`probes/hardlink_reject/` | `probe.json`（反例、入口与硬链接证据） |

## 10. 交回经理

- 结论：**`PASS`**。索引绑定修复在离线、公开样本、Mock 供应商、隔离目录条件下满足任务书全部判据：三路径 trace 与绑定/清单/摘要/门禁同版本；单条 trace 改版本仍被原 v0.3 `trace_integrity` 以 `version_binding` 拦下；索引未就绪、轮前漂移、最后一轮内漂移、非最后一轮内漂移四种停发均按目标停止码与阶段生效，已执行轮的响应、trace 与结算保留；旧源码绑定在环境与发送门之前被拒。
- 无缺陷需交回返工；§8 的守卫 `\\?\` 观察仅影响「复用陈旧 basetemp」的用法，建议在下次复用入口时留意。
- 未做：真实请求、调额、新 GO、正式基线接收、P2 发布 —— 均按任务书留待另行授权。
- 建议下一步：由经理复核本报告后，再决定新的真实运行计划与预算（当前阶段额度与 OCR 中心额度的历史结论未在本轮复核范围内）。

## 11. 补证追加：Trace 归档修复（2026-11-20 18:30，Asia/Shanghai）

本节在 §1–§10 定稿后追加，属**证据补强**，不改变任何结论与已有数值。

**现象（经理只读发现）**：§9 表中 5 个探针各自交付的 `probes/<name>/qa-traces.sqlite3` 均为 4,096 字节，缺少 `traces` 表。

**根因**：首轮 `copy_evidence()` 在 `adapter.close()` **之前**复制，trace 库当时仍为 WAL 模式，主库文件只有一个 4096 字节页头，实际数据在 `-wal`；`copy2` 只取了主文件。关闭适配器时 WAL 已回写主库，因此 `backend/.pytest_cache/<id>/probes/<name>/run/data/observability/qa-traces.sqlite3` 下的原库一直完整（40,960 / 49,152 字节，无 `-wal`/`-shm`）。

**处置**：按各探针 `probe.json` 的 `run_dir` 定位原库，逐份保全并归档到 `trace-archive-supplement/`：

| 每探针子目录 | 内容 | 与原库关系 |
| --- | --- | --- |
| `original/qa-traces.sqlite3` | 字节级保真副本 | SHA-256 与源逐字节相同 |
| `qa-traces.complete.sqlite3` | 自包含归档（`journal_mode` 归一为 DELETE，读取后不产生旁文件） | 行内容与保真副本全等；SHA 差异仅来自 journal 头字段 |
| `defective/qa-traces.sqlite3` | 4,096 字节旧副本（原样保留） | 无 `traces` 表（可读、0 表） |

**只读核对（5/5 通过，未重跑测试、未改源码、未发真实请求）**：

| 探针 | 原库字节 | `traces` 表 | trace 条数（期望） | 索引版本 | 结论 |
| --- | --- | --- | --- | --- | --- |
| `three_path` | 49,152 | 有 | 3（3） | 全为 `4`（rag / legacy / legacy_with_rag_candidates） | PASS |
| `not_ready` | 40,960 | 有 | 0（0） | — | PASS |
| `pre_turn_drift` | 40,960 | 有 | 1（1） | `2` | PASS |
| `final_turn_drift` | 49,152 | 有 | 3（3） | `2` | PASS |
| `non_final_turn_drift` | 40,960 | 有 | 2（2） | `2` | PASS |

每份归档的 trace_id 均与各 `probe.json` 记录的 id 集合完全一致；保真副本与归档副本逐行（trace_id/path/index_revision/status）全等。原 5 份 4,096 字节副本在原位保留、未覆盖。

**清单**：`trace-archive-supplement/supplement-manifest.json`（机读，含每份文件的相对路径、字节数、SHA-256 与查询结果）+ `trace-archive-supplement/supplement-report.md`（人读）；生成日志 `logs/supplement-archive.txt`。工具：`harness/supplement_trace_archive.py`、`harness/supplement_render.py`。
