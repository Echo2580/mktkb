# T007 独立验收提示词（subagent 版，2026-11-05）

角色：独立验收者（全新上下文）。任务 T007「Baseline + Diff + 报告」，对象 commit `6447b85`。
第一步：完整读 `.claude\handoffs\T007-baseline-report\handoff.md`（§5 六条唯一判定依据、§7 含 T006b 输入约束 5 条）与同目录 `report.md`（只当线索）。
第二步：亲自复跑 + 独立探针。提速策略 A/C：本包 1 次（`test_baseline.py test_report.py`）+ 受影响目录 1 次 + 全量 1 次（基线 1548）；不重跑旧基线；串行。
重点亲测（自己构造 RunResult/baseline，不复用交付测试 fixture）：
- §5.1 `baseline_id = sha256(六字段)[:12]`：同输入稳定；**逐字段**改动（dataset_version/pipeline_version/mode/scope/gate_version/corpus_sha256）都必须变；跨 `pipeline_version` 变 id。
- §5.2 审批：缺 `approver`/缺 `reason` → 报错；门禁 exit 3（未审批阈值）→ 必须拒绝且不落 `approval.json`；exit 0 的 `%TEMP%` 审批配置 → `approval.json` 含 run_id/gate_result_sha256/dataset_version/pipeline_version/corpus_sha256/approver/reason/approved_at；无 copy/rename API。
- §5.3 跨版本：无 `compare_with` → 抛错；显式 → `comparison=explicit_cross_version` 且放行路径拒绝（release_allowed=False / require_release_baseline 抛错）。
- §5.4 diff：new/fixed/still 按 `case_id`；完全相同 → 空列表且 `empty=True`；按 stratum + 总体指标差；gate 0→2 等状态变化有字段。
- §5.5 报告：markdown 首段硬门禁；html 单文件（`<script`=0、外链/`<link`=0、内联 CSS、无服务依赖），与 md 同源；gate 源码不读 report。
- §5.6 测试 42/275/1548；`git show --name-status 6447b85` 只含 handoff §2 允许路径（9 文件）；无 gate/runner/scorer/dataset/既有测试/conftest 改动；`gate_v0_1.json` 未被本包改动（仍 unapproved、阈值空）。
- 变异探针（仓库外）：如让 id 忽略 `corpus_sha256`、让审批跳过 gate、让跨版本放行、让 html 引入外链，对应探针/测试必须翻红。
证据：`docs\reports\OBS-EVAL\P0\evidence\verify\T007\`（≤3 份 + 1 探针，UTF-8 无 BOM、ASCII 文件名）；结论写 `.claude\handoffs\T007-baseline-report\review.md`（≤120 行）。
不改交付物、不 commit、不 push、不读 `.env`、零真实调用；临时文件只进 `%TEMP%`；不覆盖 `evidence/T007/`。
回复末尾 ≤10 行：总判定 + §5 各条 + 失败项 + 未覆盖 + 对 T008a/T008b 的输入约束（CLI 依赖的 API、真实 baseline 缺失的影响）。
