# P2-T207-FIX-LIVEGATE 独立验收报告

- 现场：`codex/p2-e2e` @ `df661cb`（HEAD，未 commit）；工作区另有并行包改动（见 §1 归属核对）。
- 零真实调用：本次验收只做只读代码核对 + 自建 tmp 副本的门调用 + pytest（MockTransport/netguard）。我未打开 `.env`/H1/H2 任何文件（pytest 只跑既有用例）。
- 判定快照（本包 5 个文件 sha256，验收开始与结束两次计算一致）：
  - `p2_live.py` `1a5b86f6…55f68`（= 开发 evidence/pre-fix-failure.txt 记录的修正版）
  - `test_p2_live_wiring.py` `0c702774…34a00`
  - `p2-run-contract-v0_1.md` `bb7d192e…`；`p2-live-binding-v0_1.md` `3e3f27fb…`；`T207-runbook.md` `f64000c6…`
- 证据目录：`evidence/verify/`（`verify-script.py` + `verify-script-out.txt`、`pytest-livegate-independent.txt`、`scope-attribution.txt`、`manifest-root-vs-repo.txt`、`probe-manifest-guard.py`）。

## 结论：**接收**（6 项任务全部 PASS；遗留仅 §7 的非阻断项）

## 1. 范围 —— PASS

- 本包改动恰为：`p2_live.py`（+31/−4）、`test_p2_live_wiring.py`（+133/−0，单 hunk）、三份文档、本包报告目录（未跟踪）。
- `p2_authorization.py` / `p2_contracts.py` / `p2_runner.py` / `fixtures/` **未改**（`git status` 与 numstat 均无）。
- 工作区其余改动逐文件 grep `required_live_operations|LIVE_CORE_OPERATIONS|open_live_gate|live_operation_not_authorized` 命中 **0 行** → 属并行包（FIX-SCORE/FIX-CONFLICT）与 PM 索引，不属本包，见 `evidence/verify/scope-attribution.txt`。
- 账本/预算/GO 只读核对（当前值，与开发 evidence 一致，且**我这次运行前后逐字节未变**）：
  - 账本 `05b54d06…`，1,354,211 B（正式 R1 运行导致的合法增长，非本包写入）
  - 预算 `79b21700…`，1,738 B；GO `3ed427f4…`，1,272 B（H2 GO，scope.operations 六项含 ocr）
- 无 skip/xfail（diff 里只出现 `parametrize`）；无 commit（HEAD 仍 `df661bc`）。
- 新增用例数核对：4 个测试函数，其中一个 4 参数化 → **7 个用例**，与报告一致。

## 2. 默认公开计划行为逐字不变 —— PASS

三重独立证据（脚本不 import 开发者测试设施）：

1. **源码级**：从 `git show HEAD:backend/src/mktkb/evaluation/p2_live.py` 取旧模块，ast 抽取 `open_live_gate` 函数体做行级 diff —— 删除恰为旧 4 行 `missing = sorted({...5 项...} - authorization.operations)`，新增恰为 1 行 `missing = sorted(set(required_live_operations(plan)) - set(authorization.operations))` + docstring 两行；**函数其余语句零差异**（A1）。
2. **集合级**：对 6 个操作（含 query_expansion）的 64 个子集穷举，旧/new 必需集差异**恒为且仅为** ocr，且只在"计划无 ocr 项"时出现（B1）。
3. **真实公开矩阵计划**（`docs/reports/OBS-EVAL/P2/T207/PM/T207-plan-v0_1.json`：233 项 / 254 请求 / **12 页 OCR**）：`required_live_operations` == 旧五项；旧/new 同一计划：
   - GO 覆盖 → 两者都开门，`authorization.operations` 完全相同且含 `ocr`（C2）；
   - GO 少 `ocr` → 两者同为 `go_operation_unauthorized`（C3）；
   - 计划缺 answer / index_embedding / query_embedding / rerank 任一 → 两者同为 `live_operation_not_authorized` 且指名该操作（C4×4）。

## 3. H2 型计划可开门、四核心仍强制、无计划外 OCR 通道 —— PASS

- H2 型计划（无 OCR 项、四核心齐、含 query_expansion）：`page_count=0`、`operations` 不含 ocr（D1）。
- `GO = 计划操作`（五项，无 ocr）：**旧逻辑** `live_operation_not_authorized: GO 未授权 ['ocr']`（独立复现开发 evidence 的失败形态），**新逻辑开门**，`authorization.operations` 五项无 ocr（D2）。
- `GO 为含 ocr 的超集`（真实 H2 GO 形态）：新逻辑开门，`authorization.operations` 仍取自计划（无 ocr）；旧逻辑照样拒（D3）。
- 计划缺任一核心操作（4 参数）：`live_operation_not_authorized` 并指名（D4×4）。
- 无"无计划项也能发起 OCR"通道：`PlanIndex.ocr_count=0`（F1）；`next_ocr_item(0)` → `attempt_item_exhausted`（F2）；`gate.begin_attempt("ocr-Q01-p1")` → `item_unknown`（F3，预留前拒）；同时 H2 门对计划内项可用（F4 成功预留 rerank，成本中心取自计划项）。
- 代码侧确认路径闭合：OCR 发送唯一入口 `GatedOcrGateway.recognize`（`p2_live.py:922-935`）先 `PlanIndex.next_ocr_item` 再 `ledger.begin_sync_attempt(item)`；`P2Gate._begin_locked` 对 `item_id` 做 `self._plan.item(item_id)`（`p2_authorization.py:1039-1041`），计划外 item 一律 `item_unknown`。

## 4. 反向保护未放宽 —— PASS

- GO 少计划操作（缺 rerank）→ `go_operation_unauthorized`；GO 含未注册操作（replay）→ `go_operation_invalid`；两者在旧/new 模块下**完全一致**（E1/E2；代码 `p2_authorization.py:472-480`）。
- 机制核对：`authorization.operations = tuple(sorted(plan.operations))`（`p2_authorization.py:644`），`P2RunPlan.operations` 由 items 派生（`p2_contracts.py:913-915`）——**不存在"计划有 OCR 项但 operations 无 ocr"的构造通道**，故"含 OCR 项的计划必须 GO 覆盖 ocr"仍由 `authorize_p2` 硬保证（C3 实证）。

## 5. 文档一致性 —— PASS

- runbook §8 三处 holdout 命令（`p2-run` + 两步 `p2-score`）均为 `D:/mktkb-p2-holdout/v2/manifest.json`：该文件存在（1,037 B），sha256 `8874985e…` 与仓库副本**逐字节相同**（`Buffers.equals`=true）。
- 规则与代码一致：`p2-h2-plan` 用仓库副本合法（`p2_holdout_plan.load_holdout_manifest` 普通读），holdout 加载必须 root 内（`p2_dataset.py:541-546`）。只读探针实证：仓库副本 → `holdout_manifest_outside_root`，且该拒绝发生在读 key/密文之前（`evidence/verify/manifest-root-vs-repo.txt`）。
- 引用行号逐个核对通过：`p2_authorization.py:644`、`:472-480`、`p2_dataset.py:539-546`（实际判断在 541-546，区间覆盖）。
- `p2-run-contract` §11.1 为 **additive**（原句 238-250 未动，新增 252-260）；`p2-live-binding` §10.8 描述与代码逐值一致（四核心恒需 / ocr 随计划 / 一致性由 authorize 保证 / 缺核心仍拒）。
- 非阻断文档收口项：runbook §1.1（:26）仍写旧账本基线 `6b053520… (1,050,298 B)`，与当前 `05b54d06…/1,354,211` 不符（正式 R1 运行所致）；同类的 GO 旧基线 `79a5f318…` 出现在 `T207-PM-decisions-01.md` 等他人文档。按任务口径**如实标注、不阻断本包**。

## 6. 测试与合规 —— PASS

- 独立 basetemp 复跑（系统临时目录，`-p no:cacheprovider`，`PYTHONDONTWRITEBYTECODE=1`）：
  `.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_live_wiring.py backend/tests/evaluation/test_p2_runner.py -q --basetemp <tmp>` → **63 passed, 1 warning, 34.68s**（28 + 35，与开发 evidence 的 63 一致；证据 `evidence/verify/pytest-livegate-independent.txt`）。
- 零真实出站：两文件均 `pytestmark = usefixtures("t09_network_guard")`（`acceptance/support/netguard.py:66` 断言外部 socket 尝试=0），live 传输全走 `httpx.MockTransport`；我的验收脚本只调 `open_live_gate/authorize_p2/begin_attempt`，无任何 provider 客户端。
- 我未打开 `.env`/H1/H2；验收脚本的探针只取环境变量名与 manifest 路径（`MKTKB_P2_HOLDOUT_KEY_FILE` 在校验拒绝前不会被读取）。账本/预算/GO 在本进程前后逐字节不变（`pytest-livegate-independent.txt` 记录一次）。
- 未 commit；未改账本/预算/GO；未触碰并行包文件。

## 7. 观察与限制（均非阻断）

1. **门错误文案**：修正后 `live_operation_not_authorized` 只可能因"计划缺核心操作"触发（`authorization.operations ≡ plan.operations`），但文案仍是 `GO 未授权 [x]`，易误导排查方向。文案未变、属既有问题，建议后续顺手改成"计划缺少必需操作"。
2. **报告 §5 行数陈旧**：报告称 `scorers.py` 他人改动 +48 行；我验收时快照为 +81/−7（并行包仍在写）。不影响本包结论。
3. **H2 计划本身不可核**：H2 计划/密文在工作区外，"145 项/158 请求/page_count=0"仅与仓库内生成器预期与 cost-and-quota 文档一致，本次无法对真实 H2 计划复算。
4. **开发 evidence 的 "before==after"** 无法独立回溯，我只能证明"当前值 = 开发记录值"且"我这次运行前后未变"。
5. **并发写入**：验收期间并行包新增改动（`conversations/*`、`copy.py`），故本报告结论锁定在开头列出的 5 个哈希快照上。
6. 本包只修门；H2 真实执行仍受 runner 逐轮核对、ingest 配额、计划/GO 重签等约束，未在本次范围内验证。

## 8. 建议

**接收**。改动最小（一个 `missing` 语句 + 两个公开符号），默认公开计划行为经源码/集合/真实计划三重证明逐字不变，反向保护与"无计划外 OCR 通道"均实证未放宽，runbook manifest 路径修正正确且必要。非阻断项（§7.1 文案、§7.2/§5 文档收口）留给文档收口批或后续小包处理。
