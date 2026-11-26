# FU-1 开发自测报告 · 通用 P2 入口绑定实际 RAG 索引版本

日期：2026-11-21（Asia/Shanghai）｜分支 `codex/p2-e2e`｜基线 HEAD `93486b6590c6542f34dd70d20a19b792c659f416`
开发自测（非独立验收）。零真实模型 / OCR 调用，零新增费用。

## 1. 复现（改前，冻结候选上实测）

合成夹具（"发布导致版本变化"代表场景）：先用 `fixtures/acceptance/variants/V03_物品位置表_历史V1.xlsx`
灌一版，再以 `document_ref` 把 `fixtures/acceptance/normal/D01_物品位置表.xlsx` 作为同一资料的**新版本**发布，
再灌 `D04_活动策划流程.docx`。用**通用 P2 入口**（`run_p2` + `ProductEvalAdapter` Mock 链 + 批准门禁配置）跑
2 题（RAG 轮 + legacy 轮），再走 `build_gate_run` / `evaluate_p2_hard_gates`。

改前实测（日志 [`evidence/repro-before-fix.log`](evidence/repro-before-fix.log)）：

| 观测 | 值 |
|---|---|
| 产品资料发布版本 `product_revision()` | **3** |
| RAG 索引版本 `index_status()["index_revision"]`（= trace 口径） | **4** |
| `run_manifest.json` 绑定的 `index_revision` | **3**（错：产品计数） |
| RAG 轮 trace `index_revision` | 4 |
| legacy 轮 trace `index_revision` | 3 |
| 硬门禁 | `trace_integrity = fail`，`check_id = version_binding`，`mismatched = ["index_revision"]` |

即：通用入口把**产品资料发布版本**当成索引身份，而 RAG 检索器把 `rag_meta.revision` 写进 trace，
两个同名计数器必然不等 → 每个走过 RAG 的轮次机械失败。B0 路径当时已正确（`_b0_ready_revisions` 取索引版本），
所以缺陷只在通用路径，B0 兼容性不受影响。

命令（冻结候选干净检出 `D:\mktkb-clean-93486b6`，同一夹具）：

```
cd D:\mktkb-clean-93486b6\backend
D:\GPT项目\市场部AI知识库\.venv\Scripts\python.exe -m pytest tests/evaluation/test_zzprobe_fu1.py -q -s
```

（探针文件仅用于复现，已在交付前删除；输出见上表与日志。）

## 2. 修复

| 文件 | 改动 | 说明 |
|---|---|---|
| `backend/src/mktkb/evaluation/product_adapter.py` | 新增 `binding_index_revision()`；`binding_components()` 两个分支的 `index_revision` 改用它 | 唯一来源 = `QaIndexStatus.index_revision`（内部 `rag_meta.revision`，与 trace 同源）；索引未就绪/读数非法 → `None`（缺证，不猜）；产品资料发布版本仍由 `product_revision()` 按自身用途记录 |
| `backend/src/mktkb/evaluation/p2_runner.py` | 新增停止码 `index_changed`；通用（非 B0）路径每轮前后各做一次漂移守卫；`_current_index_revision` / `_index_revision_drifted` | 同一测量窗口内索引版本漂移或读数丢失 → `aborted / index_changed`（`index_before_turn` / `index_after_turn`），不把混合版本 run 记成成功；B0 仍用原 `b0_index_changed` 语义 |

未改：`gate.py`（不做"改门禁让它过"）、`p2_b0.py`（B0 口径本来就对）、冻结工件、`var/**`、GO/账本。

## 3. 正反例（全部通过；从仓库根运行）

```
.\.venv\Scripts\python.exe -m pytest backend\tests\evaluation\test_p2_fu1_index_binding.py -q
→ 5 passed, exit 0
```

| 用例 | 断言要点 | 结果 |
|---|---|---|
| `test_generic_entry_binds_actual_rag_index_revision` | 夹具确实 产品 3 / RAG 4；`manifest.index_revision == binding.index_revision == 4 != 3`；config_hash 可由组件确定性重算；RAG/legacy 两类 trace 都是 `4`；`trace_integrity = pass`、无 `version_binding` | PASS |
| `test_generic_entry_binding_hash_is_deterministic` | 同输入两次运行 → `index_revision`/`config_hash` 完全相同 | PASS |
| `test_generic_entry_fails_on_real_misbinding` | 把 manifest 改回产品计数 3、以及任意错值 5 → `trace_integrity = fail` + `version_binding`（`index_revision` 在 `mismatched` 内）+ 非 0 退出码，不降级 | PASS |
| `test_generic_entry_keeps_binding_incomplete_when_index_version_unavailable` | `index_status().ready=False` → `index_revision=None`、`binding.complete=False`、`trace_identity_bound=False`、trace 身份字段不写半套；manifest 缺 `index_revision` 时 `build_gate_run` 直接 `run_manifest_incomplete` 拒绝 | PASS |
| `test_generic_entry_stops_when_index_drifts_mid_run` | 首轮后改动索引 → `aborted / index_changed`、`stage=index_after_turn`、只发 1 轮、`requests.jsonl` 仅 1 行 | PASS |

真实模式（隔离 Mock 传输，零外发）覆盖：`backend/tests/evaluation/test_p2_live_wiring.py::test_live_mode_binds_actual_rag_index_revision`
—— 产品 2 / RAG 3，`manifest.index_revision == binding.index_revision == index_status().index_revision`，
`outbound_network == 0`；`test_p2_live_wiring.py` 全套 34 passed。

B0 兼容：`backend/tests/evaluation/test_p2_b0.py` 全绿；B0 既有用例（`manifest.index_revision == 4`、
漂移停 `b0_index_changed`）逐值不变；B0 注册工件 `var/eval/baselines/7981d4afc2d1/*` 未改动（字节与干净检出相同）。
改后同夹具实测（[`evidence/after-fix.log`](evidence/after-fix.log)）：产品 3 / manifest 4 / 两条 trace 均 4 /
`trace_integrity = pass` / 硬失败 0。

历史 run 与批准配置摘要：未重写任何历史 trace/manifest；旧 run 的绑定值原样保留（D-005 绑定适用性证明口径不变）。

## 4. 关键发现（需主人决定，非代码缺陷）

`pipeline_source_sha256()` 显式包含 `evaluation/p2_runner.py`、`product_adapter.py` 等文件，因此**任何** FU-1 修复
都会改变候选流水线摘要：

| 口径 | 值 |
|---|---|
| 冻结候选 `93486b6`（干净检出） | `28aae43c4696db2bfdfd440bf974cdec5392c8c732314366a91407fb1f5ee8e7` |
| 本修复树 | `2aa9177b96fca93446cecc17a82ba0ecd5f89bd0e179fa3cd32b5ea5c4b61a8b` |
| 已登记 B0 admission 绑定值 | `28aae43c…`（`var/eval/baselines/7981d4afc2d1`，未改动） |

后果：发布门禁的 `candidate.pipeline` 行在**修复树**上必然 `blocked`（`release_version_mismatch`），这是"候选字节
与 B0 准入不一致"的版本门，不是 FU-1 缺陷。放行需按任务书 §6.4：新候选完成受影响项独立定向复验 → 重新冻结
（含重新建立 B0 准入）→ 主人确认。原冻结候选 `93486b6` 的同一套门禁用例在干净检出 + 已获准本地材料下
15/15（positive + real_ncu）、27/27（negative）通过，作为基线保留。

## 5. 未覆盖 / NOT-RUN

- 真实模型/OCR 链路的绑定：`NOT-RUN`（零真实调用约束）。
- 新候选的 B0 重新准入：`NOT-RUN`（需授权真实 B0 执行与新 GO）。
- 30 题/全量矩阵：不在本项范围。

## 6. 证据

| 文件 | 说明 |
|---|---|
| [`evidence/repro-before-fix.log`](evidence/repro-before-fix.log) | 冻结候选上的改前复现输出（产品 3 / manifest 3 / trace RAG 4 / version_binding fail） |
| [`evidence/after-fix.log`](evidence/after-fix.log) | 修复树同夹具输出（manifest 4 / 两条 trace 4 / pass） |
| [`candidate-fingerprint.json`](../candidate-fingerprint.json) | 改动文件改前/改后 SHA-256 与字节数 |
