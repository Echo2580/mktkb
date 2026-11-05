# P0 验收报告（OBS-EVAL · P0 · T008b）

> 分支 `p0/obs-eval` @ `5152298`（纯簿记；代码基线 `f2c0209` T008a）。日期 2026-11-05。
> 环境：Windows PowerShell；`.\.venv\Scripts\python.exe -B`；会话预算
> `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`。所有运行产物写在 `%TEMP%\t008b-p0-flow\`
> （或 pytest `--basetemp`），**不入库**。
> **结论口径**：默认门禁仍是 `exit 3 / thresholds_unapproved`；真实 baseline 与阈值审批属
> T009 人工门，**尚未建立**。本报告不声明质量达标，也不把测试内演示配置当成审批。

## 0. 免责句（设计原文，逐字引用）

> P0 的结论只证明离线回归与确定性门禁工作正常，不证明端到端 RAG 的真实回答质量已经提升；
> 真实效果在 P1/P2 用固定数据集验证。（设计 §11 原文）

> P0 只证明离线回归与确定性门禁工作正常，不证明端到端 RAG 的真实回答质量已经提升；
> 真实检索与生成效果在 P1/P2 用固定数据集验证。（计划 Task 7 Step 6 原文）

## 1. 七条验收（设计 §11）：命令、结果、证据锚

统一测试命令（7 项，7.2 秒）：

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_p0_acceptance.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\p0-acc
-> 7 passed, 1 warning in 7.21s（exit 0）
```

| # | 验收项 | 落地测试 | 实测结果 |
| --- | --- | --- | --- |
| 1 | 现有业务行为不变 | `test_acceptance_01_business_behavior_unchanged` | 归一化响应 == golden；`X-Trace-ID`/`X-Request-ID` 存在；同应用二次相同提问仍等于 golden |
| 2 | `trace_id` 关联完整阶段 | `test_acceptance_02_trace_id_is_queryable_end_to_end` | 头部 trace_id → 记录；`trace.request_id == 响应体 request_id`；必需 Span 全部命中；只读重开仓储仍可查 |
| 3 | B0 40 与 Bad Case 13 独立回归 | `test_acceptance_03_b0_and_badcase_regress_independently` | b0 40 行 / 32 scored / 8 OCR；badcase 13 / 13；两目录三件套 + `traces.sqlite3` 各自独立 |
| 4 | 绑定 dataset/index/pipeline 版本 | `test_acceptance_04_results_bind_versions` | manifest = summary = trace：`dataset_version`、`index_revision`(6/4)、`pipeline_version`(735da1397044)、`gate_version` |
| 5 | 可生成 baseline、diff、JSON 报告 | `test_acceptance_05_baseline_diff_and_json_report` | 默认配置 gate=3、审批被拒、无 `approval.json`；测试内审批配置 gate=0 → baseline `c0ce2856938f` → `diff.json` `release_allowed=True` + `report.md`/`report.html` |
| 6 | 硬门禁失败返回非零退出码 | `test_acceptance_06_hard_gate_failure_returns_nonzero_exit` | 敏感来源 case（Q01 自身的 gold unit 标为 forbidden）→ `security_leak` fail → CLI `gate` exit **1** |
| 7 | 零真实模型调用、零 Token 费用 | `test_acceptance_07_zero_real_calls` | provider spy=0、`socket.connect`=0、`.env` 读取=0、业务路径模型调用=0；默认 gate=3 |

**逐条要点**

1. **golden 来源与归一化**：`backend/tests/evaluation/golden/chat_response.json`
   （sha256 `b86484dcf1fc45387a361358a4d8f123a32d12d3900f4ebda080088a2bfd8e52`，4244 B）。
   场景：固定 3 行 xlsx（`t003d-dataset.xlsx`）→ 管理员 HTTP 上传 → worker → 发布（revision=1）
   → 员工新建会话问「把城东店和滨江店的宣传海报记录都列出来」（纯 RAG 枚举，0 次模型调用）。
   采集：**仓库外**一次性脚本 `.\.venv\Scripts\python.exe -B %TEMP%\t008b_capture_golden.py`，
   在 commit `5152298`（业务代码未变，基线 `f2c0209`）采集；测试只读、从不回写。归一化 6 项：
   `request_id`/`message_id` → `<uuid>`；`text` 中「（记录 8 位 hex）」→「（记录 <record-ref>）」
   （由本轮随机 version UUID 派生）；`sources[].source_id` → `<uuid>`；`sources[].published_at`
   → `<timestamp>`；`conflicts[].entries[].source_id` → `<uuid>`。`X-Trace-ID` 只断言格式、
   `X-Request-ID` 只断言存在，均不记录值。**重采稳定**：仓库外脚本连续两次独立采集，golden 字节 sha256
   完全相同（证据 01 §E），未循环自证（golden 不是测试运行时生成的）。
2. **trace 端到端**：`trace.request_id` 等于响应体 `request_id`；`http_request_id` 等于
   `X-Request-ID`；`required_spans(RAG, ANSWER)` 全部命中且 `validate_required_spans == []`；
   换一个只读 `TraceRepository` 重开落盘库仍按同一 trace_id 查到同一条记录与同名 Span。
3. **独立回归**：b0 与 badcase 的 `summary.json` / `run_manifest.json` / `cases.jsonl` /
   `traces.sqlite3` 分目录生成，`suite` 正确、run_id 不同、case 集合不相交（Q* vs N*）。
4. **版本绑定**：三处一致（run 清单、`summary.json`、run 内 trace 记录）；`dataset_sha256`
   等于数据集文件实测 SHA-256；同一代码两个 suite 的 `pipeline_version` 相同。
5. **baseline/diff/报告**：真实 CLI（证据 02 步骤 07/10/12）默认配置 gate=3、`baseline approve`
   被拒（`approval.json` 计数 0）、无 baseline 时 `diff`/`export` exit 3「baseline 未建立，待 T009」；
   测试内审批配置（`%TEMP%` 子集配置：检索 5 + 答案 5 指标、`min_sample=1`、宽松阈值）下
   gate=0 → baseline 审批 → `diff` exit 0、`release_allowed=True`、`blocked=None`、`diff.json`
   16 855 B、`report.md` 7 888 B、`report.html` 13 451 B（export 与 diff 报告逐字节相同）。
6. **硬门禁非零退出**：把 Q01 自己的 gold unit 声明为 `forbidden_sources` 后，真实检索引用它即
   `security_leak / forbidden_source_citation`；CLI `gate` 返回 1，`scored_count=32 = min_sample`。
   只证明"硬门禁失败非零退出"，不证明所有硬门禁在真实业务里都被触发
   （`cross_entity`/`stale_bypass` 在 v0.1 数据集没有 case 类 → `not_applicable`）。
7. **零真实调用**：评测全流程 + 业务问答均在守卫下运行；`Settings.model_config["env_file"]=None`
   （测试进程不读仓库根 `.env`）。socket 守卫只包评测全流程——`TestClient` 的 asyncio 自管道是
   loopback socketpair，业务阶段只保留 provider/.env/模型替身守卫（模型替身 `calls == []`）。

**变异抽查（证明测试非空转）**：M1 删掉 `main.py` 的 `X-Trace-ID` 响应头 → #1/#2 FAILED；
M2 让 `gate.py` 不再上报 `forbidden_source_citation` → #6 FAILED（实际退出码 3≠1）。
两处变异均已用 `git checkout` 还原、`git diff` 行数 0（证据 01 §C/§D）。

## 2. P0 全流程 CLI 实测（真实命令，产物只在 `%TEMP%`）

| 步骤 | 命令（`tools/rag_eval.py`，省略公共前缀） | exit | 关键结果 |
| --- | --- | --- | --- |
| 01 | `--help` | 0 | 6 个子命令；无 `--allow-holdout-details` |
| 02/03 | `dataset validate --suite b0|badcase --path fixtures\evaluation\*.jsonl` | 0/0 | b0 40 题 `bd4f0f7ccc6e…`；badcase 13 题 `e5f0662af3f2…` |
| 04/05 | `run --suite b0|badcase --mode local` | 0/0 | `b0-local-…-225210f7` 40 行；`badcase-local-…-3ea1fcd8` 13 行 |
| 06 | `run --suite b0 --mode replay --from-run <b0-local>` | 0 | `b0-replay-…-baa24732` 40 行，逐行 status/checks/metrics 与 local 相同 |
| 07/08/09 | `gate --run <run>`（默认配置） | 3/3/3 | `scored=32/32`、`13/13`、`32/32`；`hard_failures=[]`；`quality=unknown`、`config_status=unapproved` |
| 07 | `gate … --calibrate` | 3 | 只写 `gate_proposal.json`（`status=unapproved`、`approval_owner=T009 human gate`） |
| 10 | `baseline approve`（默认配置） | 3 | 现场重算拒绝；`approval.json` 计数 0 |
| 11 | `baseline list` | 0 | 0 条 |
| 12/13 | `diff` / `export`（无 baseline） | 3/3 | `ERROR: baseline 未建立，待 T009（c0ce2856938f）` |
| 14 | `run --mode live` | 2 | argparse 拒绝 `invalid choice: 'live'` |
| 15 | `run --mode replay`（缺 `--from-run`） | 3 | `必须提供 replay_from…不得静默降级` |
| 16 | `run … --allow-holdout-details` | 2 | `unrecognized arguments`（P0 无此开关） |
| 18 | `gate --config <测试内审批配置>` | 0 | 机制演示：`config_status=approved`；**不是 T009 审批** |
| 19/20 | `baseline approve` / `list` | 0/0 | `baseline_id=c0ce2856938f`、`approved=yes`（仅 `%TEMP%`） |
| 21/22 | `diff` / `export` | 0/0 | `release_allowed=True`、`blocked=None`；报告与 JSON 落盘 |
| 23 | `gate`（回到默认配置） | 3 | `quality=unknown`、`config_status=unapproved`、质量层 42 条 unknown 且 reason 只有 `thresholds_unapproved` |

产物 sha256（本报告只锚定关键件；完整清单见证据 02）：

```text
run_manifest.json 9b7ff3ed8b04bd153b056ba39caab8a086ddc6a19b3a0faac3834c47e4217945
summary.json      bfa5425f976c84666767f0ba949c5ad8674fc8a1e8c76d11cd84c1ec72802027
traces.sqlite3    106035803019e7a72ed5f2f4fb9f34b14997450dd0dc3219592cf9daa4c83efc
gate.json         7690cad1f057df742f6b676b91bf572f87552e6bdb0056ec9fdebcd63509b870
diff.json         e7302b4b73b7eb91de9c3ed43aedbb233c492999693ea375c72e540a3d53756f
report.md         d9f1a1391295b3bb387fda95d691beab6b0e5f914f517de539e59da83ba8bc45
report.html       5196be631faa831d67a3d6caa3ef6938ed7fec0fd06ea2fad780cedfb9984884
approval.json     a57d21cc71c7f9299cc56270150afc02c5459ce49b6345d5e2b3b30350de0667
baseline.json     f3ab9e0ca6b3013e786cfa5826aeb7f054d07cb80490b860b31adb02488943b6
```

`docs/evaluation/gate_v0_1.json` 前后 sha256 均为
`8b37182472087b878340626a33e4ab5b206026126240bc441e7350dbbccad209`（未改写）。
`git status --short` 在流程前后都只有本包 3 个交付文件，无 `var/` 或 `docs/evidence/**` 变更。

## 3. 口径与分母（与 T005 / T006b 实测一致，未改写）

- b0：40 题（exact 24 / text 8 / OCR 8），`scored=32`（8 题 OCR `skipped_requires_ocr`、0 error），
  status `pass 29 / fail 3`；3 个 fail 为 Q25/Q26/Q31（既有离线检索/抽取口径，非 runner 失败）。
- badcase：13 题，`scored=13`、0 OCR、0 error，status `pass 9 / fail 4`
  （fail：N05/N06/N09/N11）；检索分母 **10/13**（N10/N12/N13 无 gold），答案分母 13（T006b 口径）。
- 版本：`dataset_version` b0 `b0:b0-2026-11-04:bd4f0f7ccc6e`、badcase
  `badcase:badcase-2026-11-04:e5f0662af3f2`；`index_revision` 6 / 4；`pipeline_version`
  `735da1397044`；`gate_version` `mktkb.gate.v0.1`。
- 测试计数：本包 7 项；`backend/tests/evaluation` 313 → **320 passed**（18.52 s）；
  全量 `backend/tests` 1586 → **1593 passed / 0 failed / 0 error**（381.02 s = 6:21；
  T008a 基线 1586 + 7）。与 T008a 报告口径一致（其目录 313、全量 1586）。
  已知 flake `test_g08_short_budget_cancels_inflight_model_call` 本轮未命中。

## 4. 未测边界（NOT-RUN / GAP，必须原样保留）

- **`mode=live` → exit 4：NOT-RUN**。真实 live 在 CLI 参数阶段即被拒（exit 2，证据 02 步骤 14）；
  据 T008a 验收约束（2026-11-05），手改 manifest 会在 `RunManifest.from_dict` 失败（exit 3），
  而 `evaluate_gate` 的 live→4 目前**只有单元测试覆盖**，没有端到端证据。
- **真实 baseline 与阈值审批：NOT-RUN（属 T009 人工门）**。默认配置 `status=unapproved`，
  本报告中的 gate 0 / baseline `c0ce2856938f` 全部来自 `%TEMP%` 内的**测试内**审批配置，
  只证明机制可跑通，不代表任何真实审批、也不代表质量达标。
- **真实 OCR / embedding / rerank / 模型：NOT-RUN**（P0 明确零真实调用；本包守卫实测 0 次）。
- **P1/P2 真实回答质量：NOT-RUN**（无真实检索/生成数据；见 §0 免责句）。
- **HTML 报告：仅生成与字节断言**，P0 七条验收不依赖其渲染效果（设计 §10 同口径）。
- 硬门禁 `cross_entity` / `stale_bypass` 在 v0.1 数据集没有 case 类 → `not_applicable`，
  只证明"失败时非零退出"，不证明这两类门禁被真实触发。

## 5. 放行判断

放行看 `diff.json` 的 `release_allowed` / `release_blocked_reason`（并由 `require_release_baseline`
二次守卫），**不能只看 `diff` / `export` 的退出码**：`export` 是报告层，成功落盘返回 0。
当前仓库状态：无真实 baseline（`baseline list` → 0 条）+ 阈值未审批 → 默认 `gate` exit 3，
`diff`/`export` exit 3（`baseline 未建立，待 T009`）。因此 **P0 当前不放行任何版本**。

## 6. 证据锚（`docs/reports/OBS-EVAL/P0/evidence/T008b/`，4 份）

| 文件 | 字节 | sha256 |
| --- | --- | --- |
| `01-acceptance-tdd-mutation.txt` | 8 934 | `667a7362914518a248891192730440d918dddbb8aae2686882ab22ffd7d7a645` |
| `02-cli-p0-flow.txt` | 14 420 | `b255b9947a75ed6599b375fe6bbf45b80fdc88883428cc55df031f33889bb9fd` |
| `03-pytest-evaluation.txt` | 1 402 | `9a24aa50c61c36a0054a40fd2d46caac17dd5a2a7966f7d0a5d01cb75e26ebb0` |
| `04-pytest-full.txt` | 2 858 | `0e368500750476f4211c854379e4c14ae5281d89cbc921b5ab09cedc28f7b635` |

交付物 sha256：`test_p0_acceptance.py` `632f09bbbbce7f75422d795d05c49b64c454b37ba08539e40269694056b86c59`；
`golden/chat_response.json` `b86484dcf1fc45387a361358a4d8f123a32d12d3900f4ebda080088a2bfd8e52`；
`evaluation/conftest.py`（只追加 fixture）`27f432d1ffd3316fa882c9f15fb1a8f5bee82fd39c99e79ddeed756d35630010`。

## 7. 复现命令

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_p0_acceptance.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\p0-acc
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\eval-all
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t008b-full
.\.venv\Scripts\python.exe -B tools\rag_eval.py run --suite b0 --mode local --out %TEMP%\t008b-p0-flow\b0-local
.\.venv\Scripts\python.exe -B tools\rag_eval.py gate --run %TEMP%\t008b-p0-flow\b0-local   # 期望 exit 3
```
