角色：开发助手。任务 T004b（P0 第 8 包，scorer：值/来源/kind/分页/拒答/检索指标）。工作目录 `D:\GPT项目\市场部AI知识库`，Windows/PowerShell，全新上下文。

第一步：完整读 `.claude\handoffs\T004b-scorer\handoff.md`，按「交付物 / 输入 / 允许与禁止 / 验收标准 / 必须实际运行的检查 / 已知边界 / 提交」执行；细节全在该文件，不要扩大范围。T001–T004a 已通过独立验收；开工先 `git log --oneline -2` 确认 HEAD 为 T004a 收口 commit。

开工：`git branch --show-current` 应为 `p0/obs-eval`；PM 未跟踪文件与 T003d 残留不要动、不要 commit。先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；Python 用 `.\.venv\Scripts\python.exe -B`；TDD 先红后绿；commit `p0/T004b scorer`。

本包实现确定性 `score_case` 与各指标函数：值命中（全角/空格/大小写归一、数字不误配）、来源命中、kind、分页契约、引用精确/召回、拒答三指标（强制分离）、检索指标（Recall@10/MRR@10/nDCG@10/硬过滤违规/空召回，unit 级去重）、延迟与成本字段；输出 `CaseResult` 的逐项 check（稳定 id/status/evidence）。不做 runner/门禁。

硬约束：只新增 `evaluation/scorers.py` 与测试、conftest fixture；不改 dataset/gold/runner/gate/baseline/report、不改业务代码/观测内核/既有测试；不新增依赖；零真实调用、不读 `.env`、不打印凭据；不碰 `docs/evidence`/`var`/`fixtures`/账本/GO/归档区；不 push。

证据 `docs\reports\OBS-EVAL\P0\evidence\T004b\`；五段报告 `.claude\handoffs\T004b-scorer\report.md`；草稿 `.claude\handoffs\_scratch\T004b\`。

结束时回复末尾给 ≤10 行交接摘要：交付物、§5 八条自证要点（命令或 文件:行）、实际运行结果（commit sha / stat / 全量通过数）、偏离、风险。不要写 review 文件。
