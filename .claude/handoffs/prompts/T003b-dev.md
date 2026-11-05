角色：开发助手。任务 T003b（P0 第 4 包，配置 + 中间件接线）。工作目录 `D:\GPT项目\市场部AI知识库`，Windows/PowerShell，全新上下文。

第一步：完整读 `.claude\handoffs\T003b-wiring\handoff.md`，按「交付物 / 输入 / 允许与禁止 / 验收标准 / 必须实际运行的检查 / 提交」执行；细节全在该文件，不要扩大范围。T001/T002/T003a 已通过独立验收（`p0/obs-eval` @ `dea4d5d`），`observability/*` 只读。

开工：`git branch --show-current` 应为 `p0/obs-eval`，HEAD 应为 `dea4d5d`；PM 未跟踪文件不要动、不要 commit。先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；Python 用 `.\.venv\Scripts\python.exe -B`；TDD 先红后绿；commit `p0/T003b config & middleware`。

硬约束：只改 `config.py`、`main.py` 与新增的 observability 测试文件；不碰 `qa/`/`rag/`/`conversations/`、不改 tracer/store/contracts/versioning、不改既有测试；不新增依赖；不改 API 字段结构（只允许新增 `X-Trace-ID` 响应头）；中间件绝不传 `TraceMode.LIVE`（P0 禁止 live）；零真实调用、不读 `.env`、不打印凭据；测试 DB 只用 tmp_path；不碰 `docs/evidence`/`var`/`fixtures`/账本/GO/归档区；不 push。

证据 `docs\reports\OBS-EVAL\P0\evidence\T003b\`；五段报告 `.claude\handoffs\T003b-wiring\report.md`；草稿 `.claude\handoffs\_scratch\T003b\`。

结束时回复末尾给 ≤10 行交接摘要：交付物、§5 八条自证要点（命令或 文件:行）、实际运行结果（commit sha / stat / 全量通过数）、偏离、风险。不要写 review 文件。
