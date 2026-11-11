# T207-FIX-H2MAP-R1 独立复验：PASS

主人，本包 H2 版本来源映射及 R1 显式双定位冲突修复通过独立复验；不代表真实 H2 质量通过。

- 评审对象：HEAD `d7728db35655ae67569aec84cc4ededeaf7f7c13` 上当前未提交最终源码；开发已停止写入。
- 本助手只新增本报告及 `evidence/independent/` 自有证据；未改源码、开发测试、旧 review/旧证据、冻结数据、预算/GO/账本，未 commit，未读真实 H2 题号/题干/答案/逐题 trace，零真实调用。
- 源码重点：`p2_scoring.py::_source_identity` 的 H2 opt-in 分支同时检查产品原始 locator 与实际选用 locator 的版本断言；raw/index 同键冲突抛稳定 conflict。产品 `version_number` 是唯一版本身份；有效定位版本不能补足缺失/坏类型的产品版本。默认 False 路径选择逻辑保持原样。

| 必检项 | 结论 | 本轮独立依据 |
|---|---|---|
| 原 B1 两分支：product3/raw4，index 无版或 index3 | PASS | 保留原独立测试的两个分支，当次均按预期 conflict；新增真实 runner 评分边界检查，均记 error 并发出 `holdout_case_unscorable`/`source_version_conflict`，不计 pass |
| 所有显式版本与 raw/index 原定位冲突 | PASS | 新增 8 个边界：row/sheet/heading/page 冲突、raw0/raw3.0/indexFalse/index4；稳定 `source_locator_conflict` 或 `source_version_conflict`。现有 bool/string/null/错误版本合成回归全过 |
| 产品缺/坏版本不能由 locator/index 补足 | PASS | 新增缺字段、bool/string/float/0/负数 6 个用例；raw/index 均声明3仍 fail，归一 citation 不产生版本身份 |
| 原 locator/unit_key 合取、单边缺键 | PASS | 新增 3 个一致/单边缺字段边界；不合并造值。原 locator 未命中不能因 unit_key 匹配绕过 |
| 映射依据及导入顺序、稳定 block | PASS | 只读 acceptance manifest 与公开 H2 ingest-plan；D01 槽 V03/D01/V04/V05 为1/2/3/4，D02/V06为1/2；完整公开配方、缺映射/坏schema/重复键/身份冲突/乱序/缺期望版本回归全过。映射不宣称 active |
| 错版本与禁用来源、状态/诊断口径 | PASS | 原独立合成 forbidden v2/v3/v4/缺版仅v3命中，未导入 forbidden 保持允许；error/skipped/skipped_requires_ocr/unknown 对象身份保留；value/kind/should_refuse 对照保留。源码仅替换版本来源 check；原 scorer 本就按任一 check fail 判 fail，未把检索诊断 metrics 提升为质量 check |
| 公开 P2 默认57条与 P1 | PASS | 自行从 git 基线载入 scorer：R1=52/R2=2/R4=3，case scores及scorecard逐值相同并与公开归档相同，57轮默认归一逐值相同；P1 scorer/runner 归一换行后字节相同 |
| 真 runner Mock E2E、停止/隔离语义 | PASS | 当次执行旧独立 E2E 的自有副本：真实 run_p2 + ProductEvalAdapter + MockChatBackend/MockTransport，3次公开版本上传，完整30题；30 fail/0 pass/0 error、无unmapped、local_mock/real_calls=0，逐题产物及trace已清除。停止/隔离现有相关链通过；源码 runner 差分仅映射/覆盖门禁，无停止/重试变更 |
| 固定hash、guard、文件保护 | PASS | 三固定hash与交接一致；公开差分 external=[]，E2E external=[]、仅 asyncio 本地回环；16个保护文件（5源码/开发测试+11旧报告证据）前后hash一致；git diff --check退出0；无新增skip/xfail或删除既有断言 |
| 真实 H2 质量、真实模型、active 契约、发布 | NOT-RUN | 本包禁止真实调用和真实 H2 明细；不以合成 Mock 的30 fail宣称质量通过 |

## 本轮执行与证据

- 独立链：**255 passed，1条既有 Starlette/httpx 弃用 warning，13.45s，退出0**。原独立测试原文复制后在新证据目录执行，另新增19个独立 R1 边界；没有使用开发236 passed作为验收替代。
- 命令：`.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider docs/reports/OBS-EVAL/P2/T207-FIX-H2MAP-R1/evidence/independent/test_r1_independent.py backend/tests/evaluation/test_p2_holdout_source_map.py backend/tests/evaluation/test_p2_score_run.py backend/tests/evaluation/test_p2_scoring.py backend/tests/evaluation/test_p2_holdout_scorecard.py backend/tests/evaluation/test_scorers.py --basetemp <TEMP>/pytest-chain -q`。
- `PYTHONPATH=backend/src;backend/tests;backend/tests/evaluation`；TEMP/TMP独占 `C:/Users/dell1712/.codex/visualizations/2026/11/11/01a1c9e9-c47f-78e3-be5e-9d500113813d/t207-temp/h2map-r1-independent-20261111`。一次最小命令级沙箱例外避开已知 socketpair/ASGI宿主挂起；无skip/xfail。
- 自有证据：`evidence/independent/{test_r1_independent.py,tests.txt,public-diff.json,runner-e2e.json,before-hashes.json,after-audit.json}`。证据仅合成输入、公开聚合和固定hash。
- 账本 `1648405845fd5e19b593e610b92f8505fdfd78a9e57079648dc14673576785d7`；budget `79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e`；GO `3ed427f42ac2eeedff489505b94f730eadba1dc38f1b9adecf94d25750b02a7c`。
- 未跑仓库全量；SCENARIO及SAFE-DIAG留待后包。无本轮剩余阻断。进程已结束，本助手停止写入。
