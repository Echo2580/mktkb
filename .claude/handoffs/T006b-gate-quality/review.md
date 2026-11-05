# T006b · 门禁质量层 + 校准 + 豁免 — 独立验收 review

- 对象：`5a4c054`（`p0/T006b gate quality layer`，父 `1ea649f`）；分支 `p0/obs-eval`。
- 验证时 HEAD `fb0b937`（`6d6ea97`/`fb0b937` 均为 bookkeeping）；`git diff --stat 5a4c054..HEAD -- backend docs/evaluation` 为空，交付树与 `5a4c054` 一致（`verify/T006b/03-commit-config.txt:4`）。
- 环境：Windows/PowerShell；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；`.venv` Python；串行 pytest，basetemp 在 `%TEMP%`；零真实模型/OCR/embedding/rerank，未读 `.env`。
- **总判定：PASS**。§5.1–§5.6 全部 PASS；无 HIGH；3 条 MEDIUM 为 T007/T009 输入约束，不构成本包验收失败。

## 1. §5 逐条

| 条 | 判定 | 独立复核（证据/代码） |
| --- | --- | --- |
| §5.1 stratum+all、无综合分、缺指标 unknown | **PASS** | `02-probe-output.txt:30,34-36,47`：未审批 b0 45 指标行 / 42 approval unknowns、approved exit 0、无语义 `score/composite`；缺 `summary.metrics` 中的单指标 → `unknown`/observed None。实现 `gate.py:2018-2026`、`:2711-2722`；测试 `test_gate_quality.py:453,498`。边界见 LOW-1。 |
| §5.2 阈值/回退/各自分母 | **PASS** | `02-probe-output.txt:17-19,42-50,54-55`：检索 b0 32/badcase 10、答案 32/13、badcase 拒答 2/11/2；`absolute_min`/`absolute_max` 双向；同版本回退 2.125pp→exit2，跨版本→unknown/exit3；min_sample=11>10、14>13 均 unknown，未复用 hard 13。实现 `gate.py:2044-2105`、`:2304-2409`、`:2496-2531`；测试 `:531,579,636,660`。 |
| §5.3 校准只提案、未审批 unknown | **PASS** | `02-probe-output.txt:12-16,26-28,30`：proposal 与 `evidence/T006b/*proposal.json` 逐对象相等（45/105 行），`gate_config_hash=eeb7...`、run_id 绑定；config 字节未变；写回 `gate_v0_1.json` 被 `ValueError` 拒绝；approved 输入仍输出 `status=unapproved`；未审批 b0 → exit3/quality unknown（42 unknowns）。实现 `gate.py:2954-3077`；测试 `:694,770,782,836`。 |
| §5.4 0/1/2/3/4 可达、1 优先、2 只质量 | **PASS** | `02-probe-output.txt:30,34,37,54,65,69-70`：0（approved pass）、1（security/trace 硬失败，含未审批配置）、2（绝对阈值/回退）、3（未审批/跨版本）、4（live，quality=None）；`EXIT_QUALITY_REGRESSION` 仅 `gate.py:3403` 一处，优先级 `:3396-3405`；测试 `:944,817,858,890`。 |
| §5.5 waiver reason+approver、拒绝硬门禁、不改硬失败/unknown | **PASS** | `02-probe-output.txt:58-65`：缺 reason/approver → ValueError；`trace_integrity` waiver → ValueError；全局 waiver → exit0/pass_with_waivers（2 条记入 warnings/waived）；仅 all 的 waiver 留 text 失败→2；未审批+waiver 仍 3；硬 security_leak+waiver 仍 1。实现 `gate.py:693-705`、`:2724-2769`；测试 `:982,991,997,1039,1121`。 |
| §5.6 测试/配置/提交边界 | **PASS** | `01-tests.txt`：包 29、目录 233、全量 1506（0 failed/0 error，389.41s）。`02-probe-output.txt:2-9`：status=unapproved、15 指标、阈值全 null、hard_gate_min_sample 32/13。`git show --name-status 5a4c054` 仅 handoff §2 允许的 8 文件（`03-commit-config.txt:11-21`）；report 63 行。 |

## 2. 回归（T006a 语义）

- `security_leak` 合成 forbidden 泄漏 + quality=True → exit1（`02-probe-output.txt:65`）；`trace_integrity` 真实 T005 run 改 `schema_meta` → exit1（`:69`）。两项均未被 quality 的 2/3 覆盖。
- `mode=live` + quality=True → exit4、quality=None（`:70`）；未审批配置下硬失败仍 1（`:69`），不是 3/2。
- `quality=False` 在真实 b0 仍 exit0、quality=None（`:71`）；T006a `test_gate.py` 80 条包含在目录 233 中全绿。
- 硬门禁分母仍 `evaluated_count`：真实 b0=32、badcase=13（probe C1/C4），未改 T006a 口径。

## 3. 问题分级

- **MEDIUM-1 · proposal 到 config 的转写缺口（T009）**：proposal 按 stratum 给 `min_sample`/阈值（b0 exact=24/text=8；badcase price=4/poster=2/notice=2/clarify=2/policy=1/safety=0），但 `MetricSpec` 只有一个 `min_sample`/阈值并应用到每个 stratum（`gate.py:2496-2531`、`:2567-2594`）。取 all 级建议（32/10、0.9487…）会使小 stratum unknown 或 fail：`02-probe-output.txt:39`（min_sample=32→exit3）、`:40`（建议阈值直接当配置→quality fail/exit3）。审批必须为每个指标选跨 stratum 可行的单值（b0 检索/答案≤8；badcase 检索≤1 或接受 unknown），或后续扩展配置 schema。
- **MEDIUM-2 · baseline 身份校验不完整（T007）**：`max_regression_pp` 只比较 `pipeline_version`+`suite`+`dataset_version`（`gate.py:2330-2369`），未比较 design §8.3 的 `corpus_sha256`/`gate_version`/`mode`/`scope`。跨 `pipeline_version` 已正确 unknown；同 pipeline 但不同 corpus 的 baseline 会被接受。T007/T009 必须在 gate 外校验完整 baseline_id。
- **MEDIUM-3 · proposal provenance 仅临时目录可复现（T007）**：`B1/B2` 能用 `%TEMP%\t005-runs` 的 03:57 T005 local run 逐对象复现两份 proposal；这些 run 目录未入库，proposal 只带 `run_id`+`gate_config_hash`，仓库内无法再解析 run_id。观测值与 T005 证据 `02-local-replay.txt:10-11,29` 一致；T007 需持久化 run 或明确引用 T005 证据，不能只凭 proposal 重建 baseline。
- **LOW-1 · summary 整个 metrics 映射缺失时回退重算**：`02-probe-output.txt:48` 显示 summary 无 `metrics` 键 → 从 cases.jsonl 重算并 exit0（仅 warning）；单指标缺失已 unknown（`:47`）。严格 fail-closed 应把整个映射缺失也标 unknown；当前不会默认 0，但可凭 rows 通过。
- **LOW-2 · 运行组覆盖不全**：配置只有 `p95_latency_ms`+`cost_per_case_cny`；design §8.2 还列 P50、tokens、重试、degraded。§5.1 只要求覆盖四组，故不 FAIL；T007 若报告这些指标，当前无门禁字段。
- **LOW-3 · `GateConfig.to_dict` 仍输出旧键 `min_sample`**（`gate.py:310-321`），而加载器只认 `hard_gate_min_sample`（`:391-402`）；T006a LOW-1 未修，勿 round-trip。
- **LOW-4 · `gate_config_hash` 是 canonical payload hash，不是文件字节 hash**：`gate.py:447-457`；`eeb7...` 与文件 sha256 `8b37...` 不同（`03-commit-config.txt:37-38`）。proposal 绑定内容而非格式；审批记录应写 canonical hash，避免误用文件 sha。
- **LOW-5 · 证据展示裁剪**：`quality-chain.txt:56-101` 的 badcase 明细只显示 all/price/safety 三个 stratum，实际 proposal 有 7 个 stratum/105 行（probe B5/B9）；报告 §3 已写 105，属展示裁剪，不影响结论。

## 4. 未覆盖 / NOT-RUN

- 零真实模型/OCR/embedding/rerank；无 live、无网络；未读 `.env`。
- 未执行 T007/T008；未生成/审批 baseline，未写 `approval.json`；未替主人审批任何阈值。
- 未测试损坏 trace DB 字节、NaN/Inf 阈值、`summary.json` 篡改（除缺指标外）、并发/性能；T006a R1 已覆盖 trace schema 缺失/不匹配。
- 未重跑旧基线；全量 1506 只跑 1 次；未运行开发者的 chain 脚本，只独立复现其关键结果。
- 未覆盖 `cross_entity`/`stale_bypass` 的真实 entity/as_of（设计 v0.1 无字段，沿用 T006a not_applicable）。

## 5. 对 T007 的输入约束

1. **baseline 审批可用性**：仓库无 approved baseline / `approval.json`；`gate_v0_1.json` 仍 `unapproved` 且阈值全 null。`quality=True` 对硬门禁通过的干净真实 run（b0/badcase）必 exit3；硬失败 run 仍 exit1。`quality=False` 的 exit0 只代表硬门禁通过，不能当质量通过。T007 只能用 fixture approved 配置证明“可审批/拒绝”，真实 P0 baseline 待 T009。
2. **未审批阈值影响**：质量状态恒 unknown（无硬失败时 exit3，有硬失败仍 exit1）；不要把 exit3 当回退/失败；审批必须改 top-level `status=approved` 并填指标阈值，`quality_layer.status` 仅是元数据（加载器不读，`gate.py:375`）。`GateConfig.to_dict` 不可 round-trip。
3. **proposal provenance**：两份 proposal 可由 `%TEMP%\t005-runs` 的 T005 run 逐对象复现（run_id 见 `03-commit-config.txt:42-43`），但未入库；仓库内只有 proposal 和 T005 证据。T007 的 baseline 记录必须持久化 run/trace 或引用 T005 证据。
4. **proposal 转写**：per-stratum 建议不能直接写进单值 config；取 all 级 min_sample/阈值会使小 stratum unknown/fail（C10/C11）。需按最小非零 stratum 选择 min_sample（b0 8；badcase 1）并选跨 stratum 阈值；`cost_per_case_cny` 零样本、`p95_latency_ms` 无 SLA 会持续 unknown，审批时需补数据或明确移除/给阈值。
5. **baseline 身份**：gate 只校验 pipeline/suite/dataset；T007 审批/比较需自行校验 corpus_sha256/gate_version/mode/scope（design §8.3）；跨 pipeline 只能 explicit compare，不能放行。
6. **配置格式**：加载器只认 `hard_gate_min_sample`（`:391-402`）；`max_regression_pp` 只读 metric 字段；`quality_layer` 元数据不参与判定。

## 6. 证据与边界

- 验证证据：`docs/reports/OBS-EVAL/P0/evidence/verify/T006b/`（`01-tests.txt`、`02-probe-output.txt`、`03-commit-config.txt`、`probe.py`；UTF-8 无 BOM、ASCII 文件名）。探针 67/67 PASS。
- 未改 `evidence/T006b/`、交付物、`_index.md`、其他包产物；未 commit/push。
- 结束时 `git status --short` 仅新增本 review 与 `verify/T006b/`。
