模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# T113（监控 API，只读聚合）独立验收 review

**结论：PASS（T113 代码/交付）；无阻断代码缺陷。全量 0 failed 项 BLOCKED（环境，非 T113）；不计为 PASS，详见 §3。**
交付 `9edc003`（父 `10bb42b`）；当前 `HEAD=22f098e`，`git diff 9edc003..HEAD --stat` 仅
`.claude/handoffs/**`，tracked 工作树 clean。证据：`docs/reports/OBS-EVAL/P1/evidence/verify/T113/`
（4 份：`01-openapi.json`、`02-independent-probe.md`、`03-tests-and-regression.md`、`probe.md`）。

## 1. 逐项结论

| # | 验收项 | 结论 | 独立证据（非 report） |
| --- | --- | --- | --- |
| 1 | 4 端点 admin 200/结构、employee 403、匿名 401 | **PASS** | 独立探针矩阵：admin 200×4、employee 403×4、anonymous 401×4（`02` §A）；结构由 `routes.py:738-886` 白名单响应 + 本包 `test_routes.py:284-357`（已复跑 35 passed） |
| 2 | 只读（仅 GET、无写调用/无文件变化） | **PASS** | OpenAPI 4 路径仅 `get`（`01`）；`list_window` 纯 SELECT `store.py:249-281`；独立前后 SHA-256：业务库、trace 主库、trace WAL、run manifest 全等（`probe.md` §D，`02` §B） |
| 3 | 无原文（仅 hash/计数/长度/时长/成本/状态；`*_json` 裁剪） | **PASS** | 独立探针把秘密文本埋入 attributes/summary/declarations/gate 后，5 个响应均 `secret_in_any_body=false`、`json_suffix_keys=[]`、无 question/answer/context/cases/case_id 键（`02` §C）；白名单 `routes.py:87-261`、`322-370`；本包 `test_routes.py:586-631` |
| 4 | Holdout 不可达（仅聚合、无逐题；不能间接取） | **PASS** | `holdout_details=true` + 含秘密题干/答案的 `cases.jsonl` → `holdout_detected=true`、`details_withheld=true`、无 cases/case_id/秘密文本（`02` §D）；`routes.py:849-866`；trace 摘要不含 case_id/run_id；junction 逃逸 404 |
| 5 | trace 关闭降级、404/4xx、路径穿越 | **PASS** | 默认关闭 200 + `trace_disabled`；closed repo 200 + `trace_unavailable`；未知 trace/run 404；非法 window/ID 422；`%2e%2e`/`..%5C` 422（`02` §E）；`routes.py:269-287`、`564-575`、`725-731`；本包 `test_routes.py:365-450` |
| 6 | OpenAPI 4 路径 + admin 安全声明 + JSON 导出 | **PASS（LOW 口径缺口）** | `01-openapi.json`：4 路径、仅 `get`、均含 401/403，`initialize=False` 不建 data_dir；但 `securitySchemes={}` 且 operation 无 `security` 键，无机读“admin 安全声明”，见 §2 LOW-1 |
| 7 | 本包/observability/全量、P0 对照、范围/预算/合规 | **PASS（全量项 BLOCKED）** | 本包 35 passed、observability 290 passed；b0 40/40、badcase 13/13、regression 7/7 对基线 signature 0 + retrieved 0，gate 均 exit 3/hard `[]`（`03` §A-B）；全量 1812 passed/46 failed，46 项全为 `docs/evidence` 只读 PermissionError，T113 相关零失败（`03` §A）；范围/证据/单 commit/无 skip/无新依赖见 `03` §C |

## 2. 发现（均非阻断）

- **LOW-1 · OpenAPI 无机读 security**：`securitySchemes={}`，4 个 operation 均无
  `security`；只有 401/403 `responses` 说明。运行时 `Depends(require_role("admin"))`
  已挂载且 401/403 实测通过；全应用是 cookie-session，无既有 scheme 可复用。按 handoff
  §3.5 字面“admin 安全声明”属口径缺口，建议 T114 文档包补 `securitySchemes`/`security`
  或明确“401/403 即声明”。不影响授权/数据安全。
- **LOW-2 · 报告/证据 01 的父提交笔误**：写 `fcc3434`，实际 `9edc003^ = 10bb42b`
  （`fcc3434` 是更早祖先）；不改变代码与验收结论。
- **INFO · 本包只读测试未覆盖业务库**：交付 `test_routes.py:763-791` 只哈希 trace 库与
  run 三件套；验收方补测了业务库 `mktkb.sqlite3`，前后一致（`probe.md` §D），故不构成
  缺陷，但测试可加强。

## 3. 全量 pytest（BLOCKED，非 NOT-RUN）

内存门槛前实测 **4368 MB ≥ 2048 MB**，满足 §11D。全量执行两次（cwd=仓库根，先
`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`）：

- 第 1 次（无 `os.mkdir` shim）：1755 passed / 85 failed / 18 errors（759.09s）。18 个
  error 为 `%TEMP%\mktkb-eval-*` 的 0o700 目录不可进入（本沙箱 ACL 映射）。
- 第 2 次（`_scratch/pytest_runner.py` 仅 workaround 0o700）：**1812 passed / 46 failed**
  （505.08s）。46 项全部为 `docs/evidence` 只读：43 个 `acceptance/test_t09_*` 写
  `docs\evidence\T09\D1\actual\...`、3 个 `rag/test_budget*`/`test_s4` 写
  `docs\evidence\...\budget\live-ledger.jsonl.lock`；无 `observability`/T113 失败。
  两次总数均 1858，与 report 的 1858 一致，但**本环境不能证明 0 failed**。
- 既有 flake（`test_g08_short_budget_cancels_inflight_model_call`、
  `integration/test_lifecycle.py::test_concurrent_publish_and_global_revision_cas[v05]`）
  本轮未失败，未触发隔离复跑。
- 环境偏差：`backend\.pytest-tmp` 对本进程只读，故 `--basetemp _scratch\...`；`docs/evidence`
  只读导致上述 46 项失败；均为验收环境限制，不是交付物改动（`probe.md` §B）。

## 4. 回归 / 范围 / 合规

- P0：b0 `signature_diffs=0/40`、badcase `0/13`、regression `0/7`（对 T109-R2
  `regression-current`；`var/eval/runs` 无 p0-regression），retrieved 亦 0；gate 均
  exit 3、hard `[]`、unknown 42/94/80（`03` §B，`_scratch/compare_result.json`）。
- 交付：`git show --stat 9edc003` 9 文件 +2101，全部 handoff 允许路径；无
  `conversations/`/`intent.py`/`fixtures`/`gate`/账本/GO/`.env`/Holdout 改动；
  `pyproject.toml`/`backend/pyproject.toml`/`uv.lock` 无 diff；新测试无 skip/xfail/删断言；
  report 80 行、证据 4、单 dev commit；未 push/amend/切分支/改交付物。
- 零真实模型/embedding/rerank/OCR：探针全部 `Settings(_env_file=None)` + fake/offline；
  evaluation 三套 local 用离线索引；未打印/读取 `.env`；未打开 P1-HOLDOUT 逐题内容
  （Holdout 用合成秘密文本；全量执行既有测试但未查看其输出内容）。

## 5. 未覆盖 / 残余

- 全量 `0 failed/0 error` 在本沙箱 **BLOCKED**（`docs/evidence` 只读）；T113 相关全绿，
  但“全量通过”不作为本次 PASS 的证据。
- OpenAPI 机读 security 缺失（LOW-1）留给 T114 或 PM 口径裁定。
- 验收环境对 0o700/`docs/evidence` 的限制导致无法按 handoff 原始 `--basetemp` 路径执行；
  已用只改验收进程行为的 shim 并记录，未改测试/业务/交付物。
