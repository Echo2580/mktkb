角色：开发助手。任务 T104（MKTKB 项目 P1 第 6 包：D1 异常原因透传，ERR-07 产品侧；D-3 已授权）。
第一步：完整读 `.claude\handoffs\T104-error-classification\handoff.md`，严格按「输入 / 交付物 / 验收标准 / 边界」执行。
核心：把 `conversations/service.py` 的异常处理从"一律 MODEL_UNAVAILABLE"改为按真实原因分类（配置/预算/provider/超时/输出校验/内部/未知），error_code + retryable 可区分；文案套 ERR-07 正面模板（失败≠资料无答案 + 可否重试 + 不重复落库）；**不得新增响应字段/改 API 字段结构**；既有测试只在"取值变化"处最小同步并在 report 列清单。
证据 ≤4 份放 `docs\reports\OBS-EVAL\P1\evidence\T104\`；写 `.claude/handoffs/T104-error-classification/report.md`（五段、≤80 行、自证带命令/路径 + 异常分类矩阵）；1 个 commit（消息 `p1/T104 model error cause classification`）；回复末尾 ≤10 行交接摘要（含 commit sha、改动文件、测试结果、b0/badcase 对照、断言同步清单）。
测试：本包 + 受影响目录 + 全量（先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；内存 2.07GB，全量前看/轮询 FreePhysicalMemory；既有 flake 隔离复跑记录）；b0/badcase local run+gate 前后对照；`backend/tests/observability` 全绿。
禁止：改网关模块/API schema/响应字段结构/前端/b0/badcase/gate_v0_1/其他包文件；除取值同步外削弱既有断言；skip/xfail；真实模型调用；读 `.env`/Holdout；切分支；push；新增生产依赖。
`report.md` 首行注明：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`。
