角色：独立验收者（不是开发者，也不是项目经理）。任务 T004b（scorer：值/来源/kind/分页/拒答/检索指标）。全新上下文。

你的任务是证伪，不是帮它说话：只认自己亲自复跑的结果，**不引用开发方 report.md 作为 PASS 证据**。

**提速策略（主人 2026-11-05 采纳 A/C/D）**：全量套件只跑**一次**；不重跑旧 commit 基线全量（改用"0 failed/0 error + 新增用例数 + `git show --stat` 改动范围"证明无新增失败）；证据只存 ≤3 份关键输出（本包/目录/全量）；不写超长报告。

第一步：读 `.claude\handoffs\T004b-scorer\handoff.md`（验收标准 §5、必跑命令 §6）；再读同目录 `report.md`（≤80 行），只当线索。

逐条独立复核：亲自复跑 handoff §6 命令（分支 `p0/obs-eval`，`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，`.\.venv\Scripts\python.exe -B`；串行、不要并发），每条给 `PASS / FAIL / BLOCKED / NOT-RUN` + 证据。重点亲测：
- §5.1 值归一化（全角/空格/大小写、数字不误配）与"不得编造额外数值"；
- §5.2 来源命中、引用精确/召回（unit 去重）；
- §5.3 kind/拒答判定；§5.4 分页契约四项；
- §5.5 拒答三指标确实分离（造混合样本，数值不同且各自正确）；
- §5.6 检索指标与手工小样本对照；无 gold case 不进入分母；
- §5.7 确定性（两次输出逐字节一致）；§5.8 全量一次 = 基线通过数 + 新增数、0 failed/0 error。
- 提交边界：`git show --name-only HEAD` 只含 handoff §2 允许路径；不得出现 dataset/gold/runner/gate/baseline/report、业务代码、观测内核、既有测试、pyproject、docs/evidence、var、fixtures。越界即 FAIL。
- 测试非空转：抽查关键断言；可选做 1–2 个仓库外变异探针（如让拒答三指标相等、全角不归一），仓库内不得改动。
- 硬约束：无新增依赖、零真实调用、不读 `.env`、不改业务返回类型。
- **PM 指定的四处判断（必须逐条给结论，不许回避）**：
  1) `EvalOutcome` 在计划字段外增加 `retrieved`：是否违反 handoff §4/§7（"只做归一化输入、不改业务返回类型"）？给「可接受偏离」或「FAIL」。
  2) `unit_ids` 依赖：`EvalCitation/EvalRetrieved.unit_ids` 需 runner 填充，runner 尚未实现——核查缺失时是否真 fail closed（不静默算命中）、指标是否退化为 0 而非崩溃/误判；写成对 T005 的硬性要求。
  3) `value_no_fabricated` 偏严：核查判定集合（gold/问题文本/业务日期之外的数字一律算编造）会产生哪些误判，是否足以让门禁误杀，建议归为软指标还是硬门禁。
  4) 拒答口径（仅 `no_answer`/`not_found`，兼容 `refusal`；`clarification`/`conflict` 不算拒答）是否与 `docs\evaluation\` 下 gate 文档（如已有 gate_v0_1 草案/设计 §8）一致；不一致记为对 T006a 的约束，并写清以哪一方为准。

产出：写 `.claude\handoffs\T004b-scorer\review.md`（逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令与 文件:行、发现问题、未覆盖项，≤120 行）；复跑证据存 `docs\reports\OBS-EVAL\P0\evidence\verify\T004b\`（≤3 份）。

你不修改任何交付物、不改代码、不 commit、不 push、不改 `_index.md`。回复末尾给 ≤10 行结论摘要。
