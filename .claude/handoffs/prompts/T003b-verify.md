角色：独立验收者（不是开发者，也不是项目经理）。任务 T003b（配置 + 中间件接线）。全新上下文。

你的任务是证伪，不是帮它说话：只认自己亲自复跑的结果，**不引用开发方 report.md 作为 PASS 证据**。

第一步：读 `.claude\handoffs\T003b-wiring\handoff.md`（验收标准 §5、必跑命令 §6）；再读同目录 `report.md`，只当线索。

逐条独立复核：亲自复跑 handoff §6 全部命令（分支 `p0/obs-eval`，`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，`.\.venv\Scripts\python.exe -B`），每条给 `PASS / FAIL / BLOCKED / NOT-RUN` + 证据。重点亲测：
- §5.1 默认关闭：QA POST 无 `X-Trace-ID`、不建 DB、`X-Request-ID` 不变；
- §5.2 开启后响应头是 UUID、DB 能查到对应 trace 且字段合理（spans 为空属预期）；
- §5.3 只有 QA POST 有 trace（GET/登录/上传不得有）；
- §5.4 monkeypatch 写入抛错/不可写路径时响应仍正常、不泄漏内部错误；
- §5.5 trace 开/关两种设置下固定请求响应 body 归一化一致；既有 integration 全绿；
- §5.6 中间件不传 `TraceMode.LIVE`（源码+运行断言）；
- §5.7 config 默认值不破坏既有 Settings；content_mode 只接受 off/hash；HMAC key 不出现在日志/响应/异常/trace；
- §5.8 全量 `backend/tests` 相对 1176 基线无新增失败（0 failed / 0 error）。
- 提交边界：`git show --name-only HEAD` 只能含 handoff §2 允许路径（config.py、main.py、test_middleware.py、conftest.py、证据、report.md）；不得出现业务代码（qa/rag/conversations）、observability 内核文件、既有测试、pyproject、docs/evidence、var、fixtures 改动；越界即 FAIL。
- 测试非空转：抽查断言是否真校验行为；可做仓库外变异探针（如默认开启不生效、错误路径返回头、传 live），仓库内不得改动。
- 硬约束：无新增依赖、零真实调用、不读 `.env`、API 字段结构未变。

产出：写 `.claude\handoffs\T003b-wiring\review.md`（逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令与 文件:行、发现问题、未覆盖项）；复跑证据存 `docs\reports\OBS-EVAL\P0\evidence\verify\T003b\`。

你不修改任何交付物、不改代码、不 commit、不 push、不改 `_index.md`。回复末尾给 ≤10 行结论摘要。
