角色：开发助手。任务 T004a（P0 第 7 包，评测数据集 + gold 解析 + fixtures）。工作目录 `D:\GPT项目\市场部AI知识库`，Windows/PowerShell，全新上下文。

第一步：完整读 `.claude\handoffs\T004a-dataset\handoff.md`，按「交付物 / 输入 / 允许与禁止 / 验收标准 / 必须实际运行的检查 / 已知边界 / 提交」执行；细节全在该文件，不要扩大范围。T001–T003d 已通过独立验收；开工先 `git log --oneline -2` 确认 HEAD 为 T003d 收口 commit。

开工：`git branch --show-current` 应为 `p0/obs-eval`；PM 未跟踪文件与 T003c 并发残留不要动、不要 commit。先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；Python 用 `.\.venv\Scripts\python.exe -B`；TDD 先红后绿；commit `p0/T004a eval dataset`。

本包三件事：① `CaseSpec` 校验/加载/`dataset_version`；② `resolve_gold`（稳定引用→unit，0/多匹配 fail closed）；③ 构建脚本把 B0 40 题与 BadCase 13 题转成 `fixtures/evaluation/{b0,badcase}.jsonl`，并用"离线索引真实解析"证明 gold 可定位（B0 非 OCR 32 题 + badcase 13 题）。

硬约束：不改冻结 `fixtures/acceptance/**`、不改 `docs/evidence/**`（只读）、不改业务代码/观测代码/其它 evaluation 模块；不新增生产依赖；零真实模型/OCR/embedding/rerank 调用、不读 `.env`、不打印凭据；B0 的 8 道 OCR 题标 `requires_ocr=true` 且不得触发真实 OCR；无法解析的 gold 必须报错或在报告中逐条列出并经 PM 裁决，不得静默丢弃；不碰 `var`/账本/GO/归档区；不 push。

证据 `docs\reports\OBS-EVAL\P0\evidence\T004a\`；五段报告 `.claude\handoffs\T004a-dataset\report.md`；草稿 `.claude\handoffs\_scratch\T004a\`。

结束时回复末尾给 ≤10 行交接摘要：交付物、§5 八条自证要点（命令或 文件:行）、实际运行结果（commit sha / stat / 全量通过数 / 两次构建 sha256）、偏离（含无法解析项）、风险。不要写 review 文件。
