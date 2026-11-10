模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# T110 独立验收（检索金标与检索指标）

验收对象：分支 `p1/fix-retrieval`，交付 `6c82a8f`（父 `3e58d36`）；验收时 HEAD=`6c82a8f`，
初始 `git status --short` 为空。**结论：PASS（技术交付；含非阻断残余 + 一项验收流程
瑕疵待 PM 裁定，见 NOT-RUN）**。未改交付物、未 commit/push/切分支；仅新增本
`review.md` 与 `verify/T110/` 4 份证据。

| # | 项 | 判定 | 依据（命令 / `文件:行`） |
| --- | --- | --- | --- |
| 1 | 同 chunk 同排名、unit 去重、top-10 按 chunk | **PASS** | 独立手算 A–I：A=0.6131471928、C=0.9197207891、D=0.4414924137、F 第 11 chunk 全 0、I=0.4692787260；`02-probe.py` `FAILS=0`；`scorers.py:840-865/897-917` |
| 2 | 金标 override/fallback/空金标/fail closed | **PASS** | 探针 12 项：override、fallback、两空、`unit_key_not_found`、`duplicate_unit_key`、`ambiguous_units`、`locator_not_found`、`record_code_not_a_lookup_key`×2、范围集合；`gold.py:168-176/181-215/251-266` |
| 3 | hard/empty 量化、无 gold 分母、summary/gate | **PASS** | hard=2/3、empty=1/7、无 gold 剔除；summary 五字段与 P0 同名；gate 复跑 hard `[]`、五指标可读；`docs/evaluation` 无 diff；`scorers.py:1122-1145`、`gate.py:1957/2047-2065` |
| 4 | b0/badcase/regression 数值变化合理性 | **PASS** | 用原始 `cases.jsonl` 独立复算旧口径，逐位等于 P0（b0 MRR .8697916667/nDCG .8954577740；badcase .7679144385/.7166666667/.6851021520）；新口径等于交付；retrieved diffs=0 |
| 5 | 回归/预算 | **PASS** | 本包 **17 passed**；evaluation **409 passed**；全量 **1812 passed / 0 failed / 0 error**（473.63s，峰值 413.4 MB＜2GB）；b0 0/40、badcase 0/13、regression 0/7 signature；RG006 pass/answer、RG005/7 不变 |
| 6 | 合规/形式 | **PASS（技术/交付）** | 9 文件全允许路径；无 fixtures/b0/badcase/gate_v0/业务/账本；无 skip/xfail/删断言/新依赖；report 71 行五段；证据 4；单 dev commit；零真实调用。验收流程瑕疵见 NOT-RUN |

## 定向核验要点

- **排名单位**：`EvalRetrieved` 条目是 chunk；runner 按 unit 展开时保留 `chunk_id`
  （`runner.py:1457-1474`），`scorers.py:840-865` 用 `doc_code+chunk_id` 归并；同 chunk
  多 unit 共享排名。1 chunk 3 unit 中 2 相关 → nDCG 只计一次 gain（0.613147），未按
  unit 顺序编造名次。相关 unit 在 chunk 第 3 条仍 MRR=1。
- **去重/top-10**：c1 u1、c2 u1、c3 u2 → `retrieved_units=2`、Recall 2/2、nDCG
  0.919721；10 个噪声 chunk 后的第 11 个命中 → Recall/MRR/nDCG=0、`retrieved_units=21`。
- **金标**：`relevant_units` 非空只用它；空回退 `expected_sources`；两空返回 `()` 且
  scorer 为 None/不进分母；0 命中/重复 key/locator identity 冲突/record_code-only 均
  `GoldUnresolved`，不静默挑选。
- **数值来源**：T110 与 P0/T109 的 `outcome.retrieved` 逐 case 0 diff；旧公式复算值
  逐位等于 P0 summary，新公式复算值逐位等于交付 summary（`stored_metrics_mismatch=[]`）。
  N09 旧 10/17、nDCG 1.0 → 新 13/17、0.6489315753；Q25/Q26/Q27/Q29/Q30/Q32、N03/N07、
  RG001/RG003 的 MRR/nDCG 上升均由旧“unit 名次展开”修正而来。
- **门禁**：在 T110 run 副本上 `gate --config docs/evaluation/gate_v0_1.json`：b0/badcase/
  regression 均 exit 3、hard `[]`、unknown 42/94/80；五指标读取并展示，阈值/审批未动。

## 残余 / 观察（不阻断）

1. **nDCG 是保守下界**：每 chunk 位置一次 gain 与 LOW-4“同 chunk 同排名”一致，也避免旧
   口径的相邻名次高估；但 ideal 仍按 `min(|relevant|,10)` 个 unit 位置，单 chunk 多相关
   unit 会显著低于 1（1 chunk 3 unit 全相关=0.469279；N09 13/17=0.649）。这是“每 chunk
   一次 gain、nDCG≤1”的代价，属低估计而非高估；T112 若要 unit 级可比 nDCG，需显式改
   chunk-level ideal，不能在本包静默改口径。
2. **`empty_recall_rate` 语义**：P0“没有任何 retrieved unit”的比例，不是“零相关命中”；
   report §5 已披露，解读时不得混同。
3. **`record_code` + `locator: {}`** 仍按范围型 locator 匹配整篇（`gold.py:198-215`；
   合成探针返回全部 3 unit）；`gold.py:168-176` 只拦截无 locator 键的 record_code-only。
   属 T004a/T005 遗留 fail-open，gate 记 `record_code_empty_locator` unknown；若 PM 认为
   “record_code-only”包含空 locator，需另开小包。
4. **真实 `relevant_units` 缺失**：b0/badcase/regression 三套 fixture 非空计数均为 0；
   override/fail-closed 仅合成索引覆盖，T111/live 才走真实路径。
5. **证据 02 行 37 文字笔误**：C 案 `c2` 是第 2 个 chunk（不是“第 3 位”），u2 才是第 3
   位；表格/测试数值正确。
6. **hard_filter 分母**沿用 P0“有 gold 且未跳过 case 内全部 retrieved unit”；负样本泄漏
   由 gate `security_leak` 管，不混入质量指标。

## NOT-RUN / 红线

- **验收流程瑕疵（如实披露，待 PM 裁定）**：验收方执行过
  `rg -n "record_code" fixtures/evaluation -g "*.jsonl"`（以及一次同目录
  `relevant_units` 搜索），该范围包含 `fixtures/evaluation/holdout-questions.jsonl`，
  因此该文件被 ripgrep 扫描。命令输出未显示、后续也未使用任何 Holdout 内容；b0/
  badcase/regression 的复算与结论均未依赖 Holdout。但严格按“不读 Holdout”边界，这是
  一次流程越界；若 PM 要求零扫描，应由全新上下文重跑本验收。
- 未读 `.env`；未做真实模型/embedding/rerank/OCR 调用。
- 全量测试无失败，未触发既有 flake 隔离复跑（无 flake 可隔离）。
- 未做 gate 阈值校准/审批（T112）、未跑 live 端到端。
- 未 push/commit/切分支/stash/reset；未改交付物。

证据：`docs/reports/OBS-EVAL/P1/evidence/verify/T110/{01-verdict,02-probe.py,
03-probe-results,04-test-eval-runs}.md`（02 为脚本）。
