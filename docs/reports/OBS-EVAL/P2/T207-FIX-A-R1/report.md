# P2-T207-FIX-A-R1 开发报告：3 阻断闭环 + H2 灌库方案（零真实调用）

- 角色：T207-FIX-A-R1 开发助手（全新上下文）。开工 HEAD `b1bfa60`，工作区另含 FIX-S 未提交改动（`p2_scoring.py`/`scorers.py`/`test_p2_scoring.py`，本包未读改）。
- 边界：真实出站 **0**（全程 Mock 产品路径 + 纯函数/离线 pytest）；未读 `.env`/H1/H2 题干/答案/密文/key；未改 fixtures/期望/门槛/账本/预算/GO 固定路径、`p2_runner.py`、FIX-S 三文件；未新增 skip/xfail；未 commit/push。
- 账本/预算/GO 到达=离开：`6b053520…`（1,050,298 B / 1095 行）、`79b21700…`、`79a5f318…`。
- 证据 4 份：`evidence/01-pytest.txt`、`04-u-controls.txt`、`h2-state-probe.py`、`h2-state-out.json`。

## 1 阻断项（逐条闭环）

### B1 FIX-S 集成：套件红 -> 全绿
- `backend/tests/evaluation/test_p2_score_run.py:332-339`：删除「Q39 必 fail / 不改 scorers.py」的过时注释，期望改 **40/0**，并新增 `Q39 row.status == "pass"` 断言（把「FIX-S 已修好」钉住，而不只改数字）。
- A report §6.1 改为「已由 FIX-S 修复、不再是待决项」，§6.3/§7 同步（见 §2）；HEAD/基线标注改 `b1bfa60`。
- 复跑：该文件 **9 passed**；与 FIX-S 的 `test_p2_scoring.py` 同批 **195 passed / 0 failed**（evidence 01）。

### B2 H2 plan_id 统一（单一来源）
- 新增 `p2_holdout_plan.H2_DEFAULT_PLAN_ID = "P2-T207-H2-20261111"`；`cli.py` 的 `--plan-id` 默认值、`evidence/build-plan.py` 写 GO 处、runbook §8.1 命令三处同值（旧默认 `P2-H2-20261111` 删除）。
- 实测：不带 `--plan-id` 跑 `p2-h2-plan` 得 `"plan_id": "P2-T207-H2-20261111"`，签发链不会再撞 `go_plan_id_mismatch`；候选 GO 的 `scope.plan_id` 未改（本就正确）。

### B3 `holdout_input_missing` 落码
- `cli.py:_score_holdout` 入口（读 manifest/解封**之前**）显式二选一：都缺 -> `holdout_input_missing`；都给 -> `holdout_input_conflict`；均 exit 3、**不写任何产物**。
- 测试 `test_cli_holdout_requires_exactly_one_sealed_input`（缺/重两例，含「out 目录不存在」断言）；契约 §7.4、runbook §8.4 写入两个稳定码；旧 `TypeError` 路径已不可达。

## 2 非阻断项（同包修正）

| # | 项 | 处理 |
|---|---|---|
| 4 | cost 数值 | §1 硬顶 1000→**1600**、余 453→**653**；§6 公开 255→**263**、灌库 68→**14**、小计 1281→**1235**、+20% 1537→**1482**（1600 结论不变）；§5 H2 worst 6.368256→**1.592064**（36×0.044224；旧文把 144 请求当 36 回合、多乘 4 倍）+14 批 = **1.620736**；§7 公开 8.588048→**8.145808**、阶段 9.1594063→**8.7171663**（含 H2 **10.3379023**）、项目总 24.80→**23.7881108**、含 12 页 OCR 21.18→**15.99 可行**；全 corpus 结论改为「**只在请求侧不可行**（1,948 > 1600），资金 12.34 可行」 |
| 4b | runbook | §0 旧 GO 拒因 `go_plan_sha256_mismatch`→**`go_plan_id_mismatch`**（§4 停止码补该码）；§5 账本增量 R1 242→**≤242** 并给出上界推导（只给当前有效版建索引 + content_sha256 缓存复用） |
| 5 | A report 陈旧 | §1 表 12 行**逐文件重算** sha16/行数（含 R1 改动），注明旧表 11 行 +1、`test_p2_public_cases.py` sha16 陈旧；§5 验证换成 R1 新结果；§7 注明 §7.4 已随 `b1bfa60` 进 HEAD、`git checkout --` 回退不掉 |
| 6 | u-controls 解码 | `text=True` → `encoding="utf-8", errors="replace"` + 子进程 `PYTHONIOENCODING=utf-8`。前/后实测：旧形态 stdout **0 字符** + `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xcf`（stderr 2,128 B）；新形态 563 字符 /「13 passed」/ stderr **0 B**；`p2-u-controls` 实跑 U01–U10 全 pass、stderr 0 B |
| 7 | clarification 只判 kind | 定性为**评审口径问题**（非本包引入缺陷）：不改冻结判据，模块头把「更严」更正为「**更松**（只判 expected_kind）」；`test_p2_public_cases.py` 加断言钉住 C01–C04 的空值 + 措辞入 notes，防被读成「措辞也对」 |

## 3 H2 灌库方案与批数 B（新增）

- **方案文件**：`docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json`（`p2-ingest-plan/v0.1`，sha256 `362e3ea1…8ed19`），12 个 source、**顺序即语义**：
  V03(建槽,name=D01) → D01(v2) → V04(v3) → V05(v4) → D02(v1) → V06(取代 D02 v2) → D03 → D04 → D05 → D06 → V01 → V07。
- **离线验证**（产品 Mock 路径，零真实/零出网）：`evidence/h2-state-probe.py` 走产品 HTTP 上传/解析/发布 + 产品索引同步，终态（`h2-state-out.json`）：
  D01 槽 latest=4/active=4（v1 V03 `superseded`、v2 D01 `superseded`、v3 V04 `superseded` 且有 `published_at`、v4 V05 `published`）；
  D02 槽 latest=2/active=2（v2=V06）；D03–D06/V01/V07 各 v1 `published`；revision=12、索引 8 份资料/21 chunk；
  **五条假设逐条 hold=true**：H1 仅 V03 是历史版；H2 V04 已发布为 v3；H3 V01 与 D01 双有效（1 vs 4）；H4 V06 取代 D02（888 覆盖 001）；H5 V05 已发布且删行（单元 9→8）、V07 仍有效。
- **结构约束（如实）**：H2 与 H5 写同一版本槽——V05 发布为 v4 后，v3 只保留在**版本历史**里、不再是当前有效版。
  若某题要求「v3 就是当前版」，它就与 H5 无法同库共存；最小替代是拆两次 run（先 V03→D01→V04，再追加 V05），代价 +1 计划/GO/run。**不自行改题**。
- **V02 不入包**（判断+依据）：五条假设都不引用 V02，而 V02 的电话（010-00000099）与 V06 的（010-00000088）不同，入包会凭空造出
  未声明的电话冲突（正好是 R3/C06 的形态）。若保管方确认某题引用 V02，最小替代是加 1 个 source（B=15、165 请求），由经理决定。
- **批数 B = 14**（产品 chunker + 产品缓存语义离线实算）：每次发布触发索引同步，只给当前有效版建索引、按 content_sha256 复用缓存，
  真实 provider 按 batch=5 拆 POST ⇒ 逐次待嵌入文本 9/1/1/7/4/1/2/2/2/1/1/1 ⇒ **2+1+1+2+1+1+1+1+1+1+1+1 = 14**；上界口径 Σceil(单元/5)=**20**。
- **计划命令与预期**：`p2-h2-plan --cases-metadata <工作区外> --holdout-manifest docs/evaluation/p2-holdout-v2.manifest.json --ingest-batches 14 --plan-out <工作区外> --plan-id P2-T207-H2-20261111`；
  实测输出 **items=145 / total_requests=158（144+14）/ page_count=0 / worst 1.620736 / ocr 中心 0**。模板 `T207-plan-h2-v0_1.template.json` 的 scale 已替换 68 占位（sha256 `8ba3aae3…5c929`），cost §5 与 runbook §8 同步（路径/顺序/预期终态/B/审计项）。

## 4 验证（题述 7 文件 + FIX-S；不跑全仓）

- `01-pytest.txt`：8 文件（题述 7 + `test_p2_scoring.py`）**195 passed / 0 failed**（54.16s）；追加 `test_p2_public_controls`/`test_gate_quality`/`test_p0_acceptance` **42 passed**。
- H2：生成器合成跑通（145/158/1.620736）；灌库终态与 B 见 §3；`post_counters` 全 0、`mock_mode=true`（零真实出站）。
- 固定路径 SHA 前后一致（见头部）；未写 run 产物/账本；`git status` 无 fixtures/GO/预算/账本改动，无新增 skip/xfail。

## 5 限制

- H2 真实 30 题未跑（按边界禁止）；本包只验证「灌库状态 + 计划规模」，不产出 H2 质量结论。
- H2/H5 的「v3 是否必须为当前版」只能由封存侧（保管方/经理）判定——本包给出两种口径与代价，不替其改题。
- R1 的真实 embedding POST 数未实测（未真实 run），runbook 只给「≤242」的上界口径；核账以账本 reservation 为准。
- 未跑全仓 pytest、未跑真实 `p2-run`；FIX-S 三文件与 `p2_runner.py` 未改（仅被动运行其测试）。
