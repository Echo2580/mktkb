模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# T114 独立验收结论

**结论：PASS（6/6 验收项，无阻断项；2 条 LOW 残余）。** 以当前工作树代码为准；
dev commit `2a0c192`（7 files, +2739/-0，全部允许路径）；`HEAD=6e6947d`，其后仅
`.claude/handoffs/**` PM 簿记；开工时 `git status --porcelain` 为空。

## 逐条验收

| # | 结论 | 自跑命令 / 证据 |
| --- | --- | --- |
| 1 权限矩阵 | **PASS** | 本包 62 passed（证据 `01`）；独立探针 87 checks/0 failed：4 端点匿名 401 `AUTH_REQUIRED`、employee 403 `ROLE_REQUIRED` 且 `details={"required_role":"admin"}`；用 `bad..id`、不存在 id、`window=not-a-window` 也不返回 404/422（`test_routes_security.py:395/412/428/450`；探针段 1/1b/2）。 |
| 2 资源/参数负例 | **PASS** | admin 不存在 trace/run → 404 `TRACE_NOT_FOUND`/`RUN_NOT_FOUND`；非法 window/id → 422 对应 `INVALID_*`；`%2e%2e`/`..%5C`/`bad%20id` → 422，`..%2F`/`bad%2Fid` 路由 404，均不 200；未知 request → 200 空列表；trace 关闭四端点 200 + `trace_disabled`（`:486/501/515/541/570/577/646`；探针段 B/8）。 |
| 3 时间窗/分页 | **PASS** | `1h/24h/30m/999999h` → 200；`0h/-1h/abc/24/1.5h/24D/1H/ 24h/1000000h` → 422 `INVALID_WINDOW`；`999999h` 200 且 `since<until`、无 500；四端点无 limit/offset，NOT-APPLICABLE（`:599/617/626`；`接口与数据契约.md:212-214`；探针段 B）。只断言不崩，未声称性能上限。 |
| 4 不泄露 | **PASS** | 401/403/404/422 信封严格四键 + `request_id`，message 不回显输入/路径；成功响应逐层 Pydantic 白名单；秘密文本埋入 `case_id`、`*_json`、summary `metrics_scope/declarations`、gate `failures.evidence`、span `attributes_json`、holdout `cases.jsonl` 后均不出现；span 仅键名/计数；Holdout 仅聚合（`:467/680/760`；探针段 A/5/6）。 |
| 5 文档/OpenAPI | **PASS** | `doc_check.py` 40 checks/0 failed：8 个模型的文档字段集合与 `model_fields` 全等；端点表 4 条均 GET；错误码/正则/13 个窗口样例一致；文档声明只读/降级/不泄露/无分页（`接口与数据契约.md:180-228`）。`openapi_check.py`：快照 4 paths、仅 GET、每条 401/403、13 schemas 与实时引用闭包全等；37,106 bytes，SHA-256 `51f7ed…db5979`（证据 `02`/`03`）。 |
| 6 回归/预算 | **PASS** | 本包 62、observability 352、全量 1920 passed / 0 failed / 0 error（473.84s，跑前 3297 MB；未触发既有 flake）；b0/badcase/regression local+gate 对 P0/T109-R2 `signature_diffs=0`、`retrieved_diffs=0`、gate exit 3/hard `[]`；未改 `routes.py`/T113 `test_routes.py`/conftest/pyproject/uv.lock；无 skip/xfail/删断言/新依赖；report 80 行、证据 4 份、单 dev commit（证据 `01`/`03`）。 |

## 独立复跑与探针

```powershell
# 本包 -> 62 passed, 1 warning, 17.56s
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_routes_security.py `
  -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t114v-pkg
# observability -> 352 passed, 46.13s
# 全量 -> 1920 passed, 0 failed/0 error, 473.84s
```

```powershell
.\.venv\Scripts\python.exe -B .claude\handoffs\_scratch\T114v\probe.py       # 87 checks, 0 failed
.\.venv\Scripts\python.exe -B .claude\handoffs\_scratch\T114v\doc_check.py   # 40 checks, 0 failed
.\.venv\Scripts\python.exe -B .claude\handoffs\_scratch\T114v\openapi_check.py # exit 0
```

评测独立重跑：b0 `b0-local-…e05aaf61` 40/40（pass29/fail3/skip8）、badcase
`…472c1810` 13/13（pass9/fail4）、regression `…6c624c46` 7/7（pass5/fail2）；
三套 gate 均 exit 3、`hard=[]`、failures 0；逐例签名/retrieved 对基线 0 diff
（证据 `03` §C）。

## 证伪检查（均建立/澄清，不构成阻断）

- **401/403 先于参数校验**：对非法 path id（`bad..id`）匿名/employee 仍 401/403；
  编码斜杠 `..%2F`/`bad%2Fid` 由路由层 404（未匹配路由），不进入资源读取，也不
  泄露存在性；文档 `:199` 已写明“被路由匹配前 404”。不是顺序缺陷。
- **错误响应泄露**：逐 body 键白名单 + message 回显检查；404/422 无临时目录、无提交
  原文。未发现路径/题干/答案泄露。
- **超大窗口**：`999999h` 200 且 `since<until`；仅证明不崩，文档已声明不声称性能。
- **OpenAPI 快照**：仅 4 paths、仅 GET、401/403 齐全；快照与实时 schema 的 4 路径
  components 引用闭包完全相等；未见多路径或写方法。
- **T113 未被动过**：`git diff 9edc003..2a0c192` 对 `routes.py`、T113 `test_routes.py`、
  conftest、pyproject/uv.lock 均为空；dev commit 仅 7 个允许路径。

## 残余 / 建议（不阻断）

- **LOW-1（holdout 标志措辞）**：手工构造“manifest `holdout_details=false` +
  summary `holdout.details_written=true` + 无 `cases.jsonl`”的不一致 run 目录时，
  `details_withheld=false`；文档 `:222` 的“存在逐题明细或声明”字面更宽。真实 runner
  在 `runner.py:2806-2807` 令 `details_written = manifest.holdout_details`，不会分歧；
  该响应仍只有聚合，不读 `cases.jsonl`、无原文泄露。建议文档改为“manifest
  `holdout_details=true` 或存在 `cases.jsonl`”，或代码把 summary 标志纳入判断。
- **LOW-2（继承 T113）**：OpenAPI 仍无 `securitySchemes`，仅以 401/403 表达权限；
  `接口与数据契约.md:228` 已显式声明，属 T113 LOW-1 的继承残余，不改变运行期鉴权。
- 未覆盖（非本包验收要求）：`trace_unavailable`/`partial_data` 降级路径与 500 响应
  未有专项测试；本次未发现对应代码缺陷，建议后续补测。

## 证据

- `docs/reports/OBS-EVAL/P1/evidence/verify/T114/01-pytest-runs.md`
- `docs/reports/OBS-EVAL/P1/evidence/verify/T114/02-independent-probe.md`
- `docs/reports/OBS-EVAL/P1/evidence/verify/T114/03-scope-regression-openapi.md`

未改交付物；未 commit/push/切分支；仅写上述 3 份证据与本 review。
