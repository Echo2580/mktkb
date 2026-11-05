# T006b · 门禁质量层 + 校准 + 豁免 — report.md

## 1. 完成内容

- `backend/src/mktkb/evaluation/gate.py`：追加质量层（`QualityResult`/`QualityMetricResult`/`QualityPolicy`）、`QualityWaiver`、`GateProposal`/`calibrate_gate`/`write_gate_proposal`，并把质量失败接入 `exit 2`；硬门禁 8 项判定与 0/1/3/4 语义未改（diff 的删除行只有旧 docstring/import/`baseline` 警告）。
- `docs/evaluation/gate_v0_1.json`：追加 `quality_layer` 元数据（分母口径、审批人、提案路径），`status=unapproved`，15 个指标的 `absolute_min/absolute_max/max_regression_pp/min_sample` 全为 null。
- 新增 `backend/tests/evaluation/test_gate_quality.py`（29 tests；合成 `RunResult` + 真实 `TraceRepository`，零真实模型/OCR/embedding/rerank，不读 `.env`、不写 `var/`）。
- 证据 4 份：`gate-proposal.json`、`badcase-proposal.json`、`quality-chain.txt`、`04-exit-matrix.txt`（退出码矩阵 + 三次测试结果 + 配置 hash）。
- 边界：只改上述 2 文件 + 新增测试/报告/证据；未改 `dataset/gold/scorers/runner/corpus.py`、`observability/**`、业务代码、既有测试断言、`conftest.py`。

## 2. §5 逐条自证

1. **stratum + all、无综合分**：`gate.py:2711-2722` 对 `_quality_strata(cases)` × 配置指标逐个评估；`QualityResult`（`gate.py:736-752`）无综合分字段。`test_gate_quality.py:453` 断言 3 个 stratum + all，`:498` 断言 summary 缺指标 → `unknown` 而非 0。
2. **阈值语义与分母**：`gate.py:2567-2594` 判 `absolute_min`/`absolute_max`；`:2304-2395` 的 `max_regression_pp` 仅在 `pipeline_version`（且 suite/dataset）一致时判定，跨版本 → `unknown`（`:2330-2343`）。分母按指标：检索 `gold_cases_non_ocr`（`:2044-2062`）、答案 `scored_cases_non_ocr`（`:2064-2072`）、拒答排除 error/service_error/knowledge_changed（`:2009-2011`、`:2074-2105`）；测试 `:531/:579/:636/:660`，明确不复用 `hard_gate_min_sample`（`:2496-2531`）。
3. **校准只出提案**：`calibrate_gate`（`gate.py:2954-3053`）输出观测值/建议阈值/`run_id`/`gate_config_hash`，建议规则见 `:2911-2951`（0–1 比率留 2pp、回退 2pp、`min_sample=分母`；运行类不自动建议）；`write_gate_proposal` 拒绝写回 `gate_v0_1.json`（`:3064-3069`）。未审批 → 所有适用指标 `thresholds_unapproved` → `unknown` → exit 3（`:2457-2469`；测试 `:694/:770/:782/:836`）。
4. **退出码**：`gate.py:3396-3405` 优先级 = live 4（`:3125`）→ 硬失败 1 → 任何 unknown 3 → 质量失败 2 → 0；`test_gate_quality.py:944` 证明硬失败 + 质量失败仍是 1，`:817` 证明质量未达绝对阈值为 2，`:858` 同版本回退为 2，`:890` 跨版本为 3；T006a `test_gate.py:1478` 保住 exit 4、`:574` 断言硬失败永不返回 2。
5. **waiver**：`QualityWaiver.__post_init__`（`gate.py:693-705`）强制 `reason`+`approver`，硬门禁 ID 构造即 `ValueError`；豁免只匹配已发生的质量失败并写入 `GateResult.warnings` + `quality.waived`（`:2724-2769`），不改硬失败、不把 unknown 变通过。测试 `:982/:991/:997/:1039/:1121`；证据矩阵含三条拒绝输出。
6. **测试与配置**：包 29 passed、目录 233 passed、全量 1506 passed（0 failed/0 error）；`gate_v0_1.json` 可被 `load_gate_config` 解析、`status=unapproved`、无任何非空阈值（`04-exit-matrix.txt` 末尾命令输出）。

## 3. 实际运行结果

- 包：`pytest backend/tests/evaluation/test_gate_quality.py -q` → **29 passed**（0.66s）。
- 目录：`pytest backend/tests/evaluation -q` → **233 passed**（9.12s；T006a 基线 204 + 29）。
- 全量：`pytest backend/tests -q` → **1506 passed, 0 failed/0 error**（373.49s = 6:13；基线 1477 + 29）。
- commit：`p0/T006b gate quality layer`（单 commit；代码基线 T006a R1 `439fc1b`，父提交 `1ea649f` 为纯簿记；最终 sha 见 `git log -1 --format=%h`；未 push）。`git show --numstat`：`gate.py +1489/-25`、`gate_v0_1.json +18/-1`；新增测试 1138 行、报告 63 行与 4 份证据。
- 真实 run 校准（T005 local，b0 与 badcase）：proposal `status=unapproved`、`gate_config_hash=eeb70a6c2d3b...`、b0 run `b0-local-20261105T035721820024Z-9462c0d1`、badcase run `badcase-local-20261105T035723357224Z-b712d96d`；每个 stratum + all 输出 15 指标（b0 45 行 / badcase 105 行）。
- 关键观测与建议（all）：b0 `Recall@10=0.96875/32 → min 0.9487`、`MRR@10=0.869792/32 → 0.8498`、`nDCG@10=0.895458/32 → 0.8755`；badcase `0.767914/10 → 0.7479`、`0.716667/10 → 0.6967`、`0.685102/10 → 0.6651`；两者均建议 `max_regression_pp=2.0`、`min_sample=分母`。
- 分母实测：b0 检索 32 / 答案 32 / 拒答适用 0、可答 32、实际拒答 1 / 延迟 32 / 成本 0；badcase 检索 **10** / 答案 **13** / 拒答适用 2、可答 11、实际拒答 2 / 延迟 13 / 成本 0；OCR 8 题与 error 行均被排除。
- 诊断：`value_no_fabricated` 仅出现在 proposal/diagnostics（b0 检查 32 题，Q26 fail，`participates_in_gate=false`），不进质量判定/退出码。
- 退出码矩阵（`04-exit-matrix.txt`，每条含实际 `exit=` 输出）：

| exit | 证据 | 结果 |
| --- | --- | --- |
| 0 | `[exit 0]`：approved + 绝对阈值达标 + trace 门禁开 | `exit=0 quality=pass unknowns=0` |
| 1 | `[exit 1]`：`citations=[]` 硬失败 + Recall 0.1 质量失败 | `exit=1 hard=['citation_required'] quality=fail` |
| 2 | `[exit 2]`：approved + Recall 0.6 < `absolute_min=0.9`，无硬失败 | `exit=2 hard=[] quality=fail` |
| 3 | `[exit 3]`：同 run 用 `status=unapproved` 配置 | `exit=3 quality=unknown thresholds_unapproved` |
| 4 | `[exit 4]`：`mode=live` | `exit=4 quality=None` |

## 4. 偏离与未做

- 目录测试用 `--basetemp backend\.pytest-tmp\t006b-eval`（handoff 写的是 `eval-all`），避免删除上一轮 T005 local run 产物；命令语义相同，结果见证据。
- 未把 `git show --stat HEAD` 写入证据（不能把自身 commit 的 stat 放进同一 commit），stat 见本报告 §3 与交接回复。
- 未做：baseline/diff 报告（T007）、CLI（T008）、live（禁止）；未替主人审批任何阈值；未新增依赖。
- 质量模式默认关闭（`quality=False`），T006a 调用方行为不变；`exit 0` 在默认模式仍只代表硬门禁通过。

## 5. 风险与遗留

- `gate_v0_1.json` 仍无任何阈值且 `unapproved`：在 T009 审批前，`quality=True` 必然 `unknown`（exit 3），不能当作质量通过——这是设计约束，不是缺陷。
- 建议阈值是机械规则（2pp 余量 + 2pp 回退 + 分母作 `min_sample`），不是统计保证；badcase `safety` 仅 2 题、拒答仅 2 题，分层阈值波动大，审批时需人工判断。
- b0 无 `should_refuse` 题 → `refusal_recall` 无适用样本；成本样本为 0 → `cost_per_case_cny` 在质量模式会 `unknown`，若审批需先补数据。
- `max_regression_pp` 只认同 `pipeline_version` + suite + dataset；跨版本只能分析、不能放行（设计 §8.3）；无 baseline 时回退检查显式 `skipped`，不会误报 unknown。
- 真实 run 来自 pytest 临时目录，目录可能被后续测试清空；provenance 以 proposal 中的 `run_id` + `gate_config_hash` + 证据链为准。
- 已知 flake `test_g08_short_budget_cancels_inflight_model_call` 本次全量未命中。

### 交接摘要

- commit `p0/T006b gate quality layer`（基线 `439fc1b`，未 push）；交付 `gate.py`、`gate_v0_1.json`、`test_gate_quality.py`、本报告、`evidence/T006b/` 4 份。
- §5 六条全绿：stratum+all 无综合分；阈值/回退/各自分母完整；校准只提案且未审批→unknown→3；exit 2 仅质量、硬失败优先 1；waiver 需 reason+approver 且硬门禁拒绝；配置 unapproved+阈值空。
- 退出码 0/1/2/3/4 各有实测输出（`04-exit-matrix.txt`）；真实链路 0/2/3 见 `quality-chain.txt`。
- 通过数：包 29、目录 233、全量 1506（0 failed/0 error，6:13）。
- 建议阈值：b0 Recall/MRR/nDCG = 0.9487/0.8498/0.8755（分母 32）；badcase = 0.7479/0.6967/0.6651（分母 10）；均 `max_regression_pp=2.0`。
- 风险：阈值待 T009 人工审批前质量模式恒 exit 3；小样本分层与零成本样本需人工评估。
