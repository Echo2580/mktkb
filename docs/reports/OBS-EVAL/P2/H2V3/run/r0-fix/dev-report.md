# H2 v3 任务 A：入口透传 delta（B+ 最小接线）开发报告

- 包：`v3-run-r4`（B+ 入口修复 + run0）
- 工作区：`D:\GPT项目\市场部AI知识库`，分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存 **0** 项
- 改动面：**仅 1 个文件** `tools/p2_h2_v3_controlled_execute.py`（v3 入口，本轮新建文件）
- 结论：**修复成立**（根因复现 → 执行层放行 → 负对照仍拒 → check-only 16/16 绿 → run0 真实跑通）；v2 入口与全部 C 冻结件**逐字节未变**

---

## 1. 根因（先读 `run/run-r0-report.md`，本次已在代码里复现）

| 层 | 行为 | 结果 |
|---|---|---|
| check 层 `_contract_validate()` | 冻结契约 `validate_run` 拒后，按 `_authorized_batch_delta` 算出 `authorized_delta`（plan 9 / recipe 8） | `ok=true, code=index_embedding_batches_v3_derived` |
| 执行层 `v2._execute_loaded(contract=bundle.contract)` | 把**冻结契约**交给执行核心 | — |
| `p2_live.build_live_adapter` / `p2_runner.run_p2` | `validate_scenario_execution → contract.validate_run`（`p2_holdout_scenarios.py:205-216`） | 按冻结 `RECIPES` 的 `ingest_batches=8` **逐值重建**计划 → `scenario_plan_mismatch` |
| v2 错误映射 | `scenario_contract_invalid`（`tools/p2_h2_controlled_execute.py:2408-2409`） | 任何网络动作**之前**整 run 被拒 |

即：**check 层算出的 `authorized_delta` 从未到达执行层**。冻结件本身没有问题，缺的是「v3 入口里的一根线」。

## 2. 改动（最小接线，只放宽一格）

四项编辑，全部在 v3 入口内：

1. `from dataclasses import dataclass` → `dataclass, field`；
2. 模块 docstring 的「与 v2 入口的差异」由四处改为**五处**，补上「执行层 delta 透传」一条；
3. `_V3BatchContract` 增加一个 `_authorized` 字段（check 层授权值的逐值副本），并在 `validate_run` 里加两道闸：
   - **无授权** → 仍抛 `scenario_plan_mismatch`（等价冻结契约原始拒绝）；
   - **授权值 ≠ 执行期实测值**（item_id / plan_requests / contract_recipe_requests 任一不等）→ 仍抛 `scenario_plan_mismatch`；
4. 新增 `_execution_contract(bundle, plan, contract_state, scenario)`，把授权三方校验（**授权值 == 计划值 == census 派生值**，且 `derived_from == v3_ingest_batch_census`）通过后才返回「只放宽这一格」的契约子类；`run_command` 里由 `contract=bundle.contract` 改为 `contract=exec_contract`。

关键约束（逐条满足）：

- 未改 `product_adapter.py`、`p2_holdout_scenarios.py`、`p2_holdout_plan.py`、`p2_runner.py`、`p2_live.py`；
- 未改任何 C 冻结 12 对象、v2/v3 语料与密文、评测模块、账本内容、30 题/标签/阈值；
- 「其余逐值相同」由冻结 `validate_run` 自己先跑一遍保证：只有它抛出的**恰是** `scenario_plan_mismatch` 时才进入放宽分支；binding/subset/ingest 任一不符仍按原码拒绝；
- 放宽的**唯一**格子是 `items[index_embedding].requests`，且必须等于 census 派生值。

## 3. 改前 / 改后 SHA（只涉 v3 入口）

| 角色 | 路径 | 改前 SHA-256 | 改后 SHA-256 |
|---|---|---|---|
| v3 入口（唯一改动） | `tools/p2_h2_v3_controlled_execute.py` | `5f9dc3913e8d3aec8a795b40b82a60dd8ff32406cc2d3a42b37b8322d4201812` | `9750eb1823b71340e16f870a68fb05199a48ae123a44aa9ea8e75a584089f269` |
| v2 入口（未改） | `tools/p2_h2_controlled_execute.py` | `ad215251a778352789ece459524f5b7a9e14770af006e9debfdf478df8db70e2` | **同左** |
| 产品适配器（未改） | `backend/src/mktkb/evaluation/product_adapter.py` | `c9378f81088ff3777bd564e43983ecfa37f8889957965e7b6d38b2d35a9f4787` | **同左** |
| 冻结场景契约（未改） | `backend/src/mktkb/evaluation/p2_holdout_scenarios.py` | `bb9ae59a5ff30bfbba259d251b1bbb0e6bb67cd6d50016179bfe97143689178f` | **同左** |
| 冻结计划构造（未改） | `backend/src/mktkb/evaluation/p2_holdout_plan.py` | `d0cb23de2cff80a743c086a8723edd80654d64b22f4e18f97973dd83b153cd25` | **同左** |

`p2_runner.py` / `p2_live.py` 未在改动前后被本包触碰（mtime 分别为 `2026-11-13 01:21:18` / `01:21:35`，远早于本包开工时刻 `2026-11-15 13:57`；v3 入口 mtime 为 `2026-11-15 13:59:28`）。

### 3.1 diff（可自证）

- 完整 unified diff：`r0-fix/evidence/v3-entry-diff.patch`（3 个 hunk、213 行、`a/tools/...` ↔ `b/tools/...`）
- **diff 的可信性有自证**：改前文件已被覆盖，故用「反向替换」从改后文件重建改前版本，重建结果 SHA = `5f9dc391…`，与开工前记录的基线**逐字节相同**（`r0-fix/evidence/rebuild-before.py`、`rebuild-before.stdout.txt`，输出 `match True`）。重建成功 ⇒ 该 diff 就是真实改前→改后差异。

diff 摘要（改后新增）：

```python
@dataclass(frozen=True, repr=False)
class _V3BatchContract(ValidatedScenarioContract):
    _authorized: Mapping[str, Any] | None = field(default=None, repr=False)
    def validate_run(self, plan, dataset, ingest):
        ...  # 先跑冻结 validate_run；只有 scenario_plan_mismatch 才继续
        delta = _authorized_batch_delta(plan, expected, scenario)
        if not delta.get("ok"):            raise ScenarioError("scenario_plan_mismatch")
        if self._authorized is None:       raise ScenarioError("scenario_plan_mismatch")
        # 授权值与执行期实测值逐值比对，不一致即拒
```

## 4. check-only：仍 16/16 绿、`ok=true`

命令（`cwd=仓库根`，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=40`）：

```
python tools/p2_h2_v3_controlled_execute.py check-only \
  --binding <regen-1160c>/bindings/run0-base_b0.binding.json --run-index 0 \
  --plan-set <regen-1160c>/plans --out <r0-fix/evidence/check-only-rebind2.json>
```

| 项 | 值 |
|---|---|
| `ok` / `reasons` | **true** / `[]` |
| 检查 | **16/16 全绿** |
| `contract_validate_run` | `code=index_embedding_batches_v3_derived`、`authorized_delta={plan_requests:9, contract_recipe_requests:8, item_id:ingest-index-embedding}` |
| `production_ready` | **true** |
| 请求已用 / 剩余 | 961 / 199（上限 1160） |
| 本次计划请求 / 最坏金额 | 65 / 0.637568 元 |
| 外部/本地尝试 | **0 / 0** |
| 账本 / 预算 | 前后同值（`ledger_unchanged=true`、`budget_unchanged=true`） |

证据：`run/r0-fix/evidence/check-only-rebind2.json`。

> 说明：check-only 的判定路径**未被本次改动触碰**（`_contract_validate` 一行未改），所以 16/16 的语义与上一轮完全一致，只是 `code_version` 随代码变化。

## 5. 执行层放行/仍拒：零发送离线探针

`r0-fix/evidence/probe-exec-contract.json`（脚本在仓外，只 import 入口、只做内存校验，装 socket 守卫，`external=[] / local=[]`）：

| 场景 | 期望 | 实测 |
|---|---|---|
| ① 冻结契约直接过 `validate_scenario_execution`（`p2_live`/`p2_runner` 的同一入口） | 拒 | **拒** `scenario_plan_mismatch`（根因复现） |
| ② 包装但**不带授权** | 拒 | **拒** `scenario_plan_mismatch` |
| ③ 授权值被篡改回配方值 8 | 拒 | **拒** `scenario_plan_mismatch` |
| ④ check 层 `authorized_delta` → `_execution_contract` | 放行 | **放行**（两次调用均不抛） |

`ok=true`，`exec_contract_type=_V3BatchContract`，`plan_ingest_requests=9`，`census_derived_batches=9`，`plan_sha256=70f8f373…`。

## 6. 重绑：为什么「代码在计划后改动 → 必须重绑」

1. v3 入口把**自身**追加进 v2 的 `CODE_SCOPES`（`_load_controlled_entry()`），因此 `code_digest()` 覆盖本文件；
2. 改代码 ⇒ `code_version` 从 `db3b6050…` 变为 `f2d707f3…`；
3. binding 文档记录 `code_version` 且 `binding_sha256` 覆盖它；`run` 又以 `str(document["code_version"]) != v2.code_digest()` → `code_changed_since_plan` 硬拒；
4. 故必须用官方 `plan-private` 重新签发 binding（`--created-utc 2026-11-15T05:00:00+08:00 --max-requests 1160`，与上一轮**逐值相同**的入参）；
5. **计划字节不受影响**：`code_version` 只进 `config`，不进 plan 文档；实测四份 plan 文件与 `regen-1160b` **逐字节相同**（r0 `c74eb105…`），`plan_sha256` 仍为 `70f8f373…`；
6. 因此 **GO 无需重发**：GO 绑的是 `plan_sha256` / `plan_id` / `max_requests`，check-only 的 `go_binding` 复核 `plan_sha_match=true`、`plan_id_match=true`；
7. 账本/预算全程零写（`ledger_unchanged=true`、`budget_unchanged=true`）。

| 项 | 上一轮（`regen-1160b`） | 本轮（`regen-1160c`） |
|---|---|---|
| `code_version` | `db3b6050…` | **`f2d707f3a88c7b898566e56355c3fc0adf15a8c5e090985749c459725646b018`** |
| run0 binding SHA | `c4e1dd37…` | **`5414fef43819d9329fc19d5fc019798c9b851cfe2889b32232c4f8583a516434`** |
| run0 plan 文件 SHA | `c74eb105…` | **同左（逐字节相同）** |
| run0 `plan_sha256` | `70f8f373…` | **同左** |
| GO 文件 SHA | `215398d1…` | **同左（未重发）** |

## 7. v2 行为完全不变：证据

1. v2 入口文件 SHA 前后**逐字节相同**（`ad215251…`）；
2. `product_adapter.py` / `p2_holdout_scenarios.py` / `p2_holdout_plan.py` SHA 前后相同（见 §3 表）；
3. 本包唯一写入路径是 v3 入口的 `run_command`：`_execution_contract` 只在 `contract_state["authorized_delta"]` 存在时包装；**当计划与 v2 配方逐值相同时（`code is None`）直接返回 `bundle.contract` 本体**，即 v2 路径的对象与行为一个字节都不变；
4. v2 入口的 `plan-private / check-only / run` 三处调用签名未变，未新增/修改任何 v2 参数。

## 8. 边界与纪律

- 未 stage / commit / push；暂存 0 项；未新建 worktree、未切分支；
- 仓内新增仅：`run/r0-fix/**`（本报告 + evidence）、`run/r0/**`（run0 新产物）、`run/run-r0-report-b.md`、`run/r0-attempt2/**`（上一轮逐字节归档）；
- 未把真实 H2 题面/答案/query 文本写入任何仓内产物（本报告只有路径、计数、哈希、固定码）。

## 9. 证据清单（`r0-fix/evidence/evidence-manifest.json` 带哈希）

| 文件 | 内容 |
|---|---|
| `check-only-rebind2.json` | 重绑后 16/16 绿、`ok=true`、零写零发 |
| `probe-exec-contract.json` | 执行层放行 + 三项负对照（零发送） |
| `v3-entry-diff.patch` | 唯一改动文件的 unified diff |
| `rebuild-before.py` / `rebuild-before.stdout.txt` | 改前文件重建与基线 SHA 自证（`match True`） |
| `make-r0-artifacts-b.py` | run0 仓内产物的生成脚本（可复算） |
| `evidence-manifest.json` | 上述文件的字节数与 SHA-256 |
