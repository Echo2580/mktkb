# P1FIX 证据 08：测试、业务评测、门禁与真实边界（前后对照）

> 环境：Windows；`.venv\Scripts\python.exe` 3.12.7；所有 pytest 命令均设
> `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`、`-p no:cacheprovider`、独立 `--basetemp`；
> 零真实 provider/网络；未读 `.env`；未读 Holdout 逐题/答案/逐题结果。

## 1. 测试用例通过数（与业务评测成绩分开）

| 命令 | 结果 |
| --- | --- |
| 全量 `pytest backend/tests -q`（本次只跑 1 次） | **2023 passed / 0 failed / 0 error，566.53s（9m26s）**，唯一 warning 为既有 `StarletteDeprecationWarning` |
| 定向合并（19 个本次新增/受影响文件，日志 `data/targeted-tests.txt`） | **284 passed / 0 failed，103.59s** |
| `test_p1_refusal_controls.py`（A，offline 全量语料索引） | 23 passed |
| `test_p1_t105_anaphora_field.py`（rag+integration，B） | 27 + 29 passed（两层分别 collect/运行） |
| `test_p1_source_bridge.py`（integration，C）+ `test_p1_source_bridge_mapping.py`（unit） | 3 + 4 passed |
| `test_p1_refusal_scope_http.py`（A，spy 零 chat） | 3 passed |
| `test_diff_release_gate.py`（D 反例/合法） | 15 passed |
| `test_baseline_portability.py`（E） | 21 passed |
| `test_live_request_accounting.py`（F mock 负例） | 5 passed |
| 前端 `npm run typecheck` / `vite build` | exit 0 / exit 0（40 modules，241ms） |

改前基线（T900 独立验收）：1933 passed。本次 +90 个用例全部为新增/受影响包，无 skip/xfail，
未删除既有断言（仅按新证据链补齐 `test_report.py` 合法场景输入、给 `test_p1_t106_copy.py`
SAMPLE_FIELDS 补 `metric/topic` 两个新文案占位）。

## 2. 业务评测（local，确定性离线）前后对照

| suite | 改前（P0/T900） | 本次改后 | 说明 |
| --- | --- | --- | --- |
| b0 | pass29 / fail3 / skipped_ocr8 | **pass29 / fail3 / skipped_ocr8** | 对 P0 run 逐例签名 `(case_id,status,kind,error,checks)` **diff=0/40** |
| badcase | pass9 / fail4 | **pass9 / fail4** | 对 P0 run 逐例签名 **diff=0/13** |
| regression | pass5 / fail2 | **pass7 / fail0** | 仅 RG005/RG007 由 fail→pass（期望变化，逐条解释见 A 证据） |
| gate（local，gate_v0_1 配置） | exit 3 / hard `[]` / quality unknown | **exit 3 / hard `[]` / quality unknown**（三套一致） | 未降低门槛；local 不能作为发布放行 |

原始对照：`data/local-compare.json`（含三套 status_counts、逐例 diff 数、pipeline_version、gate 结果）。

## 3. 门禁 / baseline / 发布放行

- 合法且一致的真实 P1 产物：`release_allowed=True`（`data/D-verify-release-chain.json`）；
- 同 `gate_version` 改阈值内容 → `gate_config_drift`；旧 run 的 gate → `current_gate_run_mismatch`；
  缺 gate → `current_gate_missing`（均 `release_allowed=False`）；
- baseline 审批后配置漂移 → `baseline_gate_config_drift`（单测）；跨版本固定
  `explicit_cross_version_analysis_only`；
- `pipeline_version`：旧 `08166b113481`（P1 baseline `bc6f6f906db1`）→ 本次代码语义变化后
  **`d3ca88d2c515`**。旧 baseline 与新 run 属跨版本，只能 `compare_with` 分析、不能放行；
  新 P1 release baseline 未建立（需真实 live run + gate 重评 + 主人重新审批，见 §6）。
- E 归档/恢复：真实 `bc6f6f906db1` 归档 6 文件 → verify ok → restore 到隔离根 → `baseline list
  approved=yes`、`load_baseline`/`load_run` 通过；源 `var/**` 摘要逐字节不变。

## 4. Holdout（只报告受限聚合；执行成功 ≠ 答案通过）

同一默认受限入口（`run --suite holdout --mode local --holdout-labels <本地 labels>`，
**未开启 details**，只产出 manifest+summary）：

| 指标 | 改前（T900 独立聚合，HEAD 代码） | 本次改后 | 对照 |
| --- | --- | --- | --- |
| 执行 | 30/30，`error_count=0`，分母 30 | **30/30，`error_count=0`，分母 30** | 相同 |
| 答案通过 | pass 7 / fail 23 | **pass 7 / fail 23** | 相同 |
| 拒答混淆 | TP3/FN3/FP3/TN21（recall 0.5/precision 0.5/false_refusal 0.125） | **相同** | 相同 |
| Recall@10 / MRR@10 / nDCG@10 | 0.4537037 / 0.5740741 / 0.4730013 | **完全相同** | 相同 |
| 其他质量指标（value_hit/source_hit/citation/empty_recall…） | — | **完全相同** | 仅 p50/p95 延迟噪声（203→197 / 1001→971ms，非质量口径） |
| pipeline_version | `735da1397044` | `d3ca88d2c515` | 版本区分，符合预期 |

说明：T108-R2 曾记录 `Recall@10=0.5154`，那是 **T108 时点的旧 pipeline**（早于 T109–T114），
不是本次改动前基线；以同一 HEAD 代码的 T900 独立聚合 run 为改前基线，本次 A–F 修复**没有**
改变 Holdout 聚合质量。**“30/30 执行成功”不是“30/30 答对”**；7/30 答案通过如实保留，
原 P1 没有 Holdout 最低答案通过率阈值，本次不编造阈值。

## 5. API / schema / 依赖兼容性

- `AskResult` 12 字段、`MessageView` 12 字段、`SourceSummary` 6 字段、`SourceView` 10 字段
  **前后一致**（`conversations/schemas.py` 零 diff；仅字段**取值**变化，D-3 已授权）；
- `conversations/models.py`、`documents/models.py`、迁移文件零 diff；无业务库/索引库 schema 变化；
- `backend/pyproject.toml`、`uv.lock`、requirements 锁、`frontend/package.json` 零 diff；
  无新增生产依赖；
- 冻结 fixtures `b0.jsonl`/`badcase.jsonl`/`regression.jsonl`/`holdout-questions.jsonl` **零改动**；
  `var/**` 原产物与 `docs/evidence/**` 零改动；
- 新公开评测数据使用独立文件 `fixtures/evaluation/refusal-controls-2026-11-10.jsonl`（带固定
  `label_version`），不改冻结历史。

## 6. 未执行的真实验证（NOT-RUN）与后续授权

1. **真实 live 检索评测重跑**（T111/T112 式 embedding/rerank）：NOT-RUN——本次零真实调用、
   未重签 GO、未触碰预算/账本；如需验证新 pipeline 的 live 检索指标，需主人按既有方案 A 重新授权
   GO/预算与阶段额度。
2. **新 P1 release baseline**：未建立（需真实 live run → gate 重评 → baseline approve 主人审批）。
   旧 baseline `bc6f6f906db1` 已如实标为旧 pipeline，不得冒充新发布基线。
3. **真实端到端答案评测、OCR 质量、扩充 live 套件（badcase/regression/holdout live）**：
   NOT-RUN——属后续授权范围（P2），本次不自行开展。
4. **Holdout live**：NOT-RUN（同上）；本次只跑既有受限聚合入口。
5. **前端 e2e（Playwright）**：NOT-RUN——本环境未装配浏览器/服务；本次前端改动只用
   typecheck/build + 后端真实 HTTP 数据链路覆盖。若需 e2e，应在既有隔离数据 + 离线/mock 服务
   环境重跑受影响用例（02-chat/acceptance-02/05 等）。
6. 未运行真实 provider 的其它证明：所有测试进程使用项目既有隔离配置与 socket/provider guard，
   零外网请求。

## 7. 边界与偏差披露

- **Holdout 题干误读（自我披露）**：开工做 fixture 清单时，一个脚本把
  `fixtures/evaluation/holdout-questions.jsonl` 的题干一并打印到了本地临时输出（未含答案/逐题结果，
  未入库）。发现后已停止读取该文件，**未使用任何 Holdout 题干定位或调参**；本次所有修复只基于
  公开 b0/badcase/regression/源码/公开语料。该偏差如实记录，供独立验收者复核。
- 工作树原有未提交产物 `.claude/handoffs/_index.md` 修改、`docs/面试/`、`2026-11-10-p1-takeover.md`
  本次**未改、未清、未提交**；收尾 `git status` 与开工一致（另有本次改动清单，
  `data/final-git-status.txt` / `final-git-diffstat.txt`）。
- 只读副作用说明：D 的真实产物复核通过 `evaluate_gate` **只读打开** `var/eval/runs/**/traces.sqlite3`
  （SQLite WAL 模式），该 run 目录的 `traces.sqlite3-shm` 共享内存文件 mtime 被更新（内容为非持久
  共享内存；`-wal` 仍为 0 字节，主库 `traces.sqlite3` 与 `cases.jsonl/summary.json/run_manifest.json/
  gate.json`、baseline `baseline.json/approval.json` 的 mtime/size 均与历史一致，未改内容）。
  该文件本就是 T112 产物的一部分（32768B），不属于本次“修改原 var 产物”。
