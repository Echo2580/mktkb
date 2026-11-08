# T110 独立验收：结论与逐条判定

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（验收方证据，非交付物）

验收对象：分支 `p1/fix-retrieval`，交付 commit `6c82a8f`（父 `3e58d36`）；验收时
HEAD=`6c82a8f`，工作树初始 `git status --short` 为空。结论：**PASS（含非阻断残余）**。

| # | 项 | 判定 | 关键证据 |
| --- | --- | --- | --- |
| 1 | 指标口径：同 chunk 同排名、去重、top-10 按 chunk | **PASS** | 独立手算 A–I 全一致；A=0.613147、C=0.919721、D=0.441492、F 第 11 chunk=0、I=0.469279；`FAILS=0`（02/03-A） |
| 2 | 金标口径：override/fallback/空金标/fail closed | **PASS（含残余 3）** | `gold.py:251-266`；探针 12 项 PASS：override/derive/empty/`unit_key_not_found`/`duplicate_unit_key`/`ambiguous_units`/`locator_not_found`/`record_code_not_a_lookup_key`×2/范围集合（02/03-B） |
| 3 | 量化指标：hard/empty、无 gold 分母、summary/gate | **PASS** | hard=2/3、无 gold 剔除、empty=1/7；summary 五字段与 P0 同名；gate 读取/展示、hard `[]`、`docs/evaluation` 无 diff（03-D/04-C） |
| 4 | 数值变化合理性（b0/badcase/regression） | **PASS** | 独立复算旧口径逐位等于 P0：b0 MRR .8697916667/nDCG .8954577740；badcase .7679144385/.7166666667/.6851021520；新口径等于交付值；retrieved diffs=0（03-C） |
| 5 | 回归/预算 | **PASS** | 本包 17 passed；evaluation 409 passed；全量 1812 passed/0 failed/0 error；峰值 413.4 MB；b0 0/40、badcase 0/13、regression 0/7 signature；RG006 pass/answer、RG005/7 不变（04-B/D） |
| 6 | 合规/形式 | **PASS** | 9 文件全允许路径；无 fixtures/b0/badcase/gate_v0/业务/账本；无 skip/xfail/删断言/新依赖；report 71 行五段；证据 4；单 dev commit；零真实调用（04-A/E） |

## 关键复算

- **同 chunk 多 unit**：1 chunk（u1,u2,u9，u1/u2 相关）→ Recall 2/2、MRR 1、nDCG
  `1/(1+1/log2 3)=0.6131471928`；未按 unit 顺序编造 1,2,3。相关 unit 位于 chunk 第 3 条
  仍 MRR=1。
- **去重**：c1 u1、c2 u1、c3 u2 → `retrieved_units=2`、Recall 2/2、nDCG
  `1.5/1.6309297536=0.9197207891`；重复 unit 不重复计 gain。
- **top-10**：10 个噪声 chunk（20 unit）后的第 11 chunk 命中 → Recall/MRR/nDCG 全 0，
  `retrieved_units=21`；证明按 chunk 截断而非按 unit。
- **数值来源**：验收方用 T110 原始 `outcome.retrieved` 同时实现旧/新公式；旧公式复算出
  P0 冻结 summary 的逐位数值，新公式复算出交付 summary；`stored_metrics_mismatch=[]`。
  P0/T109 与 T110 的 `retrieved` 逐 case 完全相同（0 diff），故变化来自口径修正而非数据。
- **N09**：旧 10/17、nDCG 1.0 → 新 13/17、nDCG 0.6489315753；与报告/证据一致。

## 残余 / 观察（均不阻断）

1. **nDCG 是保守下界**：交付口径“每个 chunk 位置只计一次 gain”，与 LOW-4“同 chunk 同
   排名”一致，也避免了旧口径把同 chunk unit 拆成相邻名次的高估；但 ideal 仍按
   `min(|relevant|,10)` 个 unit 位置计，单 chunk 多相关 unit 会显著低于 1（1 chunk 3
   unit 全相关 → 0.469279；N09 13/17 → 0.649）。这是“每 chunk 一次 gain、nDCG≤1”
   要求的直接代价，属**低估计**而非高估；T112 若需要 unit 级可比 nDCG，应显式决定是否
   改为 chunk-level ideal，不能在本包静默改口径。
2. **`empty_recall_rate` 语义**：仍是 P0“没有任何 retrieved unit 的 case 比例”，不是
   “零相关命中”；报告 §5 已披露，评测解读时不得混同。
3. **`record_code` + `locator: {}` 仍 fail-open**：`gold.py:198-215` 将其当范围型 locator
   匹配整篇（合成探针返回 D01 全部 3 unit）；`gold.py:168-176` 只拦截“没有 locator 键”
   的 record_code-only。这是 T004a/T005 遗留形态，gate 会记 `record_code_empty_locator`
   unknown（exit 3），T110 未新增该回归；若 PM 认为“record_code-only”包含空 locator，
   需另开小包，不在本包放行语义内。
4. **真实 `relevant_units` 数据缺失**：b0/badcase/regression 三套 fixture 的
   `relevant_units` 非空计数均为 0；override/fail-closed 仅合成索引覆盖，T111/live 才走
   真实路径。
5. **证据 02 行 37 文字笔误**：C 案 `c2` 是第 2 个 chunk（不是“仍占第 3 位”），u2 才是
   第 3 位；表格与测试数值正确，属文档瑕疵。
6. **hard_filter 分母**：沿用 P0“有 gold 且未跳过的 case 内全部 retrieved unit”；负样本
   泄漏由 gate `security_leak` 管，不混入质量指标（`scorers.py:1122-1145`）。

## NOT-RUN / 红线

- **验收流程瑕疵（如实披露）**：验收方执行过
  `rg -n "record_code" fixtures/evaluation -g "*.jsonl"`（及一次同目录
  `relevant_units` 搜索），范围包含 `fixtures/evaluation/holdout-questions.jsonl`，该文件
  被 ripgrep 扫描；命令输出未显示、后续未使用任何 Holdout 内容。严格按边界属流程越界，
  若 PM 要求零扫描需由全新上下文重跑。
- 未读 `.env`；未做真实模型/embedding/rerank/OCR 调用。
- 全量测试无失败，未触发既有 flake 隔离复跑（NOT-RUN，无 flake 可隔离）。
- 未做 gate 阈值校准/审批（T112）；未跑 live/dry-run 真实链路。
- 未 push/commit/切分支/stash/reset；未改交付物；仅新增本目录 4 份证据与 `review.md`。
