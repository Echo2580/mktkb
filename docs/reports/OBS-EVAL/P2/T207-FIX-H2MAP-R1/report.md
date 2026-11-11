# T207-FIX-H2MAP-R1 开发返工报告

主人，H2 双定位显式冲突已完成最小修复；仅开发自测通过，等待全新上下文独立复验。

- 接手基线：HEAD `d7728db35655ae67569aec84cc4ededeaf7f7c13` 上原 H2MAP 未提交改动全部保留；未恢复 H2DIAG patch。
- 本轮修改仅 `backend/src/mktkb/evaluation/p2_scoring.py` 的 `_source_identity` 中 `include_source_version=True` 分支；`backend/tests/evaluation/test_p2_holdout_source_map.py` 只新增 22 个合成用例。
- 原有非空 index locator 选择逻辑不变；选择后同时校验 raw product locator 和选中 locator 的显式版本断言，拒绝 null/bool/string/非正数及产品版本冲突，稳定 `source_version_conflict`。
- raw/index 在相同原 locator 键上明确不一致时稳定 `source_locator_conflict`；版本键冲突仍为 `source_version_conflict`。单边缺键不新造值、不合并补齐。
- 产品 `version_number` 仍是唯一版本身份：缺失或坏类型不能由 raw/index 补成命中；默认开关 False 路径保持原样。

## 本轮实际验证

| 检查 | 结果 |
|---|---|
| TDD RED：新增 R1 合成用例、修复前 | 10 failed / 12 passed / 34 deselected；8 个 raw 版本遮蔽、2 个 row/sheet 遮蔽均 DID NOT RAISE |
| GREEN：完整 H2MAP 文件 | 56 passed；原有 34 个用例均保留 |
| 相关链：R1 证据测试副本 + H2MAP/score_run/scoring/holdout_scorecard/scorers | 236 passed，7.42s，退出 0；1 条既有 Starlette/httpx 弃用 warning |
| 原独立阻断两个反例 | 使用原独立测试源码副本重新执行，两个反例均通过预期 conflict 断言；副本只调整证据输出位置，不代表独立验收 |
| 公开默认差分 | R1=52、R2=2、R4=3，共 57 条/57 轮；case scores、scorecard 对 git 基线及归档逐值相等，默认归一逐值相等；P1 scorer/runner 归一换行字节相同 |
| 真 runner 合成 Mock E2E | run_p2 + ProductEvalAdapter + MockChatBackend/MockTransport，3 次版本上传后完整执行 30 条；30 fail / 0 pass / 0 error，无 unmapped；逐题产物及 trace 清除，real_calls=0 |
| 防越界 | 差分/E2E guard external=[]；仅 asyncio 本地回环；预算/GO/账本三固定 hash 相等；原 H2MAP 11 个报告/证据文件逐字节 hash 不变；git diff --check 通过 |

命令：项目 `.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider`，相关链参数为 `docs/reports/OBS-EVAL/P2/T207-FIX-H2MAP-R1/evidence/test_recheck.py backend/tests/evaluation/test_p2_holdout_source_map.py backend/tests/evaluation/test_p2_score_run.py backend/tests/evaluation/test_p2_scoring.py backend/tests/evaluation/test_p2_holdout_scorecard.py backend/tests/evaluation/test_scorers.py -q`。
独占 TEMP/TMP：当前会话 visualizations 下 `t207-temp/h2map-r1-dev-20261111`；三个独占 `--basetemp` 为 `pytest-red` / `pytest-green` / `pytest-chain`。相关链使用一次命令级沙箱例外解决已知 socketpair/ASGI 宿主限制；未 skip/xfail。

## 交付与限制

- 本轮新增报告目录内仅 `report.md` 及三份证据：`evidence/tests.txt`、`evidence/test_recheck.py`、`evidence/recheck.json`；JSON 记录公开聚合、固定 hash、runner 聚合与本轮审计。
- 未读真实 H2 题号/题干/答案/逐题 trace，未改冻结数据、active、停止/重试、产品业务、预算/GO/账本；零真实调用、未 commit。
- 未跑整个仓库全量测试；本次仅运行上述必要相关链。未验证真实 H2 质量、真实模型、active 契约或发布；合成 runner 的 30 fail 是 Mock 输出的预期质量结果，不是质量通过。
- SCENARIO 与 SAFE-DIAG 不在本包。开发停止写入，交全新助手独立复验。
