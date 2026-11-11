# P2-T207-FIX-SCORE 独立验收（评分口径：value_no_fabricated 证据 grounding）

**结论：接收（任务 1-6 全部 PASS；第 7 项已给建议，无 FAIL）。**

- 验收基线：分支 `codex/p2-e2e`、HEAD `edeeefd37c5bdb4fa2d011f4a526d4c827d7db0c`；本包代码
  sha256 前 16：`scorers.py 8c2715661997cecb`、`p2_scoring.py 2d40963176de02f2`（与报告一致，
  验收前后未变）。
- 零真实调用；只写本目录 `review.md` 与 `evidence/verify/`；未碰并行包、账本/预算/GO；未 commit。
- 独立重跑 R1 的三份产物与开发 `scoring/R1-fixed/` **逐字节相同**（scorecard/case_scores/p2_decision）。

## 逐条判定

### 1. 范围 / 不 commit / 无 skip-xfail：PASS

- `git diff --numstat HEAD` 中本包只有：scorers.py +81/−7、p2_scoring.py +10/−1、
  test_p2_scoring.py +160/−1（唯一删除是 import 行替换）、test_p2_gate.py +31/−0、
  test_p2_public_controls.py +66/−0；新增目录只有本报告目录与 `scoring/R1-fixed/`。
- 测试无删除的 `def test_`，无新增 skip/xfail；82 条实跑 0 skipped。
- 未改 `fixtures/**`、`docs/evaluation/gate_v0_3.json`、`p2_live.py`、账本/预算/GO、业务回答代码；
  HEAD 未变、staged 为空、reflog 无本包 commit。
- 工作区另有并行包改动：copy.py/conversations（FIX-CONFLICT）、p2_runner.py + `docs/evaluation/p2-dataset-v0_1.md`
  （FIX-H2SCORE，注释明示包名）、`_index.md`（PM）。均不在本包允许清单内，未纳入本包验收。

### 2. 默认口径与 HEAD 逐字节一致（关键）：PASS

- 用 `git archive HEAD backend/src` 解压到工作区外临时目录作为 old，工作区 `backend/src` 作为 new；
  只调默认参数（不传 `allowed_number_keys`）：
  **fixtures 480/480、真实行 55/55 的 `CaseResult.to_dict()` JSON 逐字节相同**
  （`order_only=0`、`value_diff=0`，含 evidence 键序）。输入比开发证据 02 的 240 条多了
  "同一答案无引用"变体，结论更强。
- 默认路径 `value_no_fabricated` 的 evidence 仍是 `{"extra":[...],"checked":N}` / `{"checked":N}`，
  无 `evidence_numbers`；默认口径下 Q09-Q24 仍全部 fail（extra 与旧一致），R3 C06 仍 fail（17 条）。
- 生产代码唯一 opt-in：`p2_scoring.score_public_case` 第 890 行；`runner.py` 的 5 处
  `score_case(...)` 全部默认；`gate.py`/`exact_value_contract` 只用 `check_value` 重算。

### 3. 判定正确且不放宽：PASS（附两项已知边界）

独立构造并实跑（Q09 冻结题）：

| 构造 | vnf | case |
|---|---|---|
| 回显整行 + 引用 row5（真实 locator） | pass | pass |
| 同一答案，清空 sources | fail（extra=['1','18']） | fail |
| 原文 + "另有 7 家"（引用行无 7） | fail（extra=['7']） | fail |
| locator 仅 document_name/file_name/path（含 D02） | fail（extra=['2']，keys=[]） | fail |
| locator 仅整数键 row=5/header_row=4/column_index=3 | fail（extra=['5']） | fail |
| locator 键名 cell_18、display 无数字 | fail（extra=['18']） | fail |
| source 级 document_name="D02_..."、locator 无数字 | fail（extra=['2']） | fail |
| retrieved 的 display="7"，citations 空 | fail（extra=['7']） | fail |
| facts 的 value="7"，citations 空 | fail（extra=['7']） | fail |
| citation.text="…分机 8021" | pass（默认仍 fail） | pass |

- Q09-Q24 的旧 extra **100%** 落在被引用行的 `cells[].display`（逐条 2/2 或 1/1，无部分命中）。
- 两项边界（不阻断，建议 R4/H2 前处理）：① 实现取 locator **全部字符串值**，构造
  `number_format="0.00"` 会允许 "0"、`sheet="2026Q4"` 允许 "2026"/"4"、`column="A1"` 允许 "1"
  （R1/R2/R3 实测只有 display/heading 含数字，故不影响本次 38/40）；② 允许集是"本轮全部引用"的
  并集而非逐条声明，多引一行含 "8" 即可让"另有 8 家"通过 vnf（Q09-Q24 每题仅 1 来源，未触发）。
  建议 H2/R4 前把抽取收窄到 `cells[].display`/`heading`/text，或按 expected source 匹配引用。

### 4. R1 重评分复现：PASS

- 独立 `p2-score` 重跑 R1（输出到工作区外）：**b0 38/40、exact 24/24、OCR 7/8、negative 7/8**；
  剩余失败 Q25（value_hit）、Q33（source_hit）、N08（kind_correct+refusal_expected）。
- 与旧评分对比：case status 变化 16 条（仅 Q09-Q24）且均为 `value_no_fabricated fail->pass`；
  check status 零其它漂移。另有 13 条 vnf 的 **evidence** 追加 `evidence_numbers`（Q01-Q08/Q25-Q28/Q30，
  status 仍 pass->pass）；这是诊断字段，不影响 case/gate/decision，但开发报告"check 级变化总数=16"
  只统计了 status，建议在报告中补一句（非阻断）。
- blocks 只少 `exact_below_24_of_24(b0)` 与 `suite_below_threshold(b0)`；negative/boundary/
  update_delete 的缺口块逐条不变。`release_ready=false`、decision=`blocked`、
  hard_gate_status 与 hard_failures（trace_integrity）均不变。
- 独立产物与 `scoring/R1-fixed/` 三文件逐字节相同（见证据 03）。

### 5. T205 冻结控制与 2b 选项 (ii)：PASS

- F01 冻结题实测：correct pass；fabricated_95 仅 `value_no_fabricated` fail；outside_12 仅
  `value_no_fabricated` fail —— 两者 **case 仍 FAIL**，"唯一失败项=vnf ⇒ case FAIL"语义未变。
  F02-F04 诱饵（value_forbidden/value_hit/kind_correct）由新测试与既有冻结测试钉住，均 PASS。
- `test_gate.py::test_value_no_fabricated_failure_is_not_a_hard_gate` 与
  `test_gate_quality.py::test_value_no_fabricated_is_diagnostic_only` 仍绿；新
  `test_value_no_fabricated_alone_does_not_move_hard_gates` 证明 gate_status/hard_failures/
  evaluated_count 不变。
- 选择 (ii)（grounded 自然 pass、不改 case 状态）**合规**：gate.py:50/1455/2320 的 diagnostic-only
  只约束硬门禁/质量指标/退出码；而"极端未 grounded 仍 case fail"更严，满足任务"不得放宽"；
  若改成 case 不因 vnf 单独 fail，需改冻结断言并可能放过极端编造，违反"测试只增"。
  残留：vnf 仍可单独降低 P2 case pass 数/触发 quality block（非硬门禁，pre-existing），
  建议在 R4 口径中明示，本包不动。

### 6. 回归与合规：PASS

- 测试：HEAD 树（HEAD 源码+HEAD 测试+fixtures/docs/corpus/tools）**74 passed**；工作区
  **82 passed**（两次）；`tests/evaluation` 全目录 **797 passed**；三个 P2 集成文件 **21 passed**；
  冻结/diagnostic-only 定点 **9 passed**；0 skipped/xfail。
- 零真实出站：打分路径 socket 守卫实测 **0 连接**；未读 `.env`/H1/H2（证据 07）。账本/预算/GO
  在验收前后 sha256 不变；账本最后一条为 R1 正式运行（03:13:53Z），早于本包工作，测试零写入。
- 并发提示：验收期间 p2_runner/copy 等被并行包写入；本包五文件 sha256 未变，指标为快照。

### 7. 限制与 R2/R3/R4 建议：已给（无 FAIL）

- 开发只重跑 R1；验收方额外用新代码离线重跑 R2/R3：**scorecard 与 p2_decision 逐字节相同**；
  R2 仅 U01/C05 的 vnf evidence 追加；R3 C06 vnf 转 pass 但 case 仍 fail（conflict 语义）。
  故 R2/R3 的分数/门禁结论不受影响；如需产物一致可零真实重算 case_scores。
- R4/后续公开评分会经 `score_public_case` 自动继承 opt-in；H2 现行
  `holdout_case_scores_from_rows` 也调用 `score_public_case`，口径一致（但 H2SCORE 是并行包，
  合并后请再确认最终路径）。
- 建议（R4/H2 前，不要求本包返工）：① 收窄 locator 抽取到内容字段；② 若要"逐条声明"语义，
  按 expected source 匹配引用或做字段级核对；③ 在 H2 报告中说明 vnf 仍可单独影响 case pass 数。

## 复跑证据索引

- `evidence/verify/01-default-diff.txt`：480+55 逐字节差分、Q09-Q24 默认仍 fail、唯一 opt-in。
- `evidence/verify/02-grounding-matrix.txt`：Q09-Q24 矩阵、A-L 反例、F01 唯一失败项、两项边界。
- `evidence/verify/03-r1-rescore.txt`：独立 R1 重跑、tallies、16 条漂移、blocks/decision。
- `evidence/verify/04-r2-r3-impact.txt`：R2/R3 离线重算影响（分数/决策不变）。
- `evidence/verify/05-tests.txt`：74→82、797、21、9 条定点。
- `evidence/verify/06-scope-and-ledger.txt`：范围/并发归属、账本/预算/GO 前后 sha、无 commit。
- `evidence/verify/07-zero-call.txt`：socket/.env/H1-H2 运行时守卫。
- 可复跑脚本：`probe_default_diff.py`、`compare_default_diff.py`、`probe_grounding.py`、
  `probe_zero_call.py`（均在本目录）。

## 限制

- 只对 R1 做了完整独立重跑；R2/R3 只做离线评分核对（未重跑产品），R4 尚未存在。
- 引用证据只认 `citations`（P2 归一化里 `citation.text` 目前恒为空，实际只有 locator 字符串生效）；
  `retrieved`/`facts` 不参与，已用反例验证。
- 工作区是活跃并行现场，测试/产物数字是验收快照；本包五文件哈希在验收前后一致。
- 未审计开发助手此前的 shell 历史；"零真实调用"以打分路径运行时守卫 + 产物计量为证。

## 最终建议

**接收。** 本包正确修复了 Q09-Q24 的 row-echo 误判，默认 P1 口径逐字节不变，R1 38/40、
exact 24/24 可复现，T205 冻结控制与"极端未 grounded 仍 fail"均成立，账本/预算/GO 未受影响。
两项建议（locator 元数据收窄、逐条声明语义）留待 R4/H2 口径讨论，不构成本包返工理由。
