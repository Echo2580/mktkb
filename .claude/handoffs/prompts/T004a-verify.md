角色：独立验收者（不是开发者，也不是项目经理）。任务 T004a（评测数据集 + gold 解析 + fixtures），对象 commit `574e288`。全新上下文。

你的任务是证伪，不是帮它说话：只认自己亲自复跑的结果，**不引用开发方 report.md 作为 PASS 证据**。

**提速策略（主人 2026-11-05 采纳 A/C/D）**：本包 1 次 + 受影响目录（`backend/tests/evaluation`）1 次 + **全量只跑 1 次**；不重跑旧 commit 基线全量（改用"全量 0 failed/0 error + 新增 34 用例 + `git show --stat 574e288` 改动范围"证明无回归）；证据 ≤3 份（本包/目录/全量），报告 ≤120 行；串行跑，不并发两套 pytest。

第一步：读 `.claude\handoffs\T004a-dataset\handoff.md`（验收标准 §5、必跑命令 §6）；再读同目录 `report.md`，只当线索。

逐条独立复核：亲自复跑 handoff §6 全部命令（分支 `p0/obs-eval`，`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，`.\.venv\Scripts\python.exe -B`），每条给 `PASS / FAIL / BLOCKED / NOT-RUN` + 证据。重点亲测：
- §5.1 两个 jsonl 行数 40/13、字段齐全、b0 分层 24/8/8、badcase 来源分组正确；
- §5.2 校验规则负例（chunk_id/unit_id UUID、should_refuse 无 reason、question/turns 全空、非法 expected_kind）都真抛错；
- §5.3 B0 8 道 OCR 题 requires_ocr=true 且无真实 OCR 调用痕迹；
- §5.4 **亲自离线构建索引并 resolve_gold**：B0 非 OCR 32 题与 badcase 13 题逐条可解析（不采信开发测试结论，自己写探针；OCR 题按规则跳过）；任何 GoldUnresolved 逐条列出；
- §5.5 造 0/多匹配场景 verify fail closed；多 chunk 同 unit 去重；
- §5.6 `dataset_version` 稳定、构建脚本两次输出 sha256 一致（亲自跑两次比对）；
- §5.7 `backend/tests/evaluation` 全绿 + 全量相对 T003d 基线无新增失败；
- §5.8 硬约束与提交边界：`git show --name-only HEAD` 只含 handoff §2 允许路径；不得出现 fixtures/acceptance、docs/evidence、业务代码、observability、pyproject、var 改动；不新增依赖。
- 测试非空转：抽查断言；可做仓库外变异探针（如让 0 匹配返回首个 unit、删除校验、把 OCR 题标 false），仓库内不得改动。
- **PM 指定的两处口径判断（必须给结论，不许回避）**：
  1) `locator` 范围型（多命中不报错、仅 `unit_key` 重复才 `ambiguous_units`）是否构成对 handoff §5.5「多匹配 fail closed」的**削弱**？判据：0 匹配是否仍 fail closed、多 chunk 同 unit 是否去重、范围型是否只在该多命中语义上放宽；给「可接受偏离（记非阻断）」或「FAIL」。
  2) `expected_pagination` 统一 `null`（N05 `expected_min_total` 仅存 notes）是否造成 §5.1 字段事实缺失或分页语义被架空；给结论与对 T004b/T006 的影响提示。

产出：写 `.claude\handoffs\T004a-dataset\review.md`（逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令与 文件:行、发现问题、未覆盖项）；复跑证据存 `docs\reports\OBS-EVAL\P0\evidence\verify\T004a\`。

你不修改任何交付物、不改代码、不 commit、不 push、不改 `_index.md`。回复末尾给 ≤10 行结论摘要。
