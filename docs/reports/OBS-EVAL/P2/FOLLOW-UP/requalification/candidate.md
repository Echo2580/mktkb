# P2 收尾 · 修复候选清单（v2）

- 日期：2026-11-21（Asia/Shanghai）｜仓库 `D:\GPT项目\市场部AI知识库`｜分支 `codex/p2-e2e`｜HEAD `93486b6`
- 性质：**开发自测 + 只读复核**。本轮真实模型 0、OCR 0、外网 0、费用 0。
- 证据：[`evidence/candidate-inventory.json`](evidence/candidate-inventory.json)（逐文件 SHA-256/字节、漂移分类、冻结件复核）
- 相对 v1 的唯一字节差异：`test_p2_fu2_derive_cards.py`（FU-2 目录依赖最小修正）

## 1. 一句话

候选 = **原 HEAD `93486b6` + 工作树未提交改动**；产品代码/测试/门禁接线 19 个文件 + 本地启动器 3 个 + 簿记 2 个；
流水线摘要从被准入的 `28aae43c…` 变为 **`13a962ed…`**，因此新 B0 必须重新登记（这正是 12 条集成失败的唯一原因）。

## 2. 候选文件（字节与 SHA-256 以 `evidence/candidate-inventory.json` 的 `candidate_fingerprint_v2` 为准）

### 2.1 产品代码 / 测试（7 改 + 6 新 + 1 漂移）

| 文件 | 状态 | 改后 SHA-256（前 12） | 字节 |
|---|---|---|---|
| `backend/src/mktkb/evaluation/product_adapter.py` | modified（FU-1） | `d3bd4d8961bd` | 117714 |
| `backend/src/mktkb/evaluation/p2_runner.py` | modified（FU-1） | `8c7fc54c3012` | 125075 |
| `backend/src/mktkb/evaluation/p2_release_gate.py` | modified（FU-3） | `7cf2cfe797a9` | 28011 |
| `backend/src/mktkb/evaluation/p2_release_provenance.py` | **new**（FU-3） | `c309f8994490` | 25492 |
| `backend/src/mktkb/evaluation/p2_safe_output.py` | **new**（FU-4） | `1d3b29bd5104` | 11673 |
| `backend/src/mktkb/live_authorization.py` | modified（**漂移项，v1 未收录**） | 见证据 JSON | 见证据 JSON |
| `backend/src/mktkb/evaluation/p2_release_inputs.py` | modified（**门禁基线重新登记**，本轮） | 见证据 JSON | 39105 |
| `tools/p2_h2_v3_controlled_execute.py` | modified（FU-2） | `b5a20caf32f1` | 145068 |
| `tools/p2_h2_controlled_execute.py` | modified（FU-4） | `6cfcb724da36` | 151498 |
| `backend/tests/evaluation/test_p2_fu1_index_binding.py` | new | `3eac899b113a` | 20046 |
| `backend/tests/evaluation/test_p2_fu2_derive_cards.py` | new（**本轮再改**） | 见证据 JSON（v1 `bc55fcf7…`） | 见证据 JSON |
| `backend/tests/evaluation/test_p2_fu3_provenance.py` | new | `c1193d1827c0` | 25844 |
| `backend/tests/evaluation/test_p2_fu4_safe_output.py` | new | `ab6007617654` | 13858 |
| `backend/tests/evaluation/test_p2_runner.py` | modified（FU-1 断言口径） | `cee84def437a` | 84174 |
| `backend/tests/evaluation/test_p2_live_wiring.py` | modified（+64 行 live 绑定用例） | `a3f4a44e90d4` | 76420 |

### 2.2 漂移项（v1 指纹之外，开工时现场登记；文件全部保留、未回退）

| 文件 | 分类 | 是否影响新候选 / 真实运行身份 |
|---|---|---|
| `backend/src/mktkb/evaluation/p2_release_inputs.py` | **门禁基线重新登记** | **不影响** `pipeline_source_sha256`（不在覆盖集内，已复核仍为 `13a962ed…`）。把「已登记 B0 基线」从 `7981d4afc2d1` 换成新接收的 `2b40ee9b4740`（含三份登记件摘要）；**判据未改**：批准配置、八项硬门禁、分母与阈值、旧门禁快照与旧基线原件全部原样。 |
| `backend/tests/evaluation/test_p2_release_gate_fixtures.py` | 门禁夹具跟随 | 改从上面的常量取基线 id / run id（不再写死旧基线），只改测试写法。 |
| `backend/tests/evaluation/test_p2_release_gate_negative.py` | 门禁负例跟随 | 假登记目录名同样改用常量；断言语义未变。 |
| `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/wire_real_ncu.py` | 门禁接线跟随 | `b0` 块改用同一组常量；不涉及判据。 |
| `frontend/e2e/acceptance-07-update.spec.ts` | 浏览器断言跟随 | `knowledge_changed` 断言改为 `copy.KNOWLEDGE_CHANGED` 的完整新句（更严）；修复前该条因断言过期失败，修复后 29/29。 |
| `backend/src/mktkb/live_authorization.py` | **产品代码** | **影响**：在 `backend/src/mktkb/*.py` 内，**改了 `pipeline_source_sha256`**；新增 `S2-OWNER-ACCEPTANCE` 阶段与 GO 请求窗口基线。对 `S2-LIVE-GO` 路径行为等价（固定路径分支未变、`request_baseline` 默认 0），但**必须计入候选并重新登记 B0**。 |
| `tools/start_local.py` | 本地启动器 | **不影响** `pipeline_source_sha256`（不在产品包内）。影响：本地实例的 `--offline/--owner-live/--check-only` 模式、亲验单实例锁、`PYTHONPATH` 修正。 |
| `一键启动.cmd` | 本地启动器 | 改为 `--offline`：零出站离线演示，**不产生真实调用**。 |
| `启动-真实问答.cmd` | 本地启动器 | 改为 `--owner-live` + `S2-OWNER-ACCEPTANCE`（项目上限 100、阶段 10、106 次、单请求上界 2.103552）：**这是一条真实调用入口**，与 B0 流程分开，消耗共享账本的 `S2-OWNER-ACCEPTANCE` 阶段。 |
| `.claude/handoffs/_index.md` | 簿记 | 开工前既有追加（mtime 早于本轮），不计入候选。 |
| `docs/reports/OBS-EVAL/P2/T207-QUALITY-REPAIR/manager.md` | 簿记 | 同上。 |

> 结论：**产品代码漂移只有 `live_authorization.py` 一项**，已计入候选；本地启动器 3 项单列，
> 不改产品包字节，但其中 `启动-真实问答.cmd` 是真实调用入口，另需授权才可使用。

## 3. 候选身份

```
pipeline_source_sha256   = 13a962ed103e18ec775de9f0f2764af2a2de325392df1194b09c76932814f4e4
product_pipeline_version = d3ca88d2c515
新 B0 的 pipeline_version = d3ca88d2c515 + 13a962ed…
被准入（旧 B0 7981d4afc2d1）= d3ca88d2c515 + 28aae43c…
```

`pipeline_source_sha256()` 覆盖 `backend/src/mktkb/*.py` + 全部子包（`evaluation` 例外：只含
`p2_live/p2_runner/product_adapter/p2_ingestion` 四支）。因此 `live_authorization.py` 的改动**必然**
改变摘要；本轮 `test_p2_fu2_derive_cards.py` 的测试修正**不**改变摘要。

## 4. 原冻结件复核（只读）

| 项 | 结果 |
|---|---|
| 冻结工件（`candidate-freeze.json` → 47 项） | 对 **`93486b6` blob**：**47/47 摘要+字节一致**（缺失 0、不符 0） |
| 同上，对**当前工作树** | 44/47 一致；3 项差异 = `p2_release_gate.py`、`p2_h2_controlled_execute.py`、`p2_h2_v3_controlled_execute.py`，均属本轮修复面，**无意外差异** |
| 台账前缀 `records_append_only`（2 项） | **2/2 前缀摘要一致**；两文件已按追加增长（16145→19594、21633→22440 字节） |
| 批准配置 `docs/evaluation/gate_v0_3_approved.json` | 一致（`b1094cc7…`） |
| 正式门禁结果 `CROSS-SCENARIO-GATE/gate-result.real-ncu.json` | 一致（`d4c98f92…`，`decision=pass`，38/0/9） |
| B0 准入 `var/eval/baselines/7981d4afc2d1/b0-admission.json` | 文件字节未改；规范化 payload 摘要 = 冻结记录 `2226fa20…`（**一致**） |
| 指纹改前摘要（7 个 modified 的 HEAD blob） | **7/7 一致**（`before_mismatch=0`） |
| `candidate.patch` | 未重新生成（v1 补丁对应 v1 指纹；本轮改动请以指纹 JSON 为准，不用补丁重建） |

## 5. 隔离重建方式（供独立复核复现）

```powershell
# 1) 干净检出（非破坏性，不动当前工作树）
git worktree add --detach D:\mktkb-candidate-93486b6 93486b6

# 2) 应用候选字节：按 evidence/candidate-inventory.json 的 candidate_fingerprint_v2 逐文件复制/写入
#    （14 个产品/测试文件；不要用 candidate.patch —— 它在 p2_release_gate.py 上有行尾归一问题）

# 3) 复核
.\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\FOLLOW-UP\requalification\evidence\scripts\requalify_offline.py --out <out.json>
```

## 6. 允许纳入 / 不纳入

- **纳入候选**：§2.1 的 19 个产品/测试/门禁接线文件（字节以 [`candidate-freeze.v0_3.json`](candidate-freeze.v0_3.json) 为准）。
- **单列（需主人决定是否随交付）**：§2.2 的 3 个本地启动器 + 2 个簿记件。
- **不纳入**：`var/**`（运行数据）、`docs/evidence/**`（账本/GO）、`docs/reports/OBS-EVAL/P2/FOLLOW-UP/**` 之外的
  历史证据目录、`.claude/handoffs/**`、`%SystemDrive%/`（历史遗留怪目录，mtime 2026-11-11/12，与本案无关）。
- **禁止区零改动已复核**：`gate.py`、`p2_b0.py`、`p2_release_public.py`、`evaluation/cli.py`、
  `docs/evaluation/gate_v0_3_approved.json`、`candidate-freeze.json`、`var/**`。
