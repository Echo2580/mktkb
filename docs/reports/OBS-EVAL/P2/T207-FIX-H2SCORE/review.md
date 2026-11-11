# P2-T207-FIX-H2SCORE 独立复验（review）

- 角色：T207-FIX-H2SCORE 独立验收助手（全新上下文，未参与开发）。复验时点：2026-11-11 11:55–12:2x +08:00。
- 工作区：`D:/GPT项目/市场部AI知识库`，分支 `codex/p2-e2e`。**HEAD 在复验期间由 edeeefd 前进到 b4b9b72**（并行包 FIX-SCORE 提交）；本包改动仍未提交。
- 边界：零真实出站（Mock 产品 + 离线 pytest，`outbound_attempts=0`）；未读 `.env`/H1/H2 题干/答案/密文/key（合成封存由探针自建、Fernet key 现生成）；未改代码/测试/夹具/文档/账本/预算/GO；未 commit。
- 只写：本目录 `review.md` + `evidence/verify/`（6 份文本 + 5 个可复跑探针）。探针临时产物写在系统 TEMP（仓外）。
- 账本/预算/GO（只读）：`live-ledger.jsonl` 1,354,211 B/1,383 行 sha `05b54d06…`；`budget.json` 1,738 B sha `79b21700…`；`P2-LIVE-GO.json` 1,272 B sha `3ed427f4…`；mtime 均早于本次复验窗口（详见 evidence/verify/06）。

## 0 结论

**返工（阻断 3 项）**。接线、映射、fail-closed、schema 一致性大体成立，复跑 146/45/64/8 passed 全绿；但 **holdout_scorecard 的 `passed` 在答案类题上结构性恒为 0**（runner 写盘行不带 `product.text`，而打分只看行），所以它给出的不是 H2 质量读数；runbook §8.3「run 后直接读 scorecard、不再需要封存输入」据此不能成立。另有“结构类隔离问题不算 fail、`hard_failures` 恒 0”和“多轮题干不在泄漏审计覆盖内”两项。

| # | 任务书条目 | 判定 | 独立依据（摘要） |
|---|---|---|---|
| 1 | 范围 | **PASS** | 本包只动 `p2_runner.py`(+377)、新增 `test_p2_holdout_scorecard.py`、两份文档、本包报告目录；`conversations/*`/`copy.py` 属 FIX-CONFLICT、`_index.md` 属经理；无 skip/xfail；未 commit；p2_scoring/scorers/p2_live/fixtures/账本/预算/GO 未改（evidence/verify/06） |
| 2 | 聚合正确性 | **PASS（数量口径）＋B1 指出输入口径缺陷** | 自写合成封存 30 题/10-5-5-5-5/36 回合真跑：30/30 executed、0 error、0 pass、30 fail，by_stratum 逐层自洽（02）；接缝用**真实打分**（不注入 marks）得 23/1/6，仅去 text 即 0/24/6（01 S3/S4）；缺题/未执行计入 error 且不 pass；缺样本/缺分层出 block |
| 3 | 泄漏审计 | **FAIL（B3）** | 产物全文 0 命中（case_id/题干/答案 token、7 字短题干、3 字短答案；文档名只出现在 run_manifest 的 ingest 回执）；case_id/长题干/参考答案/明细字段/`H2-` 前缀命中即 leak；builder 级注入→全 error+稳定 block 且无明文；**但多轮题干（`case.turns[*].question`）不在扫描范围**；<8 字 needle 按设计不扫；聚合器级注入会抛错而非落 blocked card（N1） |
| 4 | 映射规则 | **PASS** | 真实 H2 计划 12 source→8 代号：V03/V04/V05→D01、V06→D02、V01/V07 独立；冲突/无前缀/无 plan/空 plan→稳定码；gold 期望代号无映射→block（`missing/mapped`），30 题不白送 pass（01 S1/S2、04 末段） |
| 5 | 语义与门禁 | **PASS（附 B2 风险）** | 未批→`holdout_threshold_unapproved`(unknown)、`release_ready=false`，passed/failed/errors/by_stratum 照常可读；`execution_mode` 只由 run 的 execution 决定、mock 下 `real_calls=0`；带真实 gate 配置时 `run_id/config_hash` 与 manifest 逐值相同（03 末段）；与 p2-score 聚合**键集/类型/同批输入下的数值逐字段一致**（01 S8，value_diffs 为空）；语义来源差异见 N2/N3 |
| 6 | 回归与合规 | **PASS** | 146 passed（5 模块）/45 passed（本包 2 模块）/64 passed（dataset）/8 passed（public controls）；公开 run 产物完整且清理 stale `holdout_scorecard.json`+`holdout_aggregate.json`；零出站；账本/预算/GO 未动（05、06） |
| 7 | 限制结论 | **影响 T207 H2 验收口径** | 见 B1/B2：本卡不能替代封存逐题行/判定表；修复前 H2 验收读数必须仍以 `p2-score --visibility holdout` 为准 |

## 1 阻断项

### B1（阻断）H2 打分行不带回答正文 → `passed` 结构性偏低，阈值 24 不可达

- 机制：`p2_runner.py:1178` 令 `include_question=dataset.public_details`（holdout=False），`:1382` 用 `as_dict(include_text=False)` 写逐题行；`product_adapter.py:809-811` 因而**不写 `product.text`**；打分侧 `p2_scoring.py:504/554` 的 `outcome.text` 只取 `product["text"]`；`_holdout_score_marks`（`:1753`，`:1764/1800`）正是从这些行打分。结论：value_hit / value_forbidden / refusal 判断全部看不到回答 → 回答类题不可能 pass。
- 单变量证据（03）：同一条真实产品观测（D01 第 8 行、产品 `kind=answer`、引用 active 版本）——**带 text 时 value_hit=pass、source_hit=pass；把同一行的 text 去掉后 value_hit=fail**；同一用例的 holdout run 记为 `passed=1/2`（只有负样本过）。
- 规模证据（01 S3/S4）：30 题同一批 23 条正确回答，带 text → 23 pass/1 fail/6 error；仅去 text → **0 pass/24 fail/6 error**。真跑（02 E1）30 题全 fail，与 dev 证据 02 现象一致，但原因是“行里没有回答”而不只是 Mock 不会答。
- 覆盖缺口：本包新增测试里的真实打分只跑“合成题 + Mock 一律 not_found”的全 fail 场景，23 pass 那条用例是 monkeypatch marks，因此从未有“产品答对”的路径覆盖到这条缺陷。
- 影响：只要题面要求值命中（H2 的 answer / paraphrase / stale_conflict / multi_turn 语义如此），该题就不可能 pass；若 25 道非负样例题都带金标值，理论上限只有 `passed ≤ 5`（仅负样本可能过）。`threshold_met` 因此永远 false、`holdout_below_threshold` 恒在——经理读到的是“H2 质量=0/30”，会把一次正常/优秀的 H2 误判为失败；方向是虚假失败，不是虚假通过。
- 修复方向（建议）：在 `_execute` 内存里保留 `ProductTurn`（含 text，不落盘）作为 H2 打分输入，或为 holdout 另建一条“内存行”（仅打分、绝不序列化）；若坚持不保留回答文本，则**必须撤回**“scorecard 即 H2 质量读数”的表述，runbook §8.3 恢复“封存逐题行/判定表为权威”，并把本 card 标注成 unknown/部分观测。
- 复验点：一条“产品答对 → card.passed 增加”的真跑（合成封存 + 能答的 Mock 题即可），并加回归测试防止再次只测“全 fail”场景。

### B2（阻断，轻）来源结构问题不影响单题状态，`hard_failures` 恒 0

- 证据（01 S5）：把一题的来源 `status` 设为 `superseded`（stale 来源）→ 该题仍 `passed`（`passed=23`），`hard_failures=0`，只多一条 `holdout_hard_failure_unclassified`(unknown) block。
- 后果：`hard_failures` 在 runner 路径永远是 0（`holdout_case_scores_from_rows` 固定 `hard_failure=None`），而 schema 的 4 类硬失败里就有 `stale_source`。`release_ready` 仍被这条 unknown block 拦住（01 S9 实测：approved gate + 30 题全 pass、其中 1 题引用 superseded → `threshold_met=true`、`release_ready=false`），但**读数**不对：该题被计入 `passed`、`hard_failures` 报 0。`passed` 与 `hard_failures` 两个字段因此不能用来判断“质量/硬失败”。
- 修复方向：至少让这些结构问题**不计 pass**（记 fail 或 error），并让“未分类硬失败”成为恒在的 unknown block（或在卡里显式 `hard_failures: unknown`），直到有分类来源；补测试。

### B3（阻断，轻）泄漏审计漏掉多轮题干

- 证据（04）：构造 `question=""`、题干在 `turns` 里的 multi_turn case，把第一/第二轮题干放进 block evidence → 审计**不报**（`NOT_CAUGHT`）；`case_id` 仍会报。代码 `:1928` 只扫 `(case.question, case.reference_answer)`。
- 影响：真实 H2 的 5 道 multi_turn（11/36 回合）题面完全不在审计覆盖内；文档 §10 与报告 §4 的“用内存题面逐题扫”对该分层不成立。另：<8 字 needle 按设计不扫（本复验用 7 字题干验证为不报），文档已写“长度≥8”，但应在测试里显式钉住这条边界。
- 修复方向：用 `case_questions(case)`（question + turns 全部文本）参与扫描；补多轮与 <8 字两类边界测试。

## 2 非阻断

- **N1**：`_holdout_scorecard_artifact` 的兜底在“泄漏来自聚合器自身（`_aggregate_marks`）”时会再次调用同一聚合器 → 审计第二次抛错、**未写出 blocked card**（实测 `escaped=true, holdout_scorecard_leak`）；泄漏来自 builder 时正常降级（30 error + 稳定 block、无明文）。与报告「产物一定写出」不符，建议兜底路径不再经过被污染的聚合器。
- **N2**：`real_calls` 口径与 p2-score 不同：runner = `provider_calls.outbound>0` 的**请求行数**（`p2_runner.py:2030-2031`），p2-score = `summary.network.outbound_attempts`（`p2_score_run._execution_context`）。mock 下都为 0；live 下行数 ≠ 出站次数（embedding/rerank 也在同一行内计数），文档应写清“不是出站总次数”。
- **N3**：`thresholds_approved` 来源不同：runner 读 gate config `status`；`p2-score --visibility holdout`（`cli.py:887-896`）硬编码 `False`。gate 转 approved 后两张卡会不一致，需在文档/门禁里明确“哪张为准”。
- **N4**：无 ingest plan 时同时出现两条同名 `holdout_document_code_unmapped` block（映射失败一条 + gold 覆盖一条），只是观感（04 末段）。
- **N5**：文档 §10「规范名/去扩展名、文件名/去扩展名四种形态都登记」——实现是 set 去重，canonical 与 path 同名时只有 2 种形态；语义不错，措辞可收紧。

## 3 复跑与证据索引（evidence/verify/）

| 文件 | 内容 |
|---|---|
| `01-mapping-and-seam.txt` | 真实 H2 计划→代号映射 12 行；映射 fail-closed（冲突/无前缀/无 plan/空 plan）；gold 缺映射 block；接缝 23/1/6 与 0/24/6；结构问题仍 pass；阈值三态；泄漏审计矩阵；与 p2-score 键集/类型一致 |
| `02-e2e-holdout.txt` | 自建合成封存 30 题真跑（计数/分层/blocks/run_id/config_hash/网络计数）；run 目录逐文件受限内容命中；503 中停（errors=30、executed=0）；公开 run 清理 stale scorecard |
| `03-text-omission.txt` | 单变量 A/B：同一观测 text 有/无 → value_hit pass/fail；holdout card passed=1/2；带 gate 配置的 run_id/config_hash 逐值一致 |
| `04-audit-boundaries.txt` | 审计矩阵（含 <8 字边界）+ 多轮题干未覆盖 + 无 plan fail-closed |
| `05-tests.txt` | 146 / 45 / 64 / 8 passed 的命令与输出 |
| `06-scope-and-ledger.txt` | HEAD、本包/并行包归属、skip 扫描、账本/预算/GO hash 与 mtime、零出站 |
| `probe*.py` | 5 个可复跑探针（零出站；`H2V_WORK` 必须指向仓外临时目录） |

## 4 限制与执行期建议

1. **真实 H2 未跑**：doc_code 全集、产品 `document_name` 形态仍未在本机验证。执行前建议让保管方跑一个 repo-safe 检查：只打印封存 labels 里 `expected_sources/relevant_units` 的 **distinct doc_code 集合**（不含题干/答案），与本包映射可产出的 `{D01…D06,V01,V07}` 对齐；若保管方用 `V03/V04/V05/V06` 作为 expected doc_code，则本卡会恒带 `holdout_document_code_unmapped`，需在映射规则里显式支持“槽别名”。
2. **逐题硬失败分类仍由封存方判定**：在 B2 修复前，`hard_failures=0` 不能作为“无硬失败”的证据；H2 验收须继续以 `p2-score --visibility holdout` 的封存判定为准。
3. 本包报告 §2/§5 与 runbook §8.3 的“H2 质量读数”表述建议在 B1 修复后重写，并补一条“产品答对→pass 增加”的验收断言，避免同类结构性零分再次被全 fail 场景掩盖。

## 5 最终建议

**返工**（B1 必改；B2/B3 建议同批修；N1–N3 顺手改）。修复后复验只需三件事：①能答的合成题在 holdout run 里 `passed` 增加且 `threshold_met` 可达；②多轮题干审计命中 + <8 字边界有测试；③结构类来源问题不再计 pass（或 `hard_failures` 显式 unknown）。其余（映射、schema、fail-closed、范围、回归）本复验已通过，无需重做。
