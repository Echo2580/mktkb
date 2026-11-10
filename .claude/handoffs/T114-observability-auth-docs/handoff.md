# T114 交接单：监控 API 权限/负例/文档（P1 第 14 包）

> 基线：分支 `p1/fix-retrieval`；T113 已交付 `9edc003`（独立验收结论见 `.claude/handoffs/T113-observability-api/review.md`）；T112 等主人指定请求上限方案、暂缓。当前 HEAD 见 `git log -1`（PM 簿记为准）。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码/文档正文。

## 0. PM 口径（先读）

1. **范围**：T113 监控 API 的**权限矩阵 / 负例 / 时间窗边界测试** + `docs/接口与数据契约.md` 增补 + OpenAPI 产物；**不改业务 API 行为/字段结构**，T113 只读语义不变。
2. **缺陷修复边界**：仅当测试发现 T113 缺陷时，允许对 `backend/src/mktkb/observability/routes.py` 做**最小修复**（不得改权限模型/schema/响应字段结构）；report §4 单列文件/函数/净增行与理由，否则不得改该文件。
3. **权限矩阵**：4 端点 × {未登录 401、employee 403、admin 200}；admin 下不存在资源 404；非法参数 4xx；trace 关闭降级 200。顺序=鉴权→参数校验→资源读取，错误码不得泄露资源存在性（未登录/employee 下不得返回 404 语义）。
4. **时间窗边界**：`_WINDOW = ^([1-9][0-9]{0,5})([hm])$`；`0h`/`-1h`/`abc`/`24`/`1.5h`/`24D`/`1H`/` 24h` → 422 `INVALID_WINDOW`；`1h`/`24h`/`999999h` → 200 不 500（大窗口只断言不崩，不声称性能/全表保护）。**分页边界：T113 四端点均无 limit/offset 参数 → 记 NOT-APPLICABLE 并说明**，不得虚构分页行为。
5. **不泄露**：成功与错误响应（401/403/404/422）均不得含问题/答案原文、`*_text` 正文字段、Holdout 逐题/题干/答案；对错误响应也做键白名单断言。
6. **文档**：`docs/接口与数据契约.md` 新增一节（按既有编号顺延，如 `## 8. 观测与监控接口（只读）`），按既有风格写：方法/路径/权限/参数/响应字段/错误码/降级/不泄露/只读声明/无分页说明。**只增不改既有章节语义**。
7. **OpenAPI 产物**：`docs/reports/OBS-EVAL/P1/evidence/T114/openapi-observability.json`（只含 4 paths + 相关 components 子集，可入库、体积可控）；另用 `app.openapi()` 断言 4 路径与安全声明。

## 1. 目标

补齐监控 API 的权限矩阵、负例与时间窗边界测试，更新接口文档与 OpenAPI 快照；证明只读、无原文泄露、Holdout 明细不可达。任务拆解依据：`.claude/handoffs/2026-11-04-p1-task-breakdown.md` §「T114」。

## 2. 交付物（只准写这些路径）

1. **新增** `backend/tests/observability/test_routes_security.py`：权限矩阵 / 负例 / 边界 / 不泄露 / OpenAPI 断言。**不要改 T113 的 `test_routes.py`**；可复用 `backend/tests/observability/conftest.py` 既有 fixture（`trace_app`/`trace_repo`/`trace_employee`/`trace_admin`）。
2. **仅缺陷时**最小修复 `backend/src/mktkb/observability/routes.py`（report §4 单列理由）。
3. `docs/接口与数据契约.md` 增补一节（4 端点）。
4. `docs/reports/OBS-EVAL/P1/evidence/T114/openapi-observability.json`。
5. 证据 `docs/reports/OBS-EVAL/P1/evidence/T114/`（≤4 份，含上面 openapi 与测试输出摘要）、`report.md`（≤80 行五段）、**1 个 commit**。

禁止：业务路由/业务 API/`conversations/`/`intent.py`/schema/账本/GO/`.env`/Holdout/`docs/evidence/**`/`var/**`/T113 `test_routes.py`；不 push/amend；无 skip/xfail/删断言/新依赖；零真实调用。

## 3. 验收标准（逐条）

1. **权限矩阵齐全**：4 端点 × 未登录 401（`AUTH_REQUIRED`）/ employee 403（`ROLE_REQUIRED`）/ admin 200 均有独立测试；employee 403 带 `required_role=admin`；不泄露存在性。
2. **资源/参数负例**：admin 下不存在 trace/run → 404；非法 `window`/`trace_id`/`run_id`/`request_id` → 4xx 且 code 正确（`INVALID_WINDOW`/`INVALID_TRACE_ID`/`INVALID_RUN_ID`/`INVALID_REQUEST_ID`）；路径穿越被拒；未知 request → 200 空列表（T113 既有语义，文档写明）；trace 关闭 4 端点 200 + `degraded_reason="trace_disabled"`。
3. **时间窗边界**：合法（`1h`/`24h`/`999999h`）与非法（清单见 §0-4）逐项断言；超大窗口 200 不 500；分页 NOT-APPLICABLE 有说明。
4. **不泄露**：401/403/404/422 响应键白名单断言；成功响应亦白名单；构造含秘密题干/答案的 fixture 不出现在任何响应；Holdout run 仅聚合。
5. **文档/OpenAPI**：文档新增节与实现一致（路径/参数/字段名/错误码可对照实现或 OpenAPI）；OpenAPI 快照含 4 路径、均 `get`、声明 401/403；文档声明只读/降级/不泄露/无分页。
6. **回归/预算**：本包新测试 + `backend/tests/observability` + 全量 0 failed/0 error（内存 <2GB 轮询；既有 flake 隔离复跑 1 次）；b0/badcase local+gate 对 P0 `case_diffs=0`、hard `[]`；regression 状态不变；证据 ≤4、report ≤80、1 commit、只改允许路径、无 skip/xfail/删断言/真实调用。

## 4. 必跑（命令口径）

- 先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`。
- `.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_routes_security.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t114-pkg`
- `.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t114-obs`
- 全量：`.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t114-full`（同一时间只跑一套；全量前空闲内存 ≥2GB，不足轮询，仍不足才 NOT-RUN 并如实记录）。
- 环境说明：当前会话文件策略为 `danger-full-access`（主人 2026-11-09 调整），全量可直接写 gitignored 的 `docs/evidence` 测试产物；若仍遇 PermissionError，如实记录该环境失败，不得把环境失败写成通过。
- b0/badcase local+gate 对 P0 与 regression 状态：沿用既有脚本/命令口径（见前包证据），只读。
- OpenAPI 快照生成脚本可放 `.claude\handoffs\_scratch\T114\`（**该目录 gitignored**；不要在仓库根建 `_scratch/`，它不入 gitignore）。

## 5. 坑

- 鉴权在 FastAPI 依赖阶段先于函数体执行：未登录且 `window` 非法时实际返回 **401**（不是 422）——先实测顺序再写断言，别照抄预期。
- `require_role` 的 403 带 `details.required_role=admin`（`auth/routes.py`）；`get_current_user` 缺/坏令牌 → 401 `AUTH_REQUIRED`。401/403 都由全局错误处理器输出，断言响应 body 键集合（不要假设只有 detail）。
- `_validate_id` 拒绝 `..`、结尾点、非安全字符 → 422；`_run_directory` 还有 `resolve()+is_relative_to` 守卫 → 穿越在 admin 下也应 4xx（实测是 422 还是 404，按实测写）。
- `metrics` 大窗口 `timedelta(hours=999999)` 合法但会扫全表：fixture 数据量小，断言 200；不要声称已验证性能上限。
- 文档不得写未实测内容；响应字段以 `routes.py` 的 Pydantic 模型逐字段核对（不要凭 report 转抄）。
- OpenAPI 快照控制体积：只截 4 paths 与相关 components；断言全量 `app.openapi()` 含 4 路径。
- 复用 `conftest.py` fixture 时注意 `trace_admin`/`trace_employee` 是已认证 `SimpleNamespace`，不是 TestClient；按 T113 `test_routes.py` 的用法使用。

## 6. 报告/证据/交付

- `report.md` 五段：完成内容 / 验收标准自证（每条 ≤2 行，带命令或 `文件:行`）/ 实际运行结果（本包·目录·全量各一行 + commit sha + stat）/ 偏离 / 风险；末尾 ≤10 行交接摘要；首行注明模型。
- 1 个 commit（建议消息 `p1/T114 observability auth negative boundaries + docs`）；不 push、不 amend 历史。
