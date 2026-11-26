# fix-1r1 证据来源与口径（PROVENANCE）

- 角色：v3-fix-1/R1（普通开发）。
- 仓库：`D:\GPT项目\市场部AI知识库`；分支 `codex/p2-e2e`；HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`。
- 输入口径：全部问句为合成句；记录为合成行（门店/物品/位置/电话），只写入 pytest `tmp_path` 或 `tempfile.mkdtemp()` 的一次性 SQLite。**未读取真实 H2 题面/答案、未解密、未碰 v2/v3 密文与语料、未跑真实 run。**
- 改前基线：`docs/reports/OBS-EVAL/P2/H2V3/fix-1/independent/_reconstructed_query.py`，由独立验收从工作树逐字节反向删除 fix-1/A 追加块得到，SHA-256 `5a7ed26b73a3ab658deff6384b5fdcc67596860345153cec4ec4f72cb350e1e1`（`probe_planner_r1.py` 只读加载，不复制、不改写）。
- `planner-before.json`：在本次 R1 改动**之前**运行 `probe_planner_r1.py` 生成；当时 `query.py` SHA-256 `f73fc735…`（= fix-1/A）。
- `planner-after.json`：在本次 R1 改动**之后**运行同一脚本生成；`query.py` SHA-256 `82776def…`。
- `before-after-summary.json`：只读上面两个 JSON 的紧凑对照（不重新执行）。
- `fix-r1.diff`：本轮修复 diff。`reconstruct_pre_r1.py` 按行块反向删除本轮追加内容重建改前文件，重建哈希与改动前实测值逐字节相同（`query.py` `f73fc735…`、`test_paths_e2e.py` `d357fdc3…`），用于自证“本轮只改了这些块”。
- `probe_A_multi_target_reuse.py` / `independent-probe-reuse-after.json`：独立验收自带探针的只读复用；仅改输出文件名，未改用例、期望或判定逻辑；运行结果为 `failures=[]`（13/13）。
- 网络口径：
  - 探针导入即删除全部代理环境变量（含大小写变体）；`socket.connect/connect_ex/create_connection/getaddrinfo` 外部出站一律拦截并计数，回环放行并计数。
  - 正对照：DNS、直连（192.0.2.1）、`urllib`（`ProxyHandler({})`）、`httpx`（`trust_env=False`）；四者均 blocked，`external_attempts_during_session=0`。
  - `netguard_plugin.py` 复制自 `fix-1/evidence/`（同一实现），用于 pytest 会话级零调用证据；`netguard-targeted-run.json` / `netguard-unit-rag-run.json` 为两次运行的结果。
- 保全口径：`preservation-after.json` 复用独立验收 `preservation_snapshot.py` 只哈希（不打印内容）；`preservation-compare.json` 与 `fix-1/independent/00-snapshot-end.json` 对照。C 冻结 12 / `p2_holdout_scenarios.py`·`_v3` / 预算·账本·GO / 外部 v2·v3 密文与语料 / `fixtures/acceptance-h2v3` 全树哈希一致；v3 冻结 32 仍 30/32，缺件与改前同一组。
- Git：未 stage / 未 commit / 未 push；新增测试与证据均为未跟踪文件。
