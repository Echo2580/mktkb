# P2-T207-FIX-SCORE 开发报告：value_no_fabricated 按「问题/金标 + 引用证据」判数字（零真实调用）
- 角色/边界：T207-FIX-SCORE 开发助手（全新上下文），分支 `codex/p2-e2e` @ `df661cb`，未 commit/push；真实调用 **0**（只读 R1 产物 + 纯函数评分）；未改 `fixtures/**`/期望/门槛/账本/GO/业务回答/`p2_runner`/`p2_live`，未碰并行包文件；无 skip/xfail。

## 1 结论（R1 用新代码离线重跑，零真实）
| 口径 | 修复前 | 修复后 |
|---|---|---|
| b0 通过/失败 | 22/18 | **38/2** |
| exact（Q01-Q24） | 8/24 | **24/24** |
| OCR（Q33-Q40）/ negative | 7/8、7/8 | 7/8、7/8（不变） |
| blocks / release_ready | b0+negative+boundary 三块 + exact_below_24_of_24，false | negative+boundary 两块，false |

## 2 本因（复核实测）
1. `scorers._value_checks`（修复前 :602）只允许「问题/期望值/参考答/业务日期」的数字：Q09-Q24 回显整行记录时，电话 `010-00000001`→`10/1`、地址 `示例市示例路18号`→`18` 被判"编造"。
2. 这些 extra **100%** 落在本轮 `product.sources[].locator.cells[].display` 里（16/16 行全 grounded，证据 03）。
3. `score_case`（修复前 :1106）把任一 check fail 当 case fail，把**诊断字段**当质量判定；`gate.py:50/1455/2320` 冻结语义写明它只作诊断（T004b MEDIUM-1），不进硬门禁/质量指标/退出码。

## 3 改动（P2-only、opt-in、默认不变；sha16）
- `evaluation/scorers.py`（1350 行，+81/−7，`8c2715661997cecb`）：新增 `citation_number_keys`（citation.text + locator 字符串值/cell display，排除 `document_name` 等容器键，归一与回答侧同口径）与 `_normalized_number_keys`；`_value_checks`/`score_case` 增**默认 None** 的 `allowed_number_keys`（允许集合 = gold ∪ 传入），默认 evidence 键序逐字不变。
- `evaluation/p2_scoring.py`（2215 行，+10/−1，`2d40963176de02f2`）：`score_public_case` 显式传 `allowed_number_keys=citation_number_keys(outcome.citations)` —— 全仓唯一打开该 opt-in 处。
- 测试只增：`test_p2_scoring.py` 5 条、`test_p2_gate.py` 1 条、`test_p2_public_controls.py` 2 条。

## 4 数字判定（不得放宽，证据 03）
- 允许集合 =「问题+期望值+参考答案+业务日期」∪「引用 text / locator 字符串值 / cell display」；文件名编号不算，整数型 locator 键（row/header_row/column_index）不参与。
- Q09-Q24 的 extra 全 grounded（2/2 或 1/1，无部分命中）。反例：同段回答清空 sources → vnf fail（['1','18']）+case fail；多写引用行里没有的 7 → fail（['7']）+case fail。
- T205 冻结诱饵 F01-F04 判别力不变：缺 90%→value_hit、他分档审批人→value_forbidden、PX-0001→value_hit、他实体→kind_correct。

## 5 对 P1 无影响（证据 02）
- 默认参数下 old(HEAD) vs new **逐字节相同**：夹具 240/240、真实行 55/55（含 evidence 键序）；默认口径下 55 条真实行仍 17 条 vnf fail（Q09-Q24 + R3 C06）。
- `runner.py`/`gate.py` 无一处传新参数；`exact_value_contract` 仍只用 `check_value` 重算。

## 6 测试（证据 04）
- 点名四文件 74 passed（改动前）→ **82 passed**（+8，无删改、无 skip/xfail）；`tests/evaluation` 全目录 **797 passed**；`tests/integration` 三个 P2 文件 **21 passed**。
- `test_gate.py`/`test_gate_quality.py` 的 diagnostic-only 冻结断言仍绿。

## 7 2b 的选择与依据：选 (ii)「grounded 后自然 pass」，不改 case 状态判定
1. `test_p2_public_controls.py::test_f01_correct_answer_with_formula_passes`（T205 冻结控制）钉死「唯一失败项 = value_no_fabricated ⇒ case FAIL」，该文件只允许**增**用例；`test_scorers.py` 的 check 级断言同理。
2. gate.py 的 diagnostic-only 已在门禁层生效（`gate.py:2320`：status=diagnostic_only、participates_in_gate=false；`exact_value_contract` 只按 check_value 重算）；P2 case 状态只影响 scorecard 与 evaluated_count（pass/fail 都计入），不改变放行。
3. 故对"仍 fail 的极端情形"（数字不在问题/金标/参考答也不在引用证据）保持 case fail（更严不更松），由 §4 两条反例钉住。

## 8 限制 / 回退
1. 只重跑 R1；R2/R3 未重算产物。R3 C06 同类（D02 行回显）只会 vnf 转 pass，仍因 conflict 值语义（expected 全含）fail，属 T207-FIX-A 已记录的 any-of 缺口。OCR/检索/trace_integrity/negative 7/8/boundary 4/6/U 缺题均未触碰；`release_ready=false`、decision=blocked 不变 —— 本报告不是质量达标或放行结论。
2. 引用证据只认 `citations`（不含 `retrieved`/`facts`）：更宽口径会引入新的可伪造面，未采纳。
3. 回退：`git checkout -- backend/src/mktkb/evaluation/{scorers.py,p2_scoring.py} backend/tests/evaluation/{test_p2_scoring.py,test_p2_gate.py} backend/tests/integration/test_p2_public_controls.py`，删本目录与 `scoring/R1-fixed/`。

证据（4）：`evidence/01-r1-rescore-before-after.txt`（命令/前后 tallies/16 条漂移/decision 对账）、`02-p1-default-diff.txt`（默认口径逐字节差分 240+55，0 分歧 + probe 源码）、`03-number-judgment-matrix.txt`（extra↔引用证据↔grounded + 反例）、`04-pytest.txt`（基线/改动后/新用例/相邻影响）。
