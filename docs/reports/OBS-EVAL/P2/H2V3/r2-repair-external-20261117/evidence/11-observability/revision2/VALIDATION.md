# 验证记录

工作目录 `backend/`；Python 使用 `..\.venv\Scripts\python.exe`。均为虚构输入，无真实材料。

## 最终组合

```powershell
..\.venv\Scripts\python.exe -X utf8 -m pytest tests/rag/test_r2_observability_revision2.py ../docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/11-observability/revision2/work/test_r2_observability.py ../docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/11-observability/revision2/work/test_safe_plan_projection.py tests/observability/test_evaluation_capture.py tests/evaluation/test_r2_observability_io_revision2.py tests/evaluation/test_p2_evidence_io.py::test_turn_and_manifest_roundtrip_with_ciphertext_only tests/rag/test_query_state.py::test_enumeration_larger_than_top_k_reports_total_and_more -q -p no:cacheprovider --tb=short --basetemp='C:/Users/dell1712/.codex/visualizations/2026/11/17/01a1e9ec-6a25-7d40-9c2d-fcba2ba67814/obs-final-tests-2'
```

退出码 0：34 passed，1 warning。SAFE 投影随后增加安全状态输出后单独运行 `..\.venv\Scripts\python.exe -X utf8 -m pytest ../docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/11-observability/revision2/work/test_safe_plan_projection.py -q -p no:cacheprovider`，退出码 0：2 passed。

真实离线索引测试在摄入和查询阶段拦截 socket connect/connect_ex/create_connection/getaddrinfo、httpx transport、subprocess.Popen；执行捕获前后/改前查询时被阻断账本 0 次，随后显式网络与子进程正对照各被拦截 1 次。此证据仅覆盖该单例和所列通道，不代表 HTTP 链或所有系统调用的审计。无真实付费调用。

最初新替身测试因虚拟 index 缺 `business_date` 出现 4 failed / 22 passed；补齐替身后通过。加密 IO 初次因测试模块导入失败未收集；修正导入后默认 tmp 路径无法创建 pytest 临时目录（3 errors），改用已授权的仓外临时目录后通过。此前未改任何评分或期望以掩盖失败。

## 集成挂起诊断

上轮 HTTP 节点曾无输出中断。本轮通过独立 `subprocess.run(..., timeout=28)` 调用项目 venv，运行 `tests/integration/test_r2_202d_uniqueness.py::test_same_store_one_row_still_joins -vv -s -p no:cacheprovider -o faulthandler_timeout=12 --basetemp=../.tmp-r2-obs-diag2`。12 秒线程栈显示主线程在 TestClient 门户等待，后台线程在 Windows asyncio `socket._fallback_socketpair`；28 秒外层超时杀死测试子进程，未完成测试。单独无守卫执行 `socket.socketpair()` 也在 10 秒无输出，手动中断，退出 1。现有证据定位至事件循环 socketpair 创建，未证明更深的环境根因或守卫缺陷。

`git apply --check --ignore-space-change .../revision2/ROLLBACK.patch` 退出码 0，仅检查，未应用。最终 tracked 状态仍 39 项、暂存为空；四个获准修改文件的变化包含本批，其他既有工作保留。未运行全量测试。
