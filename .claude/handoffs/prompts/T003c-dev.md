角色：开发助手。任务 T003c（P0 第 5 包，RAG 路径 Span 埋点）。工作目录 `D:\GPT项目\市场部AI知识库`，Windows/PowerShell，全新上下文。

第一步：完整读 `.claude\handoffs\T003c-rag-spans\handoff.md`，按「交付物 / 输入 / 允许与禁止 / 验收标准 / 必须实际运行的检查 / 已知约束 / 提交」执行；细节全在该文件，不要扩大范围。T001–T003b 已通过独立验收（`p0/obs-eval` @ `d41d19f`），观测内核与既有测试只读。

开工：`git branch --show-current` 应为 `p0/obs-eval`，HEAD 应为 `d41d19f`；PM 未跟踪文件不要动、不要 commit。先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；Python 用 `.\.venv\Scripts\python.exe -B`；TDD 先红后绿；commit `p0/T003c rag spans`。

本包唯一原则：**不改业务逻辑**。埋点全部走 `current_trace()`；为 None 时 no-op；每处只加最小 `with trace.span(...)` 与 `annotate(...)`，不重构、不改返回结构、不改异常。先读 `observability/tracer.py` 确认条件属性写在哪（`filter_decisions_json`）以及 `annotate` 的启动字段边界。

硬约束：只改 `rag/index.py`、`rag/retrieval.py`、`rag/answer.py`，新增测试与可选 `observability/trace_attrs.py`；不碰 `qa/`/`conversations/`/`main.py`/`config.py`/观测内核/既有测试；不新增依赖；零真实调用、不读 `.env`、不打印凭据；不记录问题/答案原文；不碰 `docs/evidence`/`var`/`fixtures`/账本/GO/归档区；不 push。

证据 `docs\reports\OBS-EVAL\P0\evidence\T003c\`；五段报告 `.claude\handoffs\T003c-rag-spans\report.md`；草稿 `.claude\handoffs\_scratch\T003c\`。

结束时回复末尾给 ≤10 行交接摘要：交付物、§5 八条自证要点（命令或 文件:行）、实际运行结果（commit sha / stat / 全量通过数）、偏离、风险。不要写 review 文件。
