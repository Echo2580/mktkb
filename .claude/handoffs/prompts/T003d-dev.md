角色：开发助手。任务 T003d（P0 第 6 包，QA/legacy 路径 Span 与 outcome 绑定）。工作目录 `D:\GPT项目\市场部AI知识库`，Windows/PowerShell，全新上下文。

第一步：完整读 `.claude\handoffs\T003d-paths\handoff.md`，按「交付物 / 输入 / 允许与禁止 / 验收标准 / 必须实际运行的检查 / 已知边界 / 提交」执行；细节全在该文件，不要扩大范围。T001–T003c 已通过独立验收；开工先 `git log --oneline -2` 确认 HEAD 为 T003c 收口 commit。

开工：`git branch --show-current` 应为 `p0/obs-eval`；PM 未跟踪文件不要动、不要 commit。先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；Python 用 `.\.venv\Scripts\python.exe -B`；TDD 先红后绿；commit `p0/T003d qa legacy spans`。

本包只做接线：设 `request_id/question/path/outcome`，在 legacy 路径补 `intent_parse/retrieve/query_expansion/model_answer/answer_validate/commit` Span，RAG 路径 outcome 从 `RagAnswer.kind` 映射；**不改业务算法、不改响应结构、不改异常语义**；`current_trace()` 为 None 时全部 no-op。

硬约束：只改 `qa/service.py`、`conversations/service.py` 与新增测试；不碰 `rag/**`、`main.py`、`config.py`、观测内核、既有测试；不新增依赖；零真实调用、不读 `.env`、不打印凭据；不写问题/答案原文；不碰 `docs/evidence`/`var`/`fixtures`/账本/GO/归档区；不 push。

证据 `docs\reports\OBS-EVAL\P0\evidence\T003d\`；五段报告 `.claude\handoffs\T003d-paths\report.md`；草稿 `.claude\handoffs\_scratch\T003d\`。

结束时回复末尾给 ≤10 行交接摘要：交付物、§5 八条自证要点（命令或 文件:行）、实际运行结果（commit sha / stat / 全量通过数）、偏离、风险。不要写 review 文件。
