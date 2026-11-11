# P2-T207-FIX-H2PURGE 独立验收报告（review）

- 角色：独立验收助手（全新上下文）；分支 `codex/p2-e2e`；HEAD `6ba15bf`（验收前后一致，本包与本验收均**未 commit**）。
- 口径：零真实调用（本目录探针全程 mock / 显式 overrides / 真门 + tmp 副本）；只写
  `docs/reports/OBS-EVAL/P2/T207-FIX-H2PURGE/{review.md,evidence/verify/}`；未改代码/测试/夹具/账本/预算/GO。
- 结论：**接收（阻断 0）**。四条验收项全部 PASS；报告点名测试独立复跑一致（68 / 27 passed）；
  反证独立复现且范围比开发证据更完整（2/2 失败）。证据索引见 §6。

## 1 逐条判定

| # | 验收项 | 判定 | 依据（独立复核） |
|---|---|---|---|
| 1 | 范围/合规 | **PASS** | tracked 改动仅 3 个交付文件：`p2_live.py` +2、`cli.py` +3、`test_p2_live_wiring.py` +167（纯追加 §14，0 删除）；`fixtures`、`p2_scoring.py`、`p2_dataset.py`、`p2_runner.py`、`product_adapter.py`、`p2_authorization.py` 的 `git status` 为空；新增行 skip/xfail **0**；无 commit（HEAD/提交数不变）；账本/预算/GO 未被写（§4）。详见 `evidence/verify/06-compliance.txt` |
| 2 | 行为正确 | **PASS** | holdout live 最终以**真正的** `ProductEvalAdapter(purge_traces_on_close=True)` 装配（C1/E1）；public live 仍 False（A3/C2/E2）；`run_live_p2` 缺省 False（B3）；runner `holdout_requires_purge` 负例仍可达且 fail-closed（D1/D2 + 04）。详见 `03-probe.txt`（13/13 PASS） |
| 3 | 反证/回归 | **PASS** | 68 passed / 27 passed 复跑一致；独立"移除转发"反证：两个 CLI 用例**都** `KeyError: 'purge_traces_on_close'`，随后**逐字节恢复**（sha256 前后相同）。详见 `01`、`02`、`05` |
| 4 | 合规 | **PASS** | 零真实出站（两测试模块均带 `t09_network_guard`：`test_p2_live_wiring.py:57` / `test_p2_runner.py:80`；探针从未 `start` 适配器，`requests_sent=0`）；未读 `.env`（mtime 仍 2026-11-01）/H1/H2；账本/预算/GO mtime 早于 HEAD 且验收前后不变；仓库内无 H2 输入。详见 `06-compliance.txt` |

## 2 关键事实核对（`file:line`）

- 修复本体：`p2_live.py:1514` 新增 `purge_traces_on_close: bool = False`；`p2_live.py:1533`
  转交 `build_live_adapter`（该函数 `p2_live.py:1463` 早有同参数，默认 False）。
- CLI 转发：`cli.py:731` `purge_traces_on_close=purge_traces`；开关来源 `cli.py:599`（holdout=True）/
  `cli.py:622`（public=False）；dry-run 分支原本就已转发（`cli.py:664`）——**live 是唯一漏点**。
- 缺省仍 False 的三层：`product_adapter.py:860/883`、`p2_live.py:1463`、`p2_live.py:1514`。
- 负例未绕过：`p2_runner.py:778-789` 原样未改，holdout + `purge_traces_on_close=False` 在
  **首个发送之前**以 `holdout_requires_purge` 停止；`p2_runner.py:798-800` 仅在 True 时才要求封存。
- 唯一调用面：全仓 `run_live_p2(` 仅 `cli.py:722` 一处生产调用；`build_live_adapter(` 仅
  `p2_live.py:1524` 一处调用 → 无第五个入口绕过修复。
- 测试：`test_p2_live_wiring.py` §14 共 5 个 case（2 个 CLI + 1 个三参参数化），
  断言均为 `is True` / `is False` 的严格身份比较，非真值宽松判断。

## 3 独立行为验证（`evidence/verify/probe_h2purge.py`，13/13 PASS）

| 组 | 检查 | 结果 |
|---|---|---|
| A | `cli._cmd_p2_run` → `run_live_p2` kwargs：holdout=True / public=False；payload `execution=live` | PASS |
| B | `run_live_p2` → 真 `build_live_adapter` 捕获：True→True、False→False、**缺省→False** | PASS |
| C | 全链路 CLI（真 argparse-handler → 真门 → 真 `build_live_adapter`）：holdout 装配出的
  `ProductEvalAdapter.purge_traces_on_close is True`；public 为 False（仅把时钟钉进 GO 有效窗口，其余全真） | PASS |
| D | 真 runner：holdout + purge=False → `blocked/holdout_requires_purge`、`sent=0`、`chat=0`、
  `gate.json` 仅 `holdout_purge` 失败、`real_sends_allowed=false`、无 trace 库、
  `summary.holdout.trace_retention=refused-before-start`；**正对照** purge=True 不再被该码拒绝 | PASS |
| E | 真 argv：`--visibility holdout --mode live` → True；省略 `--visibility`（缺省 public）→ False | PASS |

反证（`05-counterproof-remove-forwarding.txt`）：临时删掉 `cli.py` 的 3 行转发（−3 行）后，
`test_cli_holdout_live_passes_purge_true_to_run_live_p2` 与 `test_cli_public_live_keeps_purge_false`
**同时**以 `KeyError: 'purge_traces_on_close'` 失败（2 failed）；恢复后 `cli.py` sha256
`1b5428e0…855` 前后一致、`git diff --stat` 回到 `+3`。

## 4 合规明细与证据强度

- 复跑：`test_p2_live_wiring.py + test_p2_runner.py` → **68 passed**（41.03s）；
  `test_p2_holdout_scorecard.py + test_p2_live_request_ceiling.py` → **27 passed**（11.25s）；
  单跑 `test_p2_runner.py::test_holdout_without_purge_is_refused_before_any_work` → **1 passed**。
  collect 计数 68、§14 的 5 个 id 均已落到用例清单。
- 账本/预算/GO：`docs/evidence/` 被 `.gitignore:10` 忽略，**不能**用 git 内容比对证明未写；
  改用 mtime + 行数：ledger `2026-11-11T06:41:41Z`（1409 行）、GO `06:42:01Z`、budget `11-10T17:42Z`，
  均**早于** HEAD 提交（14:46:43+08），且在我全部复跑前后**不变** → 未见本包写入痕迹（属间接证据）。
- 未读 `.env`：探针用 `load_live_env` 的**显式 overrides** 路径，不 import dotenv；`.env` mtime 仍为 2026-11-01。
- H2 输入：仓库内 untracked 无 holdout plan/manifest/sealed/fernet 命中（仅交接提示词与本包报告）。

## 5 限制与残余风险

1. **只证明接线，不证明真实 H2 跑通**：按要求零真实调用；真实 holdout live 仍受新 GO/预算/账本/环境准入约束，
   本修复不改变任何门禁口径（D 组已确认负例仍 fail-closed）。
2. **缺省 False 依赖单一入口**：目前全仓只有 CLI 调 `run_live_p2`，故无遗漏；若后续新增脚本入口跑 holdout live，
   必须显式传该开关，否则仍会被 `holdout_requires_purge` 在**发送前**拒绝（安全侧 fail-closed，不会静默跑脏）。
3. **正对照未跑完整 run**：D3 的 purge=True 臂以 `product_service_error` 收尾（探针 mock 答案与合成题不匹配所致），
   仅用于证明"该 stop code 不再恒触发"，不作为质量/通过证据。
4. 开发证据 `evidence/02-prefix-failure-proof.txt` 因 `-x` 只展示 holdout 1 个失败，未覆盖 public 用例；
   该证据缺口已由本验收 `05` 的 2/2 失败补齐（不影响结论，但报告"两个 CLI 用例失败"当时未被自身证据支撑）。
5. 账本/GO 的"未写"为 mtime 间接证据（见 §4），非内容哈希比对。

## 6 证据索引（`docs/reports/OBS-EVAL/P2/T207-FIX-H2PURGE/evidence/verify/`）

| 文件 | 内容 |
|---|---|
| `01-pytest-68.txt` | 点名两文件 68 passed 独立复跑 |
| `02-pytest-27.txt` | holdout scorecard + live ceiling 27 passed |
| `03-probe.txt` | 自写探针 A–E 共 13 项，全 PASS |
| `04-runner-negative.txt` | runner 既有 `holdout_requires_purge` 负例单独复跑 |
| `05-counterproof-remove-forwarding.txt` | 移除转发 → 2/2 失败 → 逐字节恢复（sha256 一致） |
| `06-compliance.txt` | 改动面/未提交/受保护面/账本 mtime/skip 扫描/.env/H2 输入 |
| `probe_h2purge.py` | 可复跑探针源码（零真实出站；固定路径全指 tmp 副本） |

## 7 最终建议

**接收（阻断 0）。** 建议经理侧照此口径记账：
1. 本包修复的是"CLI holdout live 未把 purge 开关传到装配层"这一**接线缺陷**，使 H2 live 能过
   `holdout_requires_purge` 前置门；**不等于** H2 已跑通、更不等于 H2 达标（阈值/门禁仍未审批）。
2. 真实 H2 仍需新计划 + 新 GO 重新播种后执行；执行时必须用 `--visibility holdout --mode live`（勿手搓参数）。
3. （非阻断，文档侧）`.claude/handoffs/_index.md` 现有 6 行未提交改动属文档/协调包（T206 pilot 交接文本，
   不含 H2PURGE 字样），**不归本包**；提交时请分开处理，避免混入本包 commit。
