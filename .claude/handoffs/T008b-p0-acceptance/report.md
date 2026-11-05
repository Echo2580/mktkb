# T008b · P0 七条验收测试 + p0-report（P0 第 14 包）开发报告

> 基线：`p0/obs-eval` @ `5152298`（纯簿记；代码基线 `f2c0209` T008a）。本包单 commit
> `p0/T008b p0 acceptance`（sha 见 `git log -1` / 交付回执），未 push。
> 默认门禁仍是 `exit 3 / thresholds_unapproved`；真实 baseline 与阈值审批属 T009 人工门，未建立。

## 1. 完成内容

- 新增 `backend/tests/evaluation/test_p0_acceptance.py`（26 708 B / 7 项）：设计 §11 七条验收逐条落地，
  每条独立可失败；业务问答走真实 HTTP + 真实检索 + 确定性模型替身，评测走真实 `run_suite`/CLI。
- 新增 `backend/tests/evaluation/golden/chat_response.json`（4 244 B / sha256 `b86484dc…8e52`）：
  归一化后的业务行为快照，`_meta` 记录采集 commit、采集命令、场景、归一化清单与"只断言不记录"的头。
- `backend/tests/evaluation/conftest.py`：**只追加** 3 个 fixture 引用（原样复用 `observability.conftest`
  的 `trace_chat_app`/`trace_settings`/`trace_db_path`），未复制 app 装配、未改任何既有 fixture。
- 新增 `docs/reports/OBS-EVAL/P0/p0-report.md`（104 行）：逐条命令 + 结果 + sha256 锚 + 未测边界 + 免责句原文。
- 证据 4 份：`docs/reports/OBS-EVAL/P0/evidence/T008b/01..04`（TDD 红绿/变异、CLI 全流程、目录、全量）。
- 未改业务/观测/评测实现与既有断言；未新增依赖；未读 `.env`；无 `--allow-holdout-details`；未 push。

## 2. §5 逐条自证（≤2 行/条）

1. **七条齐备非空转**：7 个测试对应 §11；变异 M1（去掉 `X-Trace-ID`）→ #1/#2 红；M2（禁用
   `security_leak` 上报）→ #6 红（exit 3≠1）；两处变异已 `git checkout` 还原、`git diff` 0 行（证据 01 §C/§D）。
2. **golden 可信**：仓库外脚本在 `5152298` 采集，测试只读不回写；`_meta.normalised_fields` 与实现逐字断言；
   6 项归一化（UUID/时间戳/记录短码）显式剔除；连续两次独立重采字节 sha256 相同（证据 01 §E）。
3. **p0-report 完整**：七条命令/结果/证据锚（路径 + sha256）、未测边界（live→4、真实 baseline、
   真实 OCR/embedding/rerank/模型、P1 质量）、设计免责句原文、`unapproved` 与 T009 均写明。
4. **口径一致**：b0 40/32（8 OCR，pass 29/fail 3 = Q25/Q26/Q31）、badcase 10/13（pass 9/fail 4）、
   `index_revision` 6/4、`pipeline_version` 735da1397044，与 T005/T006b 实测一致；测试计数 313→320、1586→1593。
5. **硬约束**：无业务行为变化（golden + 既有 integration 全绿）；零真实调用（provider/socket/.env 守卫）；
   无新依赖；无 `--allow-holdout-details`（CLI 实测 exit 2）。
6. **测试与回归（策略 A）**：本包 7 passed（7.21 s）；目录 320 passed（18.52 s）；全量 1593 passed /
   0 failed / 0 error（381.02 s = 6:21）；已知 flake 未命中。

## 3. 实际运行结果

- 七条：#1 归一化响应 == golden 且带 `X-Trace-ID`；#2 trace 记录 `request_id`+Span 且只读重开可查；
  #3 两 suite 独立三件套；#4 manifest/summary/trace 三处版本一致；#5 默认 gate=3 且拒绝审批 →
  测试内审批配置 gate=0、baseline `c0ce2856938f`、diff `release_allowed=True`、报告落盘；
  #6 敏感来源 → `security_leak` → exit 1；#7 spy/socket/.env/模型调用全为 0。
- `pytest backend/tests/evaluation/test_p0_acceptance.py` → **7 passed**（7.21 s）。
- CLI 全流程（产物只在 `%TEMP%\t008b-p0-flow`）：dataset validate 0/0；run b0/badcase local 0/0；
  b0 replay 0；默认 gate b0/badcase/replay 均 **3**（`hard_failures=[]`、`quality=unknown`、
  `config_status=unapproved`）；`baseline approve` 3 且 `approval.json`=0；无 baseline `diff`/`export` 3；
  `--mode live` 2；replay 缺 `--from-run` 3；`--allow-holdout-details` 2；
  测试内审批配置 gate 0 / approve 0 / diff 0（`release_allowed=True`）/ export 0；回到默认配置 gate 3。
- 报告件 sha256：`gate.json` `7690cad1…b870`、`diff.json` `e7302b4b…756f`、`report.md` `d9f1a139…bc45`、
  `report.html` `5196be63…4884`；`gate_v0_1.json` 前后 sha256 不变；工作树无 `var/` 变更。
- 本 commit 只含 2 个测试交付 + `p0-report.md` + 4 证据 + 本报告；`git show --stat --oneline HEAD` 可复现。

## 4. 偏离与未做

- 测试内审批配置是 `gate_v0_1.json` 的**子集**（检索 5 + 答案 5，`min_sample=1`、宽松阈值），
  故意不覆盖 refusal/runtime：离线跑没有成本样本，全指标配置必然 unknown。它只演示机制，不是 T009 审批。
- #7 的 socket 守卫只包评测全流程：`TestClient` 的 asyncio 自管道是 loopback socketpair，
  业务阶段改用 provider/.env/模型替身守卫（模型 `calls == []`），已在报告与测试注释写明。
- 未跑 live（P0 参数层即拒，exit 2/3；`evaluate_gate` 的 live→4 只有单测覆盖），p0-report 记为 NOT-RUN/GAP。
- 未建立真实 baseline、未审批阈值、未伪造 `approval.json`；未跑真实 OCR/embedding/rerank/模型。

## 5. 风险与遗留

- golden 的文字断言依赖 RAG 枚举作答文案；业务代码若合理改文案需按新 commit 重采 golden 并更新
  `_meta`（测试会因 `normalised_fields`/正文不一致而红，属预期门禁）。
- 归一化把答案里的「记录 8 位短码」替换掉：它由随机 version UUID 派生，无法保留原值；
  若未来改短码生成方式，golden 仍需重采。
- 采集/变异驱动脚本只在 `%TEMP%`（未入库）；复现命令与归一化清单已写进 p0-report §1/§7，
  p0-report 的 sha256 锚可校验入库证据。
- 全量 6:21；已知 flake `test_g08_short_budget_cancels_inflight_model_call` 本轮未命中，若命中需隔离复跑。

## 交接摘要（≤10 行）

- 交付：`test_p0_acceptance.py`（7 项）+ `golden/chat_response.json` + conftest 只追加 + `p0-report.md` + 4 证据 + 本报告；单 commit，未 push。
- 七条全绿且各自可失败：M1 去 `X-Trace-ID` → #1/#2 红；M2 禁用 `security_leak` → #6 红；均已还原。
- golden 由仓库外脚本在 `5152298` 采集（业务代码未变），6 项归一化，两次重采字节相同。
- 默认 gate = exit 3 / `thresholds_unapproved`；真实 baseline 待 T009；报告未声明质量达标。
- live→4 为 NOT-RUN/GAP；P0 当前不放行任何版本（无 baseline + 阈值未审批）。
- 测试：7 + 320 + 1593（0 failed/0 error，6:21）；零真实调用、未读 `.env`、无新依赖。
