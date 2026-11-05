# T006a 独立验收提示词（subagent 版，2026-11-05）

角色：独立验收者（全新上下文）。任务 T006a「门禁硬层（8 项）+ 退出码」，对象 commit `f6bb3c4`。
第一步：完整读 `.claude\handoffs\T006a-gate-hard\handoff.md`（§5 六条是唯一判定依据，§5.4/§5.5 含 PM 裁决、§7 含 T005 输入约束）与同目录 `report.md`（只当线索）。
第二步：亲自复跑 + 独立探针。提速策略 A/C：本包 1 次（`test_gate.py`）+ 受影响目录 1 次（`backend/tests/evaluation`）+ 全量 1 次（基线 1469）；不重跑旧基线；串行。
重点亲测（全部自己构造 RunResult/RunManifest/trace，不要只调包内测试）：
- 8 项硬门禁逐项：构造失败样本 → 命中正确 ID → exit 1；每项至少 1 个**独立**样本（不抄交付测试的 fixture）。
- 退出码：0（干净 run）、1、3（min_sample 不足 / gold 不可解析 / error 行）、4（`mode=live`，且不依赖内核拒绝）；2 无触发路径。
- trace_integrity：`reason=trace.reason` 生效（构造 `KNOWLEDGE_CHANGED_AT_COMMIT` 少 retrieve 应过、`DOCUMENT_NOT_FOUND` 少 recall 应过、未知 reason 应仍要求 retrieve）；`status=replayed` 跳过 path/outcome 与 Span 校验但版本/JSON 仍校验；`*_json` 非法 JSON fail closed；schema 版本漂移 fail。
- PM 裁决口径：无该类 case → `not_applicable` 且不影响退出码；有 case 缺字段 → `unknown`→3；min_sample 分母 `scored_count`（b0=32 不含 8 OCR、badcase 用 10 而非 13）；`value_no_fabricated` 未参与硬门禁；`citation_required` 不靠 `source_hit`；`security_leak` 的 forbidden 引用按 unit 映射（unit_ids-only 引用 + unit_key forbidden 应命中）；`record_code`-only / `record_code`+空 locator → 3。
- 越界检查：不得实现质量层/`calibrate_gate`/waiver/`max_regression_pp`/exit 2 触发；`gate_v0_1.json` 阈值必须为空且 `status=unapproved`。
- 提交边界：`git show --name-status f6bb3c4` 只含 handoff §2 允许路径（8 文件）。
- 变异探针（仓库外）：如让 `required_spans` 少一项、让 replayed 不跳过、让 min_sample 用 40、让 live 放行，对应测试/探针必须翻红。
证据：`docs\reports\OBS-EVAL\P0\evidence\verify\T006a\`（≤4 份 + 1 探针，UTF-8 无 BOM、ASCII 文件名）；结论写 `.claude\handoffs\T006a-gate-hard\review.md`（≤120 行）。
不改交付物、不 commit、不 push、不读 `.env`、零真实调用；临时文件只进 `%TEMP%`。
回复末尾 ≤10 行：总判定 + §5 各条 + 失败项 + 未覆盖 + 对 T006b 的输入约束。
