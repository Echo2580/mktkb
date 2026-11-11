# P2-T207-FIX-H2SCORE-R1 独立复验（review）

- 角色：P2-T207-FIX-H2SCORE-R1 独立验收助手（全新上下文，未参与开发）。复验时点：2026-11-11 12:30–12:5x +08:00。
- 工作区：`D:/GPT项目/市场部AI知识库`，分支 `codex/p2-e2e`，HEAD `b4b9b72`（本包改动全部未提交）。
- 边界：零真实出站（Mock 产品 + 离线 pytest，`outbound_attempts=0`、`real_calls=0`）；未打开 `.env`、真实 H1/H2 题干/答案/密文/key、`D:/mktkb-p2-holdout`；未改代码/测试/文档/夹具/账本/预算/GO；未 commit。
- 只写：本目录 `review.md` + `evidence/verify/`（01 独立探针输出、02 复核探针输出、03 复跑/范围/账本、两份可复跑探针）。探针临时产物全部在系统 TEMP（仓外）。
- 独立性：**没有复用开发测试的合成封存/夹具**；30 题封存（10-5-5-5-5 / 36 回合，multi_turn 轮数排布 3-2-2-2-2）、题干/答案/金标值、Fernet key、会作答 Mock、对照臂全部自建；单变量在“同一 ProductTurn 只切换 `product.text`”上重做。

## 0 结论

**接收（阻断 0）**。上一轮 B1/B2/B3 三项阻断均已闭环，且我用**自建**封存与产品观测独立复现了开发声称的关键读数：

- B1：单变量 带 text `passed=1` / 去 text `passed=0`；30 题实跑 `passed=23 failed=7 errors=0`，分层 paraphrase 10 / multi_turn 5 / stale_conflict 5 / cross_doc_security 3 / negative 0（与开发逐值相同）；去正文两个对照臂均 `passed=0/30`；另加“30 题全对 + gate approved”臂 `passed=30`、`threshold_met=true`、`release_ready=true`，证明阈值/放行随观测值而非结构恒 false。
- B2：引用 superseded 来源的题 `pass → error`，`hard_failures=0` 且带 `holdout_hard_failure_unclassified`（`codes/counted_as/hard_failures_owner`）；30 题里 1 题 superseded + gate approved → `passed=29 errors=1 threshold_met=true release_ready=false`；引用 `forbidden_sources` 的资料由 `source_forbidden` 判 fail（同样不计 pass）。
- B3：多轮题面（2 字 / 9 字）、参考答案、case_id、明细字段名命中即 `holdout_scorecard_leak`；干净卡不误报；1 字按文档口径不扫。

另有一条**执行期口径风险**（负样本 `expected_kind`，见 §4 第 2 条），不是本包缺陷，但会影响 24/30 的读法。

非阻断 3 条（见 §2）：**N6** `p2-score --holdout-cases` 与 runner 卡的逐题口径并不相同（同一批行 `passed` 0 vs 23，缺 `source_index`），文档“逐题口径相同”需收紧；N7 结构码可达性说明；N8 ASCII 题面与 schema 词重合时的审计边界（fail-closed，不写泄漏卡）。

| # | 任务书条目 | 判定 | 独立依据（摘要） |
|---|---|---|---|
| 1 | 范围 | **PASS** | 只动 `p2_runner.py`(+512/-1)、`p2_score_run.py`(+34/-15)、新测试文件、两份契约文档、runbook §8.3/§8.4、本报告目录；`p2_scoring/scorers/p2_live/product_adapter/cli/fixtures/docs/evidence` 未改；`conversations/*`、`copy.py` 属 FIX-CONFLICT（N08 图片意图，diff 内容已核）；无 skip/xfail；未 commit（03 §3–§5） |
| 2 | B1 独立复现 | **PASS** | 自建 30 题/36 回合：23/7/0 + 分层逐值相同；单变量 1/0 vs 0/1；对照臂 A（不登记内存行）与 B（仅去 text）均 0/30；30 全对 + approved → 30/0/0、threshold_met/release_ready 均为 true（01 §B1） |
| 3 | 不落盘/不漏明文 | **PASS** | run_dir 仅 6 个聚合/门/清单文件；case_id、题干、回合题面、参考答案、金标值、回答前缀命中 **0**；无 `cases.jsonl/requests.jsonl`；`ledger.cases` 的 product 全部无 text；适配器 out_dir 全文也 0 命中；B3 矩阵逐项正确（01 §B1/§B3） |
| 4 | B2 结构问题不计 pass | **PASS** | superseded → error + 未分类 block（evidence 逐字段核对）；四个结构码在 `holdout_case_scores_from_rows` 层逐码验证 `pass→error`；实测 `forbidden_sources` 走打分侧 `source_forbidden` → fail（同样不计 pass，见 N7）；1 题 superseded 的 30 题卡 release_ready=false；`hard_failures` 恒 0 的语义与 §10/runbook 一致（01 §B2） |
| 5 | 语义一致性 | **PASS（附 N6）** | 卡片 20 键与 `P2HoldoutScorecard.to_dict` 完全一致；同一批行（带 `source_index`）聚合逐字段 0 差异；`execution_mode/real_calls` 口径正确；公开 run 不写并清理 stale；N1/N2/N4 如文档；**但 CLI `--holdout-cases` 实测 0 pass（N6，文档表述需修正）**（01 §语义/§N、02） |
| 6 | 回归与合规 | **PASS** | 19 / 35 / 273 passed（仓库根）；零出站；账本/预算/GO 的 bytes+sha256+mtime 与上一轮逐值相同；无 skip/xfail；HEAD 未前进（03） |
| 7 | 限制 | **如实（见 §4）** | 真实 H2 未跑；doc_code 全集与产品 `document_name` 形态仍未验证；`thresholds_approved` 硬编码差异不影响当前读数（gate 仍 unapproved），H2 执行期需按 §4 核验 |

## 1 关键复现（独立探针，非开发夹具）

### 1.1 B1 单变量（评分接缝）

同一条 `ProductTurn`（产品答对、引用 active 单位级来源、金标值命中）：

| 臂 | passed | failed | errors |
|---|---|---|---|
| `as_dict(include_text=True)` | 1 | 0 | 0 |
| `as_dict(include_text=False)` | 0 | 1 | 0 |

同时核对了 `_scoring_case_row` 重建行的 `product` 键集与公开 `cases.jsonl` 行相同（24 键，含 `text/sources/evidence`）——B1 的机制是“正文只在内存里补回、不改落盘口径”。

### 1.2 B1 端到端（自建封存 30 题 / 36 回合）

- 23 对 7 错（5 道负样本照答 + 2 题引错单位）：`total=30 executed=30 passed=23 failed=7 errors=0`；
  `by_stratum(passed)={paraphrase:10, multi_turn:5, stale_conflict:5, cross_doc_security:3, negative:0}`；
  `threshold_met=false`（23<24，是观测值不足，不是结构性 0）。
- 30 全对（负样本 `not_found` 拒答；我的合成 labels 把负样本 `expected_kind` 记为 `not_found`，与产品 kind 一致；真实 H2 labels 的用词见 §4 第 2 条）+ gate approved：`passed=30 failed=0 errors=0`、`threshold_met=true`、`release_ready=true`、`blocks=[]` —— 阈值与放行确实随观测值变化。
- 对照臂 A（同批观测，但 `record_scoring_case` 不登记 → 打分退回落盘口径）：`passed=0 failed=30`。
- 对照臂 B（照常登记，只把 `product.text` 去掉，复现开发说法）：`passed=0 failed=30`。
- 三臂 `execution_mode=local_mock`、`real_calls=0`；`summary.network.available=true / outbound_attempts=0`。

### 1.3 不落盘 / 不漏明文

- 23/7 臂 run_dir 只有 `gate.json / holdout_aggregate.json / holdout_scorecard.json / run_manifest.json / run_result.json / summary.json`；对每个文件全文扫描 case_id、`case.question`、每回合题面、`reference_answer`、金标值、回答前缀，命中 **0**；无 `cases.jsonl/requests.jsonl`。
- 适配器 out_dir 全文（run_dir 之外的适配器目录，另含 3 个文件）也 0 命中。
- `ledger.cases`（落盘口径的 case 行）里 30 题的 `product.text` 全部为 `None`；正文只存在于 `scoring_cases`（进程内）。
- `run_id/config_hash` 与 `run_manifest.json` 逐值一致，`detail_export=false`。

### 1.4 B3 泄漏审计矩阵

| 注入位置 | 命中 |
|---|---|
| 多轮第 1 回合题面（2 字） | ✅ |
| 多轮第 2 回合题面（9 字） | ✅ |
| 参考答案（5 字） | ✅ |
| case_id 子串 | ✅ |
| 明细字段名（`question`） | ✅ |
| 干净卡（只有计数/稳定码） | 不误报 |
| 1 字题面 | 不扫（阈值 2，与文档一致） |

另用“真实卡形态”（多轮题面塞进 `block.detail`）验证：判 `holdout_scorecard_leak`。

### 1.5 语义一致性

- 用 runner 捕获的同一批内存打分行，按 `p2-score` 的口径（`holdout_case_scores_from_rows` + `aggregate_holdout_bundle`，带 `source_index`）重建一张卡：`total/executed/passed/failed/errors/by_stratum/hard_failures/min_pass/threshold_met/hard_failures_max/thresholds_approved/detail_export/release_ready/execution_mode/real_calls/run_id/config_hash` 逐字段 **0 差异**；20 个顶层键与 `P2HoldoutScorecard.to_dict` 完全一致。
- N1：聚合器级注入泄漏时，兜底卡仍写出（`total=30 passed=0 errors=30`、`blocks=[holdout_scorecard_leak]`），卡内无 case_id。
- N2：`_scorecard_real_calls(None)=0`、`(7, outbound=7)=7`；三臂卡片 `real_calls=0`。
- N4：无 ingest plan 时只出 1 条 `holdout_document_code_unmapped`。
- 公开 run：写 `cases.jsonl`，且同一 run 目录里的旧 `holdout_scorecard.json/holdout_aggregate.json` 被清掉。

## 2 非阻断（新发现）

### N6（文档/口径，建议 H2 执行前修正，不阻断本包）`p2-score --holdout-cases` 并非“逐题口径相同”

- `docs/evaluation/p2-dataset-v0_1.md` §10 写“两者逐题口径相同（含 B2）”，runbook §8.4 把 `p2-score --holdout-cases` 列为“可选独立复核”。
- 实测（02）：把**同一批** 30 题逐题行（含 `product.text/sources/evidence`）交给真实 CLI
  `p2-score --visibility holdout --holdout-cases --document-codes --run-dir`，得 `passed=0/30`；
  同一批行经 runner 的 `_holdout_scorecard`（`source_index=source_index_from_rows(rows)`）得 `passed=23/30`。
  两张卡的 20 个字段/类型完全一致，**数值不一致**。
- 根因：`cli.py:856-863` 调用 `holdout_case_scores_from_rows` 时没有像 runner 那样传 `source_index`
  （`_source_identity` 只从 `source_index` 取 `unit_key`，`p2_scoring.py:450-456`），导致单位级引用一律无法命中
  `source_hit` → 答案题全 fail。该缺省可追溯到 FIX-A 提交（`070a832`，`git blame cli.py:856-863`），**不是 R1 引入**，本包也没改 `cli.py`。
- 影响：若经理用 `--holdout-cases` 复核 H2，会看到与 B1 同形的“结构性 0 pass”，可能误判产品。
- 建议：①H2 的独立复核用 `p2-score --verdicts`（封存判定表，不依赖逐题评分）；②后续 CLI 包补 `source_index_from_rows(rows)`；
  ③本包文档把“逐题口径相同”改成“聚合 schema 相同；`--holdout-cases` 当前缺单位级索引，读数为下限”。

### N7（文档精度）四个结构码里 runner 路径实际只能触发 `source_not_active`

- `_holdout_score_marks` 的 `allowed_doc_codes=set(codes.values())`（全部已映射代号）、`forbidden_doc_codes` 从未传入；
  `_source_identity` 要求 `source_id` 非空，所以 `citation_not_unit_level` 也到不了隔离检查。
- 实测：引用被禁资料（`forbidden_sources`）时由打分侧 `source_forbidden` 判 **fail**（不计 pass），不经过结构码；
  未映射文档名会以 `source_document_unmapped` 走 `holdout_case_unscorable`（error，也不计 pass）。
- 结论：B2 的“结构问题不计 pass”成立；文档列出四个码是“若出现则”的防御集合，不是 runner 的可达集合，建议措辞注明。

### N8（边界）ASCII 题面与 schema 固定词重合时：宁可不写卡（fail-closed）

- needle 是 2 字起子串；若某题题干恰好是 `passed/total/errors` 这类 schema 键，干净卡也会命中，
  兜底卡（已去掉说明文本）仍包含这些键 → 二次审计再命中 → `_holdout_scorecard_artifact` 抛
  `holdout_scorecard_leak`，该 run 不写 scorecard（不是泄漏，是保守拒绝）。
- 真实 H2 是中文题面，撞不上英文键；不影响本包结论，但“产物一定写出”的措辞对 ASCII 题面不成立。

### 其他小项

- 开发证据 03 记 ledger/budget/GO 为 1384/38/37 行，本验收按换行计数得 1383/37/36；bytes+sha256+mtime 完全相同，属尾部空行计法差异，不是改动（03 §6）。
- `p2-score` 的 `holdout_hard_failure_unclassified` 块 evidence 只有 `codes`，runner 侧多 `counted_as/hard_failures_owner`；同为 unknown，语义不冲突。

## 3 证据索引（evidence/verify/）

| 文件 | 内容 |
|---|---|
| `01-probe-independent-output.txt` | 自建封存 B1 单变量/三臂、B2、B3、N1/N2/N4、公开 run、语义对照、账本只读；37 项断言全 OK、0 MISMATCH（含负样本 `expected_kind` 的执行期风险读数） |
| `02-p2score-cli-parity.txt` | 同一批行：CLI `p2-score --holdout-cases` = 0 pass vs runner = 23 pass；20 键 schema 相同（N6） |
| `03-tests-scope-ledger.txt` | 19/35/273 passed、单位/归属、skip/xfail、HEAD/未提交、零出站、账本预算 GO hash+mtime |
| `probe_independent.py` | 可复跑：自建 30 题/36 回合封存 + 会作答 Mock + 三臂 + B2/B3/N/parity（系统 TEMP，零出站） |
| `probe_p2score_cli.py` | 可复跑：真实 CLI 复核路径与 runner 卡的差值（N6） |

## 4 限制与执行期核验建议

1. **真实 H2 未跑**：`doc_code` 全集、产品 `document_name` 形态仍未在本机验证。执行前建议由保管方只打印
   封存 labels 的 distinct `expected_sources/relevant_units.doc_code` 集合（不含题干/答案），与本包映射可产出的
   `{D01…D06,V01,V07}` 对齐；若出现 `V03/V04/V05/V06` 作为期望代号，本卡会恒带 `holdout_document_code_unmapped`。
2. **负样本 `expected_kind` 必须与产品实际 kind 对齐（会影响 24/30 的读法）**：
   打分侧 `_kind_checks` 对 `expected_kind` 做**严格相等**（`scorers.py:727-733`），而产品回答把
   `no_answer` 归一成 `not_found`（`conversations/service.py:1883`）。实测（01 §执行期风险）：
   `expected_kind="refusal"` 时，产品回 `not_found`/`no_answer` 都判 fail，只有字面 `refusal` 才 pass。
   若封存 H2 的 5 道负样本用 `refusal`（P1 命题协议写法），则负样本结构性 fail、卡上限 25/30，
   `passed>=24` 实际变成"24/25 答案题"——比设计意图严格得多。**执行前必须让保管方确认 labels 里负样本的
   `expected_kind`**（应为 `not_found`/`no_answer`）；若确为 `refusal`，要么改 labels，要么把阈值 24 的解释
   改为"答案题 24/25"，不要把它当产品失败。
3. **单位级证据是否齐全**：runner 卡的 `source_hit` 依赖 `product.evidence` 里的 `unit_id/unit_key`
   （`product_adapter.citation_evidence`）。若真实 H2 的引用不带单位身份，答案题会因 `source_hit` 失败而压低
   `passed`（与 B1 同类但方向相反）。建议 H2 首轮后检查：无 `holdout_case_unscorable`、`errors=0`、
   `passed` 与人工抽查一致；必要时先在受限进程做 1 轮 `source_hit` 冒烟（不落逐题）。
4. **`thresholds_approved` 硬编码差异**：`cli.py:890` 恒 `False`，runner 读 gate `status`。当前 gate 仍
   `unapproved`，两张卡都是 false，**不影响本次 T207 读数**；gate 转 approved 后 runner 卡会 true、p2-score 卡仍 false，
   放行取更保守者（§10.9 已写）。比 N3 更需要注意的是 N6：`--holdout-cases` 的 `passed` 不能当复核真值。
5. **`hard_failures` 恒 0 = 未分类**：不能当“无硬失败”；硬失败类别/计数以封存判定表（`p2-score --verdicts`）为准。
6. **N8 边界**：中文 H2 题面不受影响；如后续出现 ASCII 题干，需把审计改成“按 JSON 值而非子串”或对 schema 词做白名单。

## 5 最终建议

**接收（阻断 0）**。B1/B2/B3 已被独立复现：23/7 可复现、正文是唯一变量、结构问题不计 pass、多轮题面纳入审计、run_dir 无明文。
不要求返工；建议在 H2 执行前做两件轻量收尾：
①把 §10/runbook 的“`p2-score` 与 runner 逐题口径相同”改成“聚合 schema 相同；`--holdout-cases` 当前缺 `source_index`，
独立复核请用 `--verdicts`”（N6）；②按 §4 第 1/2/3 条做一次封存 doc_code、单位证据与负样本 `expected_kind` 核对。
