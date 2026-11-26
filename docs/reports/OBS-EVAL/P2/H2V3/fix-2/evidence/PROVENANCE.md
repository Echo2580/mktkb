# fix-2 证据来源与复算路径（PROVENANCE）

## 1. 复现口径

- **改前**：`run_prestate_probe.py` 把 `rag/query.py`（5 处）与 `rag/answer.py`（1 处）的编辑**反向替换**到临时目录，
  逐文件 SHA-256 校验等于上一轮收尾值（`reconstructed-pre-round.json` 的 `all_match=true`），再在该 PYTHONPATH 下跑探针。
  因此"改前"是可复算的重建值，不是声明值。正向重放也已机检（`fix-sha.json` 的 `forward_replay_identical=true`）。
- **改后**：同一探针脚本、同一输入，直接对工作区源码运行。
- 探针只调用产品纯函数（`mktkb.rag.query.parse_query`、`conversations.service._rag_ownes_turn` 与临时 `RagIndex`），
  不建产品库、不调模型/embedding/rerank、不开端口。

## 2. 封存证据（只读、只取结构化字段）

- 输入：`D:\mktkb-p2-h2v3-20261115` 下 4 份 `case-plan.json` + 30 份 `turn-*.fernet` + `runs3/ev.key`，
  以及仓内 `regen-1160c/bindings/*.binding.json`（用于 `load_v3_bundle` 逐值校验）。
- `probe_observed_cases.py` 抽取白名单字段：`path / mode / filters / as_of / include_future / enumerate /
  clarification / state_keys / state_as_of / state_pending_slot / state_last_kind / answer_result.{kind,reason,
  candidates,conflicts,missing_fields,error_code,source_ids} / direct_rag_answer.{kind,reason,answer_source,
  cited_unit_ids,fact_count,state_keys} / commit_observed.kind / retrieval_observed.{scope,empty,candidate,truncated}
  / query_states[-1].state_json 的槽位`。
- **不抽取**：`question`、`query_text`、`terms`、`model_output.text`、`answer_result.text`、`direct_rag_answer.text`、
  `facts`、`db_projection.messages`。因此本目录不含任何真实题面/答案/query 文本。

## 3. 未执行项

- 未运行真实 H2 五题（不读题面）；未重跑 v3 四 run；未生成组合卡。
- 未改 `backend/src/mktkb/evaluation/**`、`p2_holdout_scenarios*.py`、语料与密文、C 冻结 12、账本/GO/预算、30 题/标签/阈值。
- 未 stage / commit / push；未新建 worktree / 切分支。

## 4. 复跑命令（全部零真实调用）

```powershell
# 1) 改前复现（反向重建 + 探针）
.\.venv\Scripts\python.exe docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence/run_prestate_probe.py `
  probe_repro.py repro-pre.json docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence/netguard-repro-pre.json

# 2) 改后复现（带零调用守卫与四正对照）
.\.venv\Scripts\python.exe docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence/netguard_script.py `
  docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence/netguard-repro-after.json `
  docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence/probe_repro.py repro-after.json

# 3) 对照表 / 回归汇总 / 保全 / SHA
.\.venv\Scripts\python.exe docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence/build_repro_summary.py
.\.venv\Scripts\python.exe docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence/build_regression_summary.py
.\.venv\Scripts\python.exe docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence/preservation_snapshot.py
.\.venv\Scripts\python.exe docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence/build_fix_sha.py

# 4) 测试（在 backend/ 下）
..\.venv\Scripts\python.exe -m pytest tests/unit tests/rag -q
..\.venv\Scripts\python.exe -m pytest tests/integration tests/observability -q
..\.venv\Scripts\python.exe -m pytest tests/acceptance -q
```

## 5. 局限

- 本目录所有"结局"都是**合成输入**或**封存证据结构化字段**；真实题面未读，故"5 题是否翻 pass"不在本包结论内。
- netguard 只证明本进程没有外部出站，不覆盖外部进程；回环放行并计数（Windows 上 pytest/anyio 用 socketpair）。
