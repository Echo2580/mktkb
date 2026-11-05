# T005 独立验收提示词（subagent 版，2026-11-05）

角色：独立验收者（全新上下文，无开发会话历史）。任务 T005「Replay / Local Runner + 运行清单」，对象 commit `80fd092`。
第一步：完整读 `.claude\handoffs\T005-runner\handoff.md`（§5 六条是唯一判定依据、§6 必跑命令、§7 已知边界）与同目录 `report.md`（开发自述，只当线索）。
第二步：亲自复跑 + 独立探针，逐条 PASS/FAIL/BLOCKED/NOT-RUN；提速策略 A/C：本包 1 次（`test_runner.py`）+ 受影响目录 1 次（`backend/tests/evaluation`）+ 全量 1 次（`backend/tests`，基线 1397）；**不重跑旧基线全量**。
重点亲测：
- 三件套两模式两 suite 真实产出；`cases.jsonl` 行数与数据集一致、含 skipped 与空 gold；每行 checks/trace_id。
- manifest 版本字段齐全且两次 local run 身份字段一致；`dataset_sha256`/`corpus_manifest_sha256` 与文件实测一致。
- 零真实调用：自己插桩（provider spy=0、socket guard）复核，不要只看它的测试。
- replay：不建索引、不调 provider（可 monkeypatch 制造"若调用就爆炸"），逐 case checks/metrics 与 local 一致；`replay_from=None` 显式报错。
- unit 级：`unit_ids` 来自真实 `RagChunk`/`RagUnit`（抽查 2–3 条与索引比对），replay 重建后 Recall/MRR/nDCG 一致；OCR 不入分母；`record_code`-only gold fail closed。
- 报告声称的 b0 3 个 fail（Q25/Q26/Q31）是否真实、是否与 runner 无关（用同一数据集直接 `RagIndex.ask` 复核 1 条即可）。
- 提交边界：`git show --name-status 80fd092` 只含 handoff §2 允许路径；`conftest.py` 未被修改（允许追加，但本包声称未改）。
证据：`docs\reports\OBS-EVAL\P0\evidence\verify\T005\`（≤3 份 + 1 探针，UTF-8 无 BOM、ASCII 文件名）；结论写 `.claude\handoffs\T005-runner\review.md`（≤120 行）。
不改交付物、不 commit、不 push、不读 `.env`、零真实模型/OCR/embedding/rerank 调用；临时文件只进 `%TEMP%`；串行执行。
回复末尾给 ≤10 行结论摘要（总判定 + 失败项 + 未覆盖项 + 对 T006a 的输入约束）。
