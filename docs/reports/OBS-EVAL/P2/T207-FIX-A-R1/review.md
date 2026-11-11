# P2-T207-FIX-A-R1 独立复验（review）

- 复验角色：T207-FIX-A-R1 独立复验助手（全新上下文，未参与开发对话）。时点：2026-11-11 10:51–11:15 +08:00。
- 工作区：`D:/GPT项目/市场部AI知识库`，分支 `codex/p2-e2e` @ HEAD `b1bfa60`（工作区同时含未提交的 FIX-A / FIX-A-R1 / FIX-S 改动；FIX-S 三文件仍为 M）。
- 边界：真实出站 **0**（产品 Mock 路径 + 离线 pytest；`post_counters` 全空）；未读 `.env` / H1 / H2 题干 / 答案 / 密文 / key；未改代码 / 测试 / 文档 / 夹具 / 账本 / 预算 / GO；未 commit。
- 只写：`docs/reports/OBS-EVAL/P2/T207-FIX-A-R1/{review.md, evidence/verify/}`（4 份证据）；探针临时产物写在系统 TEMP（`p2-r1-verify-*`），仓外。
- 账本/预算/GO 到达=离开：`6b053520…`（1,050,298 B / 1095 行）、`79b21700…`、`79a5f318…`；只读快照的瞬时 `.lock` 已消失（目录只剩两份固定文件）。

## 0 结论

**接收（阻断 0）**。3 个阻断项均已真实闭环（测试期望与断言、plan_id 单一来源、holdout 输入稳定码 + 单测），H2 灌库方案经独立离线重跑复现（终态 / 五假设 / B=14），文档数值的枚举项逐项复算一致。

附 4 处**非阻断**数值/口径偏差（见 §6），其中 1 处建议签发前顺手改：报告与 runbook 的「B=15 → 165 请求」应为 **159**（144+15）。

## 1 逐条判定

| # | 项 | 判定 | 独立依据（摘要） |
|---|---|---|---|
| 1 | 范围合规 | **PASS（附注）** | `git diff --name-only HEAD`：只含 A/A-R1 允许面（product_adapter/cli/p2_holdout_plan/p2_public_cases/p2_score_run/新增测试/3 份 evaluation 文档/`T207/**` 计划·GO 候选·template·H2 ingest plan·evidence 脚本）。FIX-S 三文件 sha16 与 S 报告声明**逐值一致**（`aeb42766d5976e77 / 1a20cf0e00170de0 / 085a05476673c0d0`）；`p2_runner.py`、fixtures、gate/阈值、账本/预算/GO 固定路径 `git status` 全空；diff 内无新增 skip/xfail；HEAD 仍 `b1bfa60`（未 commit）。附注：`.claude/handoffs/_index.md` 的改动属经理本人；`undefined/` 仍是待清理临时目录 |
| 2 | 阻断① FIX-S 集成 | **PASS** | `test_p2_score_run.py:332-339` 已删旧注释、期望 40/0、并新增 `Q39 row.status == "pass"`；该文件复跑 **9 passed**；A report §6.1 已改为「已由 T207-FIX-S 修复（R1 更正，不再是待决项）」、§6.3/§7 同步 |
| 3 | 阻断② H2 plan_id | **PASS（附注）** | 单一来源 `p2_holdout_plan.H2_DEFAULT_PLAN_ID`；不带 `--plan-id` 跑 `p2-h2-plan`（合成元数据、计划写 TEMP）输出 `plan_id=P2-T207-H2-20261111`；GO 候选 scope.plan_id / template plan_id / runbook §8.1 命令 / build-plan.py 写 GO 处**四处同值**。旧值只以「变更说明/历史记录」形式残留（§6-N5），无默认值/命令/GO 字段级残留；全仓 grep 结果见 evidence |
| 4 | 阻断③ holdout 输入 | **PASS** | 真 CLI 子进程独立构造：两输入都缺 → exit 3 + `holdout_input_missing`、out 目录未创建；两个都给 → exit 3 + `holdout_input_conflict`、out 目录未创建；单 `--verdicts`（合成封存数据集）→ exit 0、`holdout_scorecard.json` 只含计数（30/25/5/0）+ `holdout_threshold_unapproved`、无 `case_id` 泄漏；契约 §7.4 与 runbook §8.4 两码已写入 |
| 5 | 文档数值 | **PASS（枚举项全对，另有 4 处非阻断偏差）** | 1600/653、263、1235、1482、1.592064、1.620736、145/158、8.145808、23.7881108、15.99、「全 corpus 只在请求侧不可行」、`go_plan_id_mismatch`、R1 ≤242、A report §1 表 **12/12 行 sha16+行数逐值一致**——全部复算通过；偏差见 §6-N1..N4 |
| 6 | H2 灌库方案 | **PASS** | 独立重跑产品 Mock 路径：D01 槽 4 版（1/2/3 superseded、4=published active）、D02 latest/active=2、V01/V07/D03–D06 各 v1 published、`product_revision=12`、索引 8 份 / 51 单元 / 21 chunk；五假设逐条 hold；**B=14**（逐次 9/1/1/7/4/1/2/2/2/1/1/1 → 2+1+1+2+1+1+1+1+1+1+1+1），上界 20；ingest plan（12 source、顺序即语义）/报告/模板/GO 内**无**题干/答案/H2 case_id/key |
| 7 | 两个裁量点 | **①成立 ②成立但属风险对冲** | ① 五假设确实不引用 V02；V02 电话 `010-00000099` 与 V06 `010-00000088`/D02 `010-00000001…04` 不同 → 入包确实凭空造第三组电话值。② V05 发布为 v4 后 v3（V04）state=superseded、published_at 存在 → 「v3 当前版」类题与 H5 无法同库共存；custodian §6 只声明「V04 已发布为 V3」，未声称当前版，故不冲突。建议见 §5 |
| 8 | 测试与合规 | **PASS** | 8 文件 **195 passed / 0 failed**（70.5s）；相邻 3 文件 **42 passed**；A 的 10 文件 269 基线集合现 **282 passed**（+13；无删除用例——diff 里没有任何 `- def test_`，见 §8 口径说明）；`p2-u-controls` U01–U10 全 pass、stderr **0 B**、`test_t09_mutation.py` sha 前后一致；零真实出站；固定路径 SHA 不变 |

## 2 三个阻断的闭环证据

1. **FIX-S 集成（B1）**
   - 代码：`backend/tests/evaluation/test_p2_score_run.py:332-339` —— 旧「Q39 必 fail / 不改 scorers.py」注释删除，`tallies.b0 = 40/0/0`，并逐行断言 `Q39.status == "pass"`（不是只改数字）。
   - 复跑：`pytest test_p2_score_run.py -q` → 9 passed（collect 计数 9 = A 原 8 + R1 新增 1）。
   - 报告：`T207-FIX-A/report.md §6.1` 已改「已由 T207-FIX-S 修复」；§7 回退段已注明 §7.4 随 `b1bfa60` 进 HEAD。
2. **H2 plan_id 单一来源（B2）**
   - `p2_holdout_plan.py:79-82` 定义 `H2_DEFAULT_PLAN_ID="P2-T207-H2-20261111"`；`cli.py` 的 `--plan-id` 默认取该常量；`evidence/build-plan.py` 写 GO 时 import 同常量；runbook §8.1 命令写同值；template `plan_id` 同值。
   - 实测（合成 30 题/36 回合元数据，计划写 TEMP、工作区外）：`plan_id=P2-T207-H2-20261111`、`items=145`、`total_requests=158`、`worst=1.620736`、`page_count=0`、`center_needs.ocr=0`、stdout 不含合成 case_id；`--plan-out` 落仓内 → `plan_out_inside_workspace`（exit 3、未写文件）；`--cases-metadata` 落仓内同拒。
3. **holdout 输入稳定码（B3）**
   - `cli.py:_score_holdout:829-841` 在 `load_holdout_dataset()` **之前**显式二选一；`_cmd_p2_score` 把 `RunScoreError` 映射为 exit 3。
   - 实测（子进程真 CLI）：缺 → `holdout_input_missing`；重 → `holdout_input_conflict`；两者 out 目录均未创建；单输入 → exit 0 + 只含计数的 `holdout_scorecard.json`。
   - 旧 TypeError 路径已不可达（源码里不再有 `Path(None)`/`None` 直传）；单测 `test_cli_holdout_requires_exactly_one_sealed_input` 同时断言「out 目录不存在」。

## 3 文档数值独立复算（逐项）

单位价（由 `p2_contracts` 冻结常量重算）：chat 0.018688、embedding 0.002048、rerank 0.0048、每回合四项 0.044224 —— 与文档一致。

| 项 | 文档 | 复算 | 判定 |
|---|---|---|---|
| cost §1 硬顶 / 已用 / 余 | 1600 / 547 / 653 | `HARD_MAX_REQUESTS=1600`；快照 reservation=547；653 = min(1600, plan.max_requests 1200) − 547（= preflight `requests_remaining`） | 一致（"余 653" 绑的是当前计划 1200 的上限，不是 1600；表述可再点明） |
| cost §1 阶段/项目余量 | 19.4286417 / 24.3576972 | 20.00−0.5713583 / 40.00−15.6423028 | 一致 |
| cost §2 计划 | 233 项 / 254 请求 / 8.127376 / 峰值 0.5 | `P2RunPlan` 实测同；中心 2.477376+5.65 | 一致；plan_sha256 `0b4e55a4…a194` 复算一致 |
| cost §3 三次 run | 242/15/6，7.994704 / 0.102784 / 0.04832，累计 263 / 8.145808 | 52×0.044224+22×0.002048+5.65=7.994704；2×0.044224+7×0.002048=0.102784；0.044224+2×0.002048=0.04832；合计 8.145808 | 一致 |
| cost §3.1 授权窗口 | 801 / 807 / 822 ≤1200 | 547+254 / (547+6)+254 / (547+6+15)+254 | 一致（且顺序 R3→R2→R1 与 §3 一致） |
| cost §4 中心需求 | answer_retrieval 2.938048（R1 2.344704 + R2 **0.545024** + R3 0.04832）→ 3.0094063 | 实际 R1 2.344704 + R2 **0.102784** + R3 0.04832 = **2.495808** → 含快照 0.0713583 = **2.5671663** | **不一致（非阻断）**：R2 分量写错，合计偏大；"9.0 够"结论不变（见 §6-N2） |
| cost §4 ocr | 0.5+5.65=6.15 > 6.0 → 6.5 | 一致 | 一致 |
| cost §5 H2 | 36×0.044224=1.592064；+14×0.002048=1.620736 | 1.592064 / 0.028672 / 1.620736 | 一致 |
| cost §5 全 corpus | 请求 1948（+160+107=2215）>1600；资金 12.34（+OCR 17.99） | 547+263+144+994=1948；0.5713583+8.145808+1.592064+994×0.002048=12.3449；+5.65=17.9949 | 一致；「只在请求侧不可行」成立 |
| cost §5 B 边界 | B≤146；累计侧剩 379 批 | 1100−(810+144)=146；1600−1221=379 | 一致 |
| cost §6 小计/+20% | 1235 / 1482 | 547+263+144+14+160+107=1235；×1.2=1482 | 一致 |
| cost §7 阶段/项目 | 8.7171663 / 23.7881108；含 H2 10.3379023 / 25.4088468；含 OCR 15.99 | 逐值一致（15.9879023） | 一致 |
| runbook §0/§4 码名 | `go_plan_id_mismatch` | runbook 出现 3 次，§4 停止码含该码 | 一致 |
| runbook §5 R1 账本 | ≤242 上界（含推导） | 242=208+22+12；`transcript_total_batches=4` 在 estimate-out.json 存在 | 一致 |
| runbook §8.3 B | 14 | 实测 14（见 §4） | 一致 |
| A report §1 表 | 12 行 sha16/行数 | 12/12 逐值一致（含 3 个新测试 212/193/532 与 `a0b8e12e…/67b2c26a…/5067acb5…/9011d818…`） | 一致（旧验收指出的 +1 与陈旧 sha16 已修） |
| ingest plan / template sha256 | `362e3ea1…8ed19` / `8ba3aae3…5c929` | 复算一致 | 一致 |

## 4 H2 灌库终态与假设矩阵（独立重跑）

重跑方式：本目录 `verify-probe.py` 自写探针（不改产品代码、只替换离线 embedder 记账），驱动 `T207-ingest-plan-H2.json` 的 12 source 走产品上传/解析/发布 + 一次产品索引同步；零出网。

| 文档槽 | 版本（number / state / active / units） | 用途 |
|---|---|---|
| D01_物品位置表.xlsx | 1 superseded（=V03 内容 sha）/ 2 superseded（=D01）/ 3 superseded 且有 published_at（=V04）/ **4 published + active（=V05，units 8）** | H1/H2/H3/H5 |
| D02_合作店家信息.xlsx | 1 superseded（=D02）/ **2 published + active（=V06）** | H4 |
| D03/D04/D05/D06/V01/V07 | 各 v1 published + active（units 8/7/8/6/5/5） | 基础语料 / H3 / H5 |

- 版本内容身份：v1..v4 的 sha256 与 V03/D01/V04/V05 fixture **逐字节同源**；D02 v1/v2 与 D02/V06 同源 → 灌库顺序语义确实落到正确的槽位。
- 索引：`ready=true`、documents **8**、units **51**（= 各槽当前有效版之和）、chunks **21**、`product_revision=12`、`provider_mode=offline`。
- 五假设（custodian-report §6 原文口径）：H1 仅 V03 为历史版 ✔；H2 V04 已发布为 v3 ✔（state=superseded、published_at 存在）；H3 V01 与 D01 双有效冲突 ✔（V01 v1 active 且含 D 区文案、D01 槽 v4 active 且含 B 区文案）；H4 V06 取代 D02 ✔（latest/active=2）；H5 V05 发布删行且 V07 仍有效 ✔（units 9→8，删除的正是 1 个 unit_key；V07 v1 active）。
- **B=14**：每次发布触发一次嵌入，逐次待嵌入文本数 9/1/1/7/4/1/2/2/2/1/1/1 → `sum(ceil(n/5))=2+1+1+2+1+1+1+1+1+1+1+1=14`；上界（每版独立成批）Σceil(units/5)=**20**；两者均 ≤ 代码包络 68。模板/cost §5/§6/runbook §8 已用 14（68 只作包络说明保留）。
- 出站：`post_counters = {"attempts": {}, "outcomes": {}}`、`mock_mode=true`。
- 泄漏面：ingest plan / template / GO 候选 / A-R1 报告均无 `h2-*` 形态 case_id、无 `question` 字段、无 key 变量赋值。

## 5 两个裁量点评估（给经理的建议）

**① V02 不入 H2 包 —— 理由成立，建议维持排除；但替代成本要按 159 记。**
- 事实核对：custodian-report §2 列了 V02（`variants/V02_店家联系方式变更通知.pdf`，V1，30142 B），但 §6 的五条假设只引用 V03/D01/V04/V01/V06/D02/V05/V07 —— 五假设确实不引用 V02。V02 的真实电话是 `010-00000099`，与 V06 的 `010-00000088`、D02 的 `010-00000001…04` 不同 → 入包会凭空多出一个未被假设声明的电话取值（正是 R3/C06 的冲突形态），会污染 H4 的判定语义。**排除是对的。**
- 若封存侧确认某题引用 V02：最小替代 = +1 source → 实测 **B=15**、**total_requests=159**（144+15）、worst **1.622784**；报告 §3 / runbook §8.3 写的「165 请求」是错的（见 §6-N1）。且该替代必须同时让保管方补一条「V02 与 D02/V06 的电话关系」假设，否则等于自造未声明冲突。

**② V05 发布为 v4 后「v3 当前版」类假设的拆 run 条件 —— 约束成立，属风险对冲而非缺陷。**
- 实测：V05 发布后 v3 仍是 published 但 state=superseded；「v3 当前有效版」在同一 KB 内与 H5 互斥，必须拆 run（先 V03→D01→V04 一轮，再追加 V05 一轮），代价 +1 计划/GO/run（约 +158 请求口径按新计划重算）。
- 与 custodian §2/§6 一致性：§6 只写「V04 已发布为 V3」，未写「V3 是当前版」；§4 的 36 回合也未暴露该语义。故当前单 run 方案与保管声明**不冲突**。
- 建议：签发前由经理向封存侧问**一个二值问题**——「stale_conflict 5 题里是否有题把 V04/V3 当作当前有效版」。答案「否」→ 维持单 run（158 请求）；「是」→ 拆 run 或把 V05 放到该 run 之后。不建议在不知道答案时改语料顺序。

## 6 非阻断发现（按优先级）

- **N1（建议签发前 1 分钟改）**：`T207-FIX-A-R1/report.md §3` 与 `T207-runbook.md §8.3` 的「若某题引用 V02 … B=15、**165 请求**」应为 **159**（144+15；实测 `--ingest-batches 15 → total_requests=159, worst=1.622784`）。本项不影响当前 158 的计划与预算，但会被当成替代方案的报价。
- **N2**：`T207-cost-and-quota.md §4` 的 answer_retrieval 需求分解失真——R2 记 `0.545024`，而 §3 的 R2 worst 是 `0.102784`；因此「2.938048 / 3.0094063」应作「2.495808 / 2.5671663」。中心额度 9.0 的结论不变（真实占用更小）。
- **N3**：`T207/evidence/build-plan.py` 注释写「R1 547+254=801 / R2 (547+242)+254=1043 / R3 (547+242+15)+254=1058」，是按 R1 先行推的；runbook §7 第 3 条与 cost §3.1 的最终口径是 **801/807/822**（R3→R2→R1）。仅注释漂移，无功能影响。
- **N4**：`T207-FIX-A/report.md §5` 写「R1 复跑共 **194** passed」，而 R1 evidence 01 与本次复跑是 **195**（差 1，疑为新增 holdout 输入用例前的读数）。属过时数字。
- **N5（口径说明，非缺陷）**：旧 `P2-H2-20261111` 仍以「变更说明/历史记录」形态出现 5 类位置：`p2_holdout_plan.py:80` 注释、runbook §8.1 说明句、PM decisions §9-2、FIX-A 验收记录/probe 证据、`.claude/handoffs/2026-11-10-p2-progress.md`；另有 `undefined/temp/*` 三份旧 CLI 快照（PM decisions §7 已列为待清理）。**无功能性残留**（默认值/命令/GO/template 全部已是新值），建议随 `undefined/` 清理一并处理，不阻断。
- **N6**：cost §1 「硬顶 1600；余 653」中的 653 实际是「当前计划 max_requests=1200 − 已用 547」。若后续有人把计划上限抬高，653 这个数会失真；建议写成「余 653（按计划 1200；按硬顶 1600 为 1053）」。

## 7 复跑命令与证据索引（4 份）

- `evidence/verify/verify-probe.py`：自写探针（A 数值复算 / B CLI 独立构造 / C H2 灌库重跑），零真实调用。
- `evidence/verify/probe-out.txt`：探针原始输出（含上述全部读数；A 表 12/12、B 全部 exit/code、C 终态与 B=14）。
- `evidence/verify/h2-state-rerun.json`：H2 灌库独立重跑结果（12 source + 13 source 两轮）。
- `evidence/verify/pytest.txt`：8 文件（195）、逐文件 collect 计数、相邻 3 文件（42）、A 的 10 文件 269 基线集合（282）、`p2-u-controls`（U01–U10 全 pass / stderr 0 B / 测试文件 sha 不变）。

命令（仓库根，全部离线）：
```
.venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207-FIX-A-R1/evidence/verify/verify-probe.py --out-h2 .../h2-state-rerun.json
.venv/Scripts/python.exe -B -X utf8 -m pytest <8 files> -q -p no:cacheprovider
.venv/Scripts/python.exe -B -X utf8 -m pytest <3 files> -q -p no:cacheprovider
.venv/Scripts/python.exe -B -X utf8 -m pytest <A 的 10 files> -q -p no:cacheprovider
.venv/Scripts/python.exe -B -X utf8 -m mktkb.evaluation.cli p2-u-controls --out <TEMP>\u-controls.json
```

## 8 限制 / NOT-RUN

- 未跑真实 `p2-run`（含 dry-run）、未发任何真实请求、未跑 OCR / Ragas / 全仓 pytest / 前端。
- H2 的 30 题真实评分未执行（按边界禁止）；本 review 只覆盖「灌库状态 + 计划规模 + 聚合器输入契约」，不产出 H2 质量结论。
- H2 灌库重跑用的是产品 **Mock/offline** 适配器：B=14 是「产品 chunker + content_sha256 缓存语义 + batch=5 拆分」下的离线值，与 cost §5 的口径一致，但不是真实 provider 的 POST 实测。
- `p2-score --visibility holdout` 的「单输入正常聚合」用**合成封存数据集**（TEMP，自有 key/密文/manifest）验证代码路径；不读真实 H2 密文/key。
- 「269 基线不回退」以 A 的 10 文件集合复跑（282 passed = 269 + 13）+ 无删除用例证明。**口径说明**：A 未留逐文件计数；按当前逐文件计数（8/5/9/35/21/71/38/23/64/8）与 S review 的 HEAD 基线（test_p2_scoring 27 条）推算，+13 = FIX-S +11（27→38）+ R1 +2（score_run 8→9、public_cases 加断言/用例）；若 public_cases 只是加断言未增用例，则另一处 +1 无法逐文件对齐（不影响「全绿且无删除」的结论）。无法回退 FIX-S 复现 269 本身（会改动 FIX-S 文件，越界）。
- 未独立验证 `p2_runner.py` 的 B-R1 语义（属另一验收线）；只在套件中被动运行。
- 只读快照会瞬时创建并删除账本旁 `.lock`（产品设计），已确认目录无残留、SHA 未变。

## 9 给经理的最小决策

1. **接收 A-R1**（阻断 0）；提交次序仍须 **A（含 R1）先、FIX-S 后**（S 的单测 import 了 A 的 `p2_public_cases`）。
2. **签发前**：把「B=15 → 165 请求」改成 159（报告 + runbook 各 1 处），顺手改 cost §4 的 R2 分量与合计，并把 A report §5 的 194 改成 195；同时清理 `undefined/`。
3. **H2 签发前问封存侧 1 个二值问题**：是否有题把 V04/V3 当成当前有效版（见 §5-②）。答案为「是」再拆 run。
4. **V02**：维持排除；若封存侧确认引用，按 +1 source / B=15 / 159 请求并补一条电话关系假设。

## 10 最终建议

**接收（阻断 0）**。3 个阻断项都有代码 + 单测 + 可复跑的稳定码/断言闭环；H2 灌库方案在同一 KB 状态上五假设全 hold、B=14 可独立复现；文档枚举数值逐项复算一致。剩余 4 处偏差都是数字/注释级，其中「165→159」建议在签发前改掉，其余列入收口清单，不影响接收判断。
