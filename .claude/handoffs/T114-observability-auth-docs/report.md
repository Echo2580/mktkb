模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# T114 监控 API 权限/负例/文档

## 1. 完成内容

- 新增 `backend/tests/observability/test_routes_security.py`（62 条）：4 端点 ×
  未登录 401 / employee 403 / admin 200；鉴权顺序；错误信封白名单；404/422 负例；
  非法 `window`/`trace_id`/`run_id`/`request_id`；编码路径穿越；时间窗合法/非法与
  超大窗口；分页 NOT-APPLICABLE；trace 关闭降级；成功/错误响应不泄露；Holdout
  仅聚合；OpenAPI 4 路径/仅 GET/401/403/快照一致性。
- `docs/接口与数据契约.md` 追加 `## 8. 观测与监控接口（只读）`（`:180`），含权限、
  端点、字段白名单、错误码、时间窗、无分页、降级、只读与不泄露；既有章节未改。
- 新增 `docs/reports/OBS-EVAL/P1/evidence/T114/openapi-observability.json`（4 paths /
  13 schemas / 37,106 bytes，SHA-256 `51f7ed…db5979`）。
- 证据 4 份（含 OpenAPI）与本报告，单 commit。
- **未改** `routes.py`：测试未发现 T113 缺陷，无需 §0-2 最小修复；未改 T113
  `test_routes.py`、业务 API/schema/conversations/intent/账本/GO/.env/Holdout。

## 2. 验收标准自证

1. 权限矩阵：`test_unauthenticated_gets_401_before_validation`（`:395`）、
   `test_employee_gets_403_before_validation`（`:412`，`required_role=admin`）、
   `test_admin_gets_200_on_all_four`（`:428`）；顺序由 `:450` 断言。
2. 负例：404 `TRACE_NOT_FOUND`/`RUN_NOT_FOUND`（`:486`）；422 `INVALID_WINDOW`
   （`:515`）与 `INVALID_*`（`:541`）；穿越 4xx（`:570`、`:577`）；未知 request
   200 空列表（`:501`）；trace 关闭 4 端点 200 + `trace_disabled`（`:646`）。
3. 时间窗：合法 `1h/24h/30m/999999h`（`:599`），非法清单含 `0h/-1h/abc/24/1.5h/
   24D/1H/ 24h/1000000h`（`:515`）；超大窗口 200 不 500（`:617`）；分页
   NOT-APPLICABLE 由 OpenAPI 参数断言（`:626`）与文档 `:210` 共同证明。
4. 不泄露：错误/成功响应逐层 Pydantic 白名单 + 递归键黑名单 + `SECRET_TEXT`
   文本断言（`:467`、`:680`）；span 只给属性键名/个数；Holdout 仅 `strata`
   聚合、`details_withheld=true`（`:760`）。
5. 文档/OpenAPI：文档 `:180-230` 与 `routes.py` 模型逐字段核对；快照 4 路径仅
   `get`、均声明 401/403；一致性由 `:834` 守护；文档写明只读/降级/不泄露/无分页。
6. 回归/预算：本包 62 / observability 352 / 全量 1920，0 failed/0 error；
   b0/badcase/regression 对基线 signature/retrieved 均 0 diff、hard `[]`；
   证据 4、report ≤80、1 commit、只改允许路径、无 skip/xfail/删断言/新依赖/
   真实调用（详见证据 02/03）。

## 3. 实际运行结果

```text
本包      test_routes_security.py   -> 62 passed, 1 warning in 17.44s
目录      backend/tests/observability -> 352 passed, 1 warning in 59.49s
全量      backend/tests             -> 1920 passed, 1 warning in 547.36s
                                     0 failed / 0 error；跑前 FreePhysicalMemory=3,628,672 KB
b0        b0-local-20261109T102119799626Z-4eac0fda      40/40  pass29/fail3/skip8  gate exit3 hard[] unknown42
badcase   badcase-local-20261109T102124052127Z-f51e3fef 13/13  pass9/fail4          gate exit3 hard[] unknown94
regression regression-local-20261109T102146258723Z-a2891506 7/7  pass5/fail2          gate exit3 hard[] unknown80
         以上三套对 P0/T109-R2 基线 signature_diffs=0、retrieved_diffs=0
```

Commit：单 commit（建议消息 `p1/T114 observability auth negative boundaries + docs`），
sha 见交接摘要与 `git log -1`；`git show --stat` 为 7 files（新增测试、文档增补、
证据 4、报告 1），全部为 handoff §2 允许路径。

## 4. 偏离

- 无代码偏离；未触发 `routes.py` 最小修复（未发现 T113 缺陷）。
- OpenAPI 未新增 `securitySchemes`：本应用为 Cookie 会话，权限声明以 401/403
  响应表达（T113 验收 LOW-1 口径）；已在文档 §8.6 与测试注释中写明，避免改
  权限依赖/响应结构。
- regression 基线取 T109-R2 `regression-current`（`var/eval/runs` 无 p0-regression），
  与 T113 验收口径一致。

## 5. 风险

- `999999h` 仅证明 200 不崩，未证明大窗口性能或全表保护上限；文档已声明。
- 外部工具无法从 OpenAPI 机读 Cookie 会话的 security scheme；运行期鉴权与
  401/403 断言仍有效，属文档化残余。
- 全量 547s、无 flake；若后续并行任务争用 CPU 可能变慢，不构成本包缺陷。

## 交接摘要

- commit：单 commit（sha 见 `git log -1`）；7 files，全允许路径。
- 测试：本包 62 / observability 352 / 全量 1920，0 failed/0 error。
- 评测：b0/badcase/regression 0 diff、gate exit3 hard `[]`。
- 证据：`docs/reports/OBS-EVAL/P1/evidence/T114/` 4 份（含 OpenAPI）。
- 风险：超大窗口仅验不崩；OpenAPI 无 securitySchemes（已文档化）。
