# T004b 独立验收 review（scorer）

> 验收者：全新上下文，无开发会话历史。对象 commit `f126598`（`p0/T004b scorer`）；分支 `p0/obs-eval`，HEAD `9d52b7c`（代码等同 `f126598`，`git diff --stat f126598 9d52b7c -- backend` 为空）。只以自己复跑结果判定；开发 `report.md` 只作定位线索，不作 PASS 证据。

## 总判定

**PASS**（4 MEDIUM / 5 LOW 非阻断；T005/T006a 必须执行 §6 硬要求）。开发报告声称的 70 passed、104 passed、1377 passed、0.25 / 1/3 / 0.5、12 个 check id 均独立复现；提交边界干净。

## §5 逐条判定

| 条款 | 判定 | 独立复跑与证据 | 结论/备注 |
| --- | --- | --- | --- |
| §5.1 值命中 | PASS | `pytest backend/tests/evaluation/test_scorers.py -q` → **70 passed**（`evidence/verify/T004b/01`）；探针 16 组 `check_value` 正反例全过；`scorers.py:247/290/358/520`；测试 `test_scorers.py:162-275` | 全半角/大小写/空白/不可见字符正确；`12` 不命中 `120`/`12.5`；负数不冒充正数；`value_hit` 与 `value_no_fabricated` 分离。`value_no_fabricated` 偏严见 MEDIUM-1。 |
| §5.2 来源命中 | PASS | `scorers.py:393/456/799`；测试 `test_scorers.py:283-408`；探针：无关 unit 不命中、引用精确/召回按 unit 去重、多 unit 引用各计一次 | `doc_code` 必须一致；unit_id → unit_key → locator 依次匹配；无关 unit 不计。LOW-1（record_code 只校验不解析）与 MEDIUM-4（仅 unit_ids 的 forbidden 引用漏报）见问题表。 |
| §5.3 kind 正确 | PASS | `scorers.py:609/614`；测试 `test_scorers.py:416-462`；探针覆盖 answer/clarification/no_answer/conflict/ambiguous/error 等 | 期望/实际 kind 精确比较；拒答样本另按 `should_refuse` 判；`clarification`/`conflict`/`ambiguous` 不算拒答。 |
| §5.4 分页契约 | PASS | `scorers.py:654-783`；测试 `test_scorers.py:526-619`；探针覆盖缺失/类型/契约矛盾/期望不符/`min_total` | 四个字段各自独立 check；契约违规优先于期望值；LOW-3 为“无期望但实际有分页”的宽口径。 |
| §5.5 拒答三指标 | PASS | `scorers.py:1098`；测试 `test_scorers.py:470-518`；探针手算 2×2 与独立性 | 0.25 / 1/3 / 0.5 独立复现；改 TN/FN/FP 的联动见下；MEDIUM-2（error 计入 TN）见问题表。 |
| §5.6 检索指标 | PASS | `scorers.py:835/1076`；测试 `test_scorers.py:627-713`；探针手算 Recall/MRR/nDCG、top-10、无 gold、硬过滤、空召回 | unit 去重有效：手算 nDCG=0.693426；去重失效反事实 nDCG=1.306574（>1，说明去重不可少）；无 gold 不进分母；缺失 unit_ids 时退化为 0 而非崩溃/误命中。 |
| §5.7 确定性 | PASS | `scorers.py:937`；测试 `test_scorers.py:787-824`；探针同一输入两次 `CaseResult` 相等且 JSON 逐字节一致；探针脚本两次输出 SHA-256 相同 | 12 个 check id 固定且唯一；每个 check 有 status + evidence；OCR 显式 `skipped_requires_ocr`，仅 1 个 `scored` check，不入分母。 |
| §5.8 测试与回归 | PASS | `pytest backend/tests/evaluation` → **104 passed**（`02`）；`pytest backend/tests`（最终代码一次）→ **1377 passed, 0 failed/0 error, 655.26s**（`03`） | 按提速策略 A 未重跑旧基线；`104-70=34`（T004a 基线）、`1377-70=1307`（T003d 基线）；`git diff 71756f5 f126598` 无既有测试/业务代码改动。时长 655.26s 高于开发报告 386.82s，仅环境/负载差异，非判定依据。 |

## 12 个 check 的真实性（非空转）

- `CHECK_IDS` 恰为 12 个且顺序固定（`scorers.py:98`）；普通、拒答、无 gold 样本均输出 12 个；OCR 例外仅 `scored`。
- 逐个构造失败输入：12 个 id 全部能翻成 `fail`，无“永远 PASS”的空转 check；其中 `refusal_expected` 的 fail 路径包内测试未直接断言，探针实测也可失败。
- 变异探针（仓库外，`probe_t004b.py`）：把 `normalize_text` 换成恒等函数 → `value_hit` 由 pass 翻 fail；把 `_pagination_has_more` 强制 pass → 分页矛盾由 fail 翻 pass（证明该 check 真的依赖契约判断）；把 `_citation_case_metrics` 换成无去重实现 → 引用精确率 0.5→2/3；把 `_retrieval_case_metrics` 换成无去重实现 → nDCG 0.6934→1.3066（>1，说明去重不可少）。
- unit 去重没有独立 check（它影响 `citation_precision/recall` 与 Recall/MRR/nDCG 指标）；包内测试 `test_scorers.py:359` 断言 0.5，反事实/无去重实现的 2/3 与 nDCG 1.3066 证明去重失效会被指标/测试捕获，不能按“某个 check 翻 fail”衡量。
- 每个非 skipped check 都有 evidence；skipped check 有 `reason`。`status` 仅使用 `pass/fail/skipped/skipped_requires_ocr`；同一输入两次输出字节一致（探针两次输出 SHA-256 相同）。

## 拒答三指标手算与独立性

| 样本 | TP | FN | FP | TN | refusal_recall | false_refusal_rate | refusal_precision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 基线 | 1 | 3 | 1 | 2 | 0.25 | 1/3 | 0.5 |
| 加 1 个 TN | 1 | 3 | 1 | 3 | 0.25 | 0.25 | 0.5 |
| 加 1 个 FN | 1 | 4 | 1 | 2 | 0.2 | 1/3 | 0.5 |
| 加 1 个 FP | 1 | 3 | 2 | 2 | 0.25 | 0.5 | 1/3 |

三个字段由同一 2×2 矩阵独立派生；加 TN 只动 false-refusal 分母，加 FN 只动 recall 分母，加 FP 同时动 false-refusal 与 precision（数学上共享 FP，不是互相替代）。分母为空时返回 `None`（`scorers.py:1118-1127`），测试 `test_scorers.py:511-518`。

## PM 指定四处判断

1. **`EvalOutcome.retrieved` 是否越界：可接受偏离，不 FAIL。** 只给本地归一化 dataclass 增加带默认值的有序字段（`scorers.py:171-182`），未修改 `RagAnswer`/`Citation` 或任何业务返回类型；计划字段全部保留且可独立构造。检索指标必须有排名，`citations/facts` 无法提供。条件：T005 必须按真实排名填充，并在 replay 产物中持久化；不能由 scorer 猜。
2. **`unit_ids` 缺失是否真 fail closed：是，不静默算命中，也不崩溃；但“0”不是“unknown”。** 缺失 citation unit_ids 时，引用精确率分母仍计入该项、命中为 0（探针：`citation_precision=0.0`、`citation_recall=0.0`），而 `source_hit` 仍可经 unit_key 通过；缺失 retrieved unit_ids 时 Recall/MRR/nDCG=0、`retrieved_units=1`、`empty_recall=0`（探针）。这不是崩溃或误命中，但会把 runner 漏填伪装成“检索质量极差”。**T005 硬要求：** `EvalCitation.unit_ids`/`EvalRetrieved.unit_ids` 必须由 chunk 真实归属填充；`cases.jsonl` 必须持久化有序 retrieved 与 citation unit_ids；local/replay 指标必须逐 case 相等；gold case 有 citation/retrieval 却无 unit_ids 时 runner 应显式 `unknown/error`（退出码 3），不得静默 0。T005 handoff:43/65/69 已写入（unit_ids、record_code fail closed、unit_key 保留）。
3. **`value_no_fabricated` 偏严的实际误判面：足以让硬门禁误杀，应作软指标。** 允许数字集合仅为 business_date/question/reference_answer/expected_values（`scorers.py:358`）；实测合法答案中的“第 2 层、共 3 张” → extra `["2","3"]`；“见 D09” → extra `["9"]`；“v2.1” → extra `["2.1"]`；“第 8 页” → extra `["8"]`；`1,000` 同时导致 `value_hit` 与 no_fabricated 失败。另有反向漏洞：`-12` 在允许 `12` 时通过 no_fabricated（符号盲）；仅有 expected_values 且非拒答时才运行，text/拒答复核不覆盖。设计 §8.1 没有该硬门禁（`exact_value_contract` 只管期望值命中，`security_leak` 只管 forbidden）；**建议 T006a 只作软指标/诊断，不得映射为 `exact_value_contract` 或 `security_leak`**；若要收紧，应从被引来源文本/证据派生允许数字，并排除文档编码、版本号、页码。
4. **拒答口径与 gate 文档一致性：设计/契约侧为准，当前无 gate_v0_1 草案可冲突。** `docs/evaluation/` 只有 `eval_data_v0_1.md` 与 `trace_schema_v0_1.md`，没有 `gate_v0_1.json`；设计 §8.2 只列三指标名，未定义拒答集合；§8.1 `conflict_not_rejected` 接受 `conflict`/`clarification`，与 scorer 不把二者算拒答一致；`not_found` 是 legacy 非答案、`no_answer` 是 RAG 非答案，纳入拒答合理；`refusal` 不是 `OutcomeKind` 成员（`trace_schema_v0_1.md:46-47`），只是兼容别名，`eval_data_v0_1.md:55` 的 prose 写成期望 kind 会与 dataset `ALLOWED_KINDS` 冲突，T006a 应以 `OutcomeKind` + `should_refuse` 为 canonical。**T006a 必须排除 `error`/`service_error` 出 2×2**：scorer 目前把它们当 TN（探针：加入 1 个 error 使 false_refusal_rate 0.5→1/3），会稀释误拒率；`knowledge_changed` 也需明确归属。若 T006a 定义不同，必须改 gate 文档并同步测试，不能只改一侧。

## 问题分级（非阻断）

| 级别 | 问题 | 位置/影响 |
| --- | --- | --- |
| MEDIUM-1 | `value_no_fabricated` 过严且覆盖不全（详见判断 3） | `scorers.py:358/520-558`；硬门禁误杀风险 |
| MEDIUM-2 | `refusal_metrics` 把 `error`/`service_error` 计为 TN，稀释 false_refusal_rate；`knowledge_changed` 未定义 | `scorers.py:1098-1127`；T006a 必须排除/标 unknown |
| MEDIUM-3 | 缺失 unit_ids 时 fail closed 为 0 而非 unknown；`source_hit` 可经 unit_key 通过而 citation 指标为 0 | `scorers.py:473-481/799-817`；T005 必须填充并持久化，并加显式 fail closed |
| MEDIUM-4 | `source_forbidden` 在引用只有 `unit_ids`、forbidden ref 用 `unit_key` 时漏报：unit_ids-only 为 pass，带 unit_key 才 fail | `scorers.py:588-600/393-428`；T005 需为 citation 同时填 unit_key/locator；T006a 的 security_leak 需 resolved forbidden 映射或 fail closed |
| LOW-1 | 仅 `doc_code` + `record_code` 的期望来源被当整篇级命中（任意 unit 都算）；当前 fixtures 均另带 unit_key | `scorers.py:407-428`；T005 handoff:65 的 runner 防御式 fail closed 必须落实；T006a 不得接受 record_code-only |
| LOW-2 | `CaseResult` 未带设计 §7.3 的 dataset/corpus/index/pipeline/gate 版本字段 | `scorers.py:201-239`；T005 的 `cases.jsonl`/manifest 必须补齐，或明确 runner 包装 |
| LOW-3 | `expected_pagination=null` 但实际有分页时只校验契约、不要求“无分页”；包内测试明确期望 pass | `scorers.py:654-661`；口径需在 T006a 写清 |
| LOW-4 | 单条检索项含多个 unit_ids 时按相邻名次展开，nDCG 可能高估 | `scorers.py:841-848`；设计未定义，建议 T006a 明确“同 chunk 同排名”或按 unit 集合口径 |
| LOW-5 | `value_no_fabricated` 符号盲、千分位不归一 | `scorers.py:341-355`；与 §5.1 归一化边界有关的遗留 |

## 对 T005 / T006a 的硬要求

- **T005**：`unit_ids` 与有序 `retrieved` 必须来自真实 chunk 归属，禁止 scorer 猜；`cases.jsonl` 持久化，replay 重建后 local/replay 的 Recall@10/MRR@10/nDCG@10 逐 case 一致；gold case 缺 unit_ids 时显式 `unknown/error`，不得静默 0；`EvalCitation` 同时保留 `unit_key`/`locator`（至少满足 forbidden source 匹配）；OCR 不入分母；`record_code`-only gold 必须 fail closed；每条 case 带设计 §7.3 版本绑定。
- **T006a**：拒答集合固定为 `no_answer`/`not_found`（兼容 `refusal`），`clarification`/`conflict`/`ambiguous` 不算；`error`/`service_error` 不进入拒答 2×2；`value_no_fabricated` 只作软指标，不得映射为硬门禁；`citation_required`/`security_leak` 不得仅凭 `source_hit`/doc 级 `source_forbidden`（unit 级 forbidden 需 resolved 映射或 fail closed）；若 gate 口径与设计/OutcomeKind 不一致，以设计 §8.1/§8.2 + `OutcomeKind` 为准并先改文档。

## 未覆盖项

- 未做 runner/replay/local/gate/baseline/report（不在本包）；未跑真实 gate，无 `gate_v0_1.json` 可对照。
- 零真实模型/OCR/embedding/rerank 调用；未读 `.env`；未新增依赖（新文件只有 stdlib + contracts/dataset/gold；无 provider/网络代码）。
- 未跑 b0 40 + badcase 13 的真实索引运行；scorer 测试以合成样本 + N12 行 + 探针为主。
- 未验证 live/多轮/holdout、P50/P95 真实 trace、真实成本/Token；未做 gate 阈值校准。
- 未把变异包装成 pytest 插件（在仓库外脚本内 monkeypatch/手算验证）；已做 4 类仓库外变异探针。

## 证据与工作树

- 复跑证据：`docs/reports/OBS-EVAL/P0/evidence/verify/T004b/{01-pytest-scorers,02-pytest-evaluation-dir,03-full-suite}.txt` + `probe_t004b.py`（UTF-8 无 BOM，ASCII 文件名）。
- 提交边界：`git show --name-status f126598` 仅 7 个 §2 允许文件（2 源码/测试 + report + T004b 证据 00–03）；`git diff --stat 71756f5 f126598` 同 7 文件；无 dataset/gold/runner/gate/baseline/report 模块（`report.md` 是 §2 明列的开发报告，不是 `evaluation/report.py`）、业务代码、观测内核、既有测试、依赖、docs/evidence、var、fixtures 改动。
- 工作树：本验收产物为 review + `verify/T004b/`（相对并行簿记 commit `72f4695` 有未提交更新）；`T005-runner/handoff.md` 的 M 与 `T006a-gate-hard/` 未跟踪目录是验收期间并行 PM 产物，未触碰。
