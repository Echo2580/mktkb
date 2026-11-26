# 定向验证记录

工作目录为 `backend/`。

1. `python -m pytest tests/integration/test_r2_202d_uniqueness.py::test_same_store_two_rows_does_not_join tests/integration/test_r2_202d_uniqueness.py::test_same_store_one_row_still_joins tests/integration/test_r2_202d_uniqueness.py::test_store_table_without_target_store_does_not_join tests/integration/test_r2_202d_uniqueness.py::test_c1_location_only_has_no_store_level_value_or_join tests/integration/test_r2_202d_uniqueness.py::test_c7_policy_turn_is_byte_identical tests/integration/test_r2_202d_uniqueness.py::test_offline_chain_has_zero_external_network_and_no_subprocess tests/observability/test_evaluation_capture.py -q`：退出码 1，系统 Python 缺少 `fastapi`，未开始测试。
2. `..\.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_r2_202d_uniqueness.py::test_same_store_two_rows_does_not_join tests/integration/test_r2_202d_uniqueness.py::test_same_store_one_row_still_joins tests/integration/test_r2_202d_uniqueness.py::test_store_table_without_target_store_does_not_join tests/integration/test_r2_202d_uniqueness.py::test_c1_location_only_has_no_store_level_value_or_join tests/integration/test_r2_202d_uniqueness.py::test_c7_policy_turn_is_byte_identical tests/integration/test_r2_202d_uniqueness.py::test_offline_chain_has_zero_external_network_and_no_subprocess tests/observability/test_evaluation_capture.py -q -p no:cacheprovider --basetemp=../.tmp-r2-obs-synthetic`：长时间无输出后人工中断，退出码 1；无通过结论。不能声称零出站守卫通过。
3. `..\.venv\Scripts\python.exe -X utf8 -m pytest tests/observability/test_evaluation_capture.py -q -p no:cacheprovider`：退出码 0，12 passed，1 warning；仅验证现有事件捕获基础测试，没有新接线。
4. `..\.venv\Scripts\python.exe -X utf8 -c "print(''runtime-ok'')"`：退出码 0。

集成测试含合成数据与既有网络、子进程守卫，但因中断未得到守卫账本及正对照结果，零外发未获得该项测试证据。未运行旧真实 runbook、全量 pytest 或真实调用。未做产品输出开关对照，因为没有新增观测开关或产品源码变更。

5. `git diff --check -- backend/src/mktkb/qa/service.py backend/src/mktkb/observability/evaluation_capture.py`：非零，报告 QA 文件既有工作树差异的行尾空白；本轮未修改该文件，未为消除既有差异而改动。
