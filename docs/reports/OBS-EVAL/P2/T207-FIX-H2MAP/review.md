# T207-FIX-H2MAP 独立验收：FAIL（主人，存在 1 项阻断）

- 基线：`d7728db35655ae67569aec84cc4ededeaf7f7c13`；评审工作区未提交 H2MAP diff，开发已停止写入。
- 独立助手未修改源码/开发测试/契约/冻结数据/预算/GO/账本，未 commit、未真实调用、未读取真实 H2 题号/题干/答案/逐题 trace。
- 结论：开发自报 190 passed 已独立重跑覆盖，但不能覆盖下列反例；本包拒收，不能进入映射通过结论。

## 阻断 B1：source_index 遮蔽产品显式 locator 版本冲突

- 位置：`backend/src/mktkb/evaluation/p2_scoring.py` 的 `_source_identity`（当前 457–484 行）。
- 合成金标：`V04 + unit_key=key + locator={sheet:synthetic,row:7}`，按映射期望 `D01/v3`。
- 产品明确给出：`version_number=3`，同时 `locator={sheet:synthetic,row:7,version_number:4}`。
- 同一产品行的 evidence 给同一个 `unit_id` 的正确 unit_key/原 locator；索引通过真实 `source_index_from_rows` 生成，分别测试“索引未声明版本”和“索引版本=3”。
- 实际：两种输入均判 `pass`、issues=[]；期望：显式产品版本字段互相冲突必须稳定不通过（例如 `source_version_conflict`）。
- 原因：非空索引 locator 先覆盖了产品 locator；随后只检查被选中的 locator，产品已经声明的 `version_number:4` 不再参与冲突检查。
- 边界：这不是“产品缺 locator、用权威索引补全”的情况；产品两个字段已明确互相冲突。对照索引版本=4，当前会正确报 `source_version_conflict`。
- 复现：`.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/T207-FIX-H2MAP/evidence/independent/probe.py`。
- 独立红例：`test_independent.py::test_explicit_product_locator_version_conflict_blocks[None/3]`，均 `DID NOT RAISE P2ScoringError`；输入/输出见 `counterexamples.json`。

## 必检结果

| 项目 | 结论 | 独立依据 |
|---|---|---|
| acceptance 配方与 H2 顺序；映射不等于 active | PASS | 只读核对 acceptance manifest 与公开 ingest-plan：D01 的 V03/D01/V04/V05 为 v1/v2/v3/v4，D02/V06 为 v1/v2；enterprise 不作本 H2 身份依据 |
| V04 命中 v3；错/缺/bool/str/float/非正版本、unit_key 与原 locator 合取 | PASS | 自有合成探针 + 现有 H2MAP 定向回归；同 citation 合取、错误答案/拒答检查保持 |
| 产品版本与所有已给 locator/index 版本冲突不通过 | FAIL | B1；已有 index 冲突保护不覆盖 raw product locator 被索引遮蔽的分支 |
| 普通 D01、公开 P2/P1 默认逐值不变 | PASS | 自行从 git 基线载入评分器，R1 52/R2 2/R4 3 条分数、scorecard、57 轮默认归一相等，并与公开归档相等；P1 scorer/runner 归一换行字节相同 |
| 缺/坏 schema/重复 key/冲突 map、导入乱序/缺版本稳定 block | PASS | 独立执行现有定向回归，包括完整公开 H2 ingest 配方的 runner 评分边界；错误均不计 pass |
| forbidden 可未导入；错版本不能冒充禁用来源 | PASS | 自有 v2/v3/v4/缺版单变量：仅 v3 命中 forbidden；公开已有未导入来源回归通过 |
| value/kind/should_refuse、诊断口径、error/skipped 保留 | PASS | 自有逐 check 对照及 error/skipped/skipped_requires_ocr/unknown 对象身份保留；源码与基线均按任一 check fail 判 fail，未将检索诊断 metrics 新增为 check |
| 真实 runner 合成 Mock E2E、停止/隔离/P1 | PASS | 真 run_p2 + ProductEvalAdapter + MockChatBackend/MockTransport；3 次公开版本上传后执行 30 条合成问题，无 ask_turn 直接 return 替身；30 fail/0 pass/0 error、无 unmapped、local_mock/real_calls=0、逐题产物与 trace 清除；既有停止回归通过 |
| 固定 hash、网络 guard、无 skip/xfail/断言删除 | PASS | public-diff.json 三固定 hash 与交接一致；独立 E2E 外部 attempts=[]（仅 asyncio 本地回环）；git diff --check 通过，开发测试只新增，无新增 skip/xfail |
| 真实 H2 质量/active 契约、真实模型与发布 | NOT-RUN | 本包禁止真实调用与真实 H2 明细；映射验收不证明整个 T207 或 P2 质量通过 |

## 执行与证据

- 一次命令级沙箱例外离线执行（默认 socketpair/ASGI 挂起属已知宿主限制），未加 skip/xfail。
- 项目 `.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider`；自有 `test_independent.py` + `test_p2_holdout_source_map.py test_p2_score_run.py test_p2_scoring.py test_p2_holdout_scorecard.py test_scorers.py`。
- 独占 TEMP/TMP：当前 visualizations 下 `t207-temp/h2map-independent-20261111`，`--basetemp .../pytest-1`；退出码 1：**212 passed、2 failed、1 条既有弃用 warning，7.83s**；未重跑同链。
- 只写本 `review.md` 及 `evidence/independent/`：`probe.py`、`counterexamples.json`、`test_independent.py`、`tests.txt`、`public-diff.json`、`runner-e2e.json`。
- 证据中仅合成输入/公开聚合/固定 hash，无真实 H2 明细。进程已结束；本独立助手停止写入，交经理派新上下文最小返工。
