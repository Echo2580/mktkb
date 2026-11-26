# T209 正式 B0 接线独立离线验收

2026-11-20，Asia/Shanghai。执行角色：独立验收 AI（与开发、经理不同上下文）。工作区 `D:\GPT项目\市场部AI知识库`，分支 `codex/p2-e2e`，HEAD `97b0066`。**本包结论为 `PASS`。**

依据 [T209 B0 独立验收任务书](../../../../superpowers/plans/2026-11-20-t209-b0-independent-acceptance-taskbook.md)。全部请求、审批、题集、trace 与归档均为合成物，落在隔离目录 `var/eval/t209-prep/b0-ia-c008628281234e84b9f19dc5af7dfb85/`（git 忽略）。未发起真实请求，未读真实凭据、预算、账本、GO、正式基线与私有 H2，未改源码、仓内测试、Git 记录与正式注册目录。

## 判定

| 接收条件 | 实测 | 判定 |
| --- | --- | --- |
| 五项验收成立 | A/B/C/D/E 五组共 57 项探针全部按预期 | 达 |
| 核心反例按预期阻断 | 35 项拒绝类反例（A 6 ＋ B 8 ＋ C 6 ＋ D 9 ＋ E 6）全部给出目标错误码或目标异常，无一放行 | 达 |
| 保护工件摘要一致 | 19 份冻结件验收前后各复算一次，0 处漂移；`git status` 前后一致 | 达 |
| 实际守卫命中 0 | 外部类命中 `{}`（回环自建管道另行单列，见下） | 达 |
| Windows 链接用例 | 硬链接用真实文件系统实测通过；目录联接因需子进程跳过，已用注入 `lstat` 补验同一拒绝分支 | 补齐 |

无失败编号，无阻断缺陷。以下"缺口"一节列出本轮确实没有取得运行证据的边界。

## 验收范围

1. **发送前绑定**：CLI 与 `run_live_p2` API 的绑定校验、注入停止点、错 run ID／流水线摘要／题集／语料／旧或篡改 v0.3 配置的发送前拒绝，以及旧计划无绑定的兼容性。
2. **单批 B0 重评分**：`baseline p2-admit` 对合成 Q01–Q40 公开运行件的 40/40 执行、≥36 正确、精确 24/24、OCR 8/8、八项硬门禁与适用性，以及七类输入变异的拒绝。
3. **审批和移植**：`p2-admit` → `p2-approve --receipt` → `archive` → `verify` → `restore` → `list` → `p2-diff` 全链、身份与摘要重核、撤掉原题集路径后的自足性、恢复后逐字节一致，以及错摘要／缺工件／多余文件／重复或覆盖输出的拒绝。
4. **差异和路径边界**：两条合成流水线的跨版本默认拒绝与显式 `--compare-with` 仅分析、同 gate 版本改配置、语料不可比、路径外逃、链接与重解析点、已有目标哨兵。
5. **候选、受限证据和 P2 发布**：合成 E2 候选、声明 holdout 的 manifest、私有字段探针、单次 B0 准入／审批／差异均无法放行 P2，以及 H2 两个必要轴未知的保留。

## 冻结比对

验收开始时与结束时各复算一次 SHA-256，与任务书快照逐行相同（19/19，0 处不符）。

| # | 文件 | SHA-256（前后一致） |
| --- | --- | --- |
| 1 | `backend/src/mktkb/evaluation/baseline.py` | `9cc231660d52a4617a30b6a12234d15c2026ded5da7be0054199777d978a445b` |
| 2 | `backend/src/mktkb/evaluation/cli.py` | `14f52beca1f66b30e8744e9eb3c6cbc3752767464ce12696b9630cb876450258` |
| 3 | `backend/src/mktkb/evaluation/gate.py` | `102350994939fcd47b9c268cf732743a322b1b05bd282d563de06a354b1fec1b` |
| 4 | `backend/src/mktkb/evaluation/p2_b0.py` | `114158ef00f17570654a4b52a13254dd9d8f9d19493b787607b5b14336fa66a3` |
| 5 | `backend/src/mktkb/evaluation/p2_b0_baseline.py` | `3e1932e714d39eded78c1678a6194908c0f52a0c350607dfa8e61b3ddc91bf40` |
| 6 | `backend/src/mktkb/evaluation/p2_contracts.py` | `be873d7b38aa87e44189fedba135e415452d90f510f230d24e11102b824a7b73` |
| 7 | `backend/src/mktkb/evaluation/p2_live.py` | `5b222aac6fee00e40e6adb81e8f37954aaf16f7d3e5b55234ea18380d4afbff5` |
| 8 | `backend/src/mktkb/evaluation/p2_runner.py` | `2e14616368ad721f43fb9bba6de863a25cb7a45bfc7a6f57817289a1b62249e1` |
| 9 | `backend/src/mktkb/evaluation/p2_scoring.py` | `34374d63ff072e849f180640133e925a4fc05b40b7e318ae9d3657e054a4f3d8` |
| 10 | `backend/src/mktkb/evaluation/report.py` | `d03730ffa2d280bc5c2b5ab553efed41e887d210138bccd05c0adf2c65c09192` |
| 11 | `backend/tests/evaluation/test_p2_b0.py` | `462e12c633c371ee0893d35a30d89ec8b217554c99a83f395dc8abc774a57c7d` |
| 12 | `docs/evaluation/gate_v0_3.json` | `3af301dba2d4dbd1bcc9d8f17c656f8a80755820fa2a8559b787974f20b5619d` |
| 13 | `docs/evaluation/gate_v0_3_approved.json` | `b1094cc726230be2ec22ec811d34a948ea4a2fe03aab2c0fcc4f20c99764d961` |
| 14 | `fixtures/evaluation/b0.jsonl` | `bd4f0f7ccc6e9f50ba630598c01b3519804447d4e0f3bfbc2facd54a5a521e4f` |
| 15 | `docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-R1.json` | `c70042e5de6a2016ccdf3f0f284b8e1ff3902efcda833d916b5c794c202a208d` |
| 16 | `docs/reports/OBS-EVAL/P2/T207/cases/document-codes.json` | `3ac6a4eb5570e42312127c39cd6a79d8759bf2fb3821ef0bd45bdee2ca5cc20d` |
| 17 | `docs/reports/OBS-EVAL/P2/T209-PREP/b0-inputs.draft.json` | `241f6ef85cbf62dc1382019c06f4996960e35510a2f4fd1b87107ad5144d4cc1` |
| 18 | `docs/reports/OBS-EVAL/P2/T209-PREP/b0-request-plan.draft.json` | `d5fb3ddb46b6f721ac3f5bfb586371db767892b4b989c4cd3d010a2b3fd808bf` |
| 19 | `docs/reports/OBS-EVAL/P2/T209-ENGINEERING-CLOSEOUT/independent-review-r02.md` | `7f9c8ad5e6a6e8de3996a3c4a35e9e67e7c6ca1f28d615f2c8cee29e552a3fed` |

工作树现场：HEAD 全值 `97b0066726e5b8d6f94cbc0b63a890084550c106`（短 `97b0066`），分支 `codex/p2-e2e`；运行前后 `git status --porcelain` 均为 43 项已跟踪修改、390 项未跟踪、0 项暂存，条目集合未变。`var/` 被 `.gitignore` 第 3 行忽略，隔离区不进版本库。测试期间未修订任何快照。

## 守卫校准与命中

- 解释器：`.venv` Python 3.12.7；pytest 9.1.1；Windows。进程环境在安装钩子前仅保留 `SYSTEMROOT/WINDIR/COMSPEC/PATH/PATHEXT/NUMBER_OF_PROCESSORS/PROCESSOR_ARCHITECTURE`，启动时不存在任何凭据类变量名。
- 九类守卫主动校准各命中 1 次：`credential`、`ledger_budget`、`go`、`private_h2`、`write_outside`、`read_outside`、`child_process`、`dns`、`socket`（校准命中计入独立计数器，不计入实际命中）。
- **实际命中 `{}`**：pytest 段与探针段前后两次导出均为空，`details` 为空。
- **回环自建管道单列**：`socket.bind->127.0.0.1` 7 次、`socket.connect->127.0.0.1` 7 次。调用栈为 `socket._fallback_socketpair → ProactorEventLoop._make_self_pipe → new_event_loop → asyncio.run`，即 Windows 上 asyncio 事件循环的本地自建管道，不是外发。为避免把平台 IPC 误判成违规同时又不能对回环开口子失控，守卫口径调整为：**仅数字回环地址放行并单独计数，其余 `connect/bind/sendto/sendmsg` 一律阻断；全部 DNS API 仍无条件阻断**。此调整与 R02 原守卫的"全阻"不同，原因与影响在此明示：R02 未运行 asyncio，本轮 A02–A06 与 CLI live 分支必须进入事件循环。
- 允许清单在 R02 基础上按任务书扩充：`gate_v0_3_approved.json`、R1 入库配方及其 12 份公开源文件（实际解析路径均在 `fixtures/acceptance`，脚本内断言）、B0 题集、公开文档名映射、两份 B0 草案、T207 公开接收记录。另加一条**刻意不存在**的路径 `backend/missing-approved-config.json`：`test_p2_b0.py` 用它断言 `gate_config_unreadable`，该路径无文件可读，放行不授予任何真实读取能力（脚本内断言其确实不存在）。
- 受守卫解释器中先做一次全新导入并断言 `mktkb.evaluation.p2_b0` 未在 `sys.modules`，导入后 `B0_GATE_CONFIG_HASH=7fa6f47a445f9643eb7f2e5ae78a72411007da38a56fca1082657870b2eab094`，`guard_hits 0`。

## 回归统计与退出码

```text
114 passed, 2 skipped, 1 warning in 12.78s
PYTEST_EXIT 0
GUARD_OPERATIONAL {} loopback {...} detail []
PROBES_SUMMARY pass=57 fail=0 error=0
PROBE_EXIT 0
ENTRY_EXIT 0
```

跳过 2 项，均因守卫禁止子进程，且都落在 `tests/evaluation/test_p2_candidate_report.py`：

| 用例 | 依赖 | 处理 |
| --- | --- | --- |
| `test_verify_rejects_reparse_point` | `subprocess.run(["cmd","/c","mklink","/J",...])` 造目录联接 | 单列缺口；拒绝分支由 D07/D07b 注入补验 |
| `test_import_and_report_path_make_zero_external_attempts` | `subprocess.run([sys.executable,"-c",...])` 独立解释器 | 单列缺口；候选模块导入与报告路径已在受守卫解释器内直接补验 |

唯一警告为 Starlette `TestClient` 的 `httpx` 弃用提示，与本次接线无关。`test_formal_read_rejects_hardlinks` **未跳过**：本机 NTFS 允许 `os.link`，该项真实运行并通过（D06 亦以真实硬链接复验）。

## 逐项实测

### 1. 发送前绑定（A，10 项）

| 编号 | 入口 | 预期 | 实际 |
| --- | --- | --- | --- |
| A01 | CLI `p2-run --mode live` | 合法绑定抵达注入停止点，无输出目录 | exit 3，`error_code=synthetic_gate_guard`，`requests_sent=0`，目录未建 |
| A02 | API `p2_live.run_live_p2` | 同上且门调用恰 1 次 | `P2AuthorizationError(synthetic_gate_guard)`，`gate_calls=['synthetic-b0-a02']`，目录未建 |
| A03 | API（计划绑定到别的 run） | `b0_plan_binding_mismatch` | 同码，门调用 0，目录未建 |
| A04 | API（计划绑定伪造流水线摘要） | `b0_plan_binding_mismatch` | 同码，门调用 0 |
| A05 | API（题面被改一题） | `b0_input_cases_not_frozen` | 同码 |
| A06 | API（一份语料 `publish` 翻转） | `b0_corpus_mismatch` | 同码 |
| A07 | CLI + 未审批 `gate_v0_3.json` | 环境与 GO 之前拒绝 | exit 3，`b0_gate_config_not_approved`，目录未建 |
| A08 | CLI + 已审批配置加 `notes` 改字节 | 同版本改内容拒绝 | exit 3，`b0_gate_file_not_approved` |
| A09 | CLI + 无 `b0_binding` 的旧计划 | 兼容，不被强制进 B0 分支 | `plan_sha256=4362968a…` 不变，无 `b0_*` 码，直达注入发送门 |
| A09b | API `p2_live.load_live_env`（未注入） | 环境边界拒绝 | `live_env_missing` |

A03–A08 同时以断言证明：注入门调用次数 0（A01/A02 恰 1 次）、输出目录未生成。GO／预算／账本读取被注入函数整体旁路，且守卫对 `go`／`ledger_budget` 类别另有兜底。

### 2. 单批 B0 重评分（B，12 项）

正例由项目原生序列化器（`P2RunLedger`／`_write_artifacts`／`P2Authorization`）生成完整公开运行件，并写真实结构的临时 SQLite trace（`TraceRepository`），零真实发送。

| 编号 | 变异 | 预期 | 实际 |
| --- | --- | --- | --- |
| B01 | 无（40 题全对） | 40/40、≥36、24/24、8/8、八门禁 | `p2-admit` exit 0；`executed=40 passed=40 exact_passed=24 ocr_executed=8`；`real_calls=53`；`min_sample=32 scored_count=40` |
| B01b | 同上看适用性 | 必需三项 pass，其余 na 显式 | `exact_value_contract/citation_required/trace_integrity=pass`；na=5 项 |
| B02 | 5 条非精确非 OCR 答案改错 | 低于 36 拒绝 | `b0_score_threshold_not_met`（scorecard passed 35） |
| B03 | 1 条精确题改错 | 24/24 不满足 | `b0_score_threshold_not_met`（exact_passed 23） |
| B04a | 去掉 1 条 OCR 行后重评分 | 评分层识别 OCR 未执行 | `ocr_executed=7`，`required_passed=False`，blocks=`case_not_executed/missing_case/ocr_not_executed` |
| B04b | 同一缺行运行件走准入 | 拒绝 | `b0_rows_incomplete`（行集完整性先于 OCR 分母触发） |
| B05 | 删临时 trace 库 | 拒绝 | `b0_evidence_file_missing` |
| B06 | `summary.network.available=False` | 出站不可核 | `b0_outbound_evidence_invalid` |
| B07 | `pipeline_version=d3ca88d2c515` + 绑定摘要置零 | 旧 R1 证据 | `b0_current_pipeline_or_corpus_changed` |
| B08 | `execution=dry_run` | mock 冒充 live | `b0_run_identity_invalid` |
| B09 | 输入变异 ↔ 分数因果 | 40 → 35 | `pristine=40 mutated=35` |
| B10 | 删掉 Q01 trace 的全部 span | trace 内容被核 | `b0_hard_gate_blocked`（`trace_integrity` 触发） |

B09/B10 是"评分与 trace 检查确实执行"的直接证据：只改输入、不改校验代码，输出随之改变。

### 3. 审批和移植（C，13 项）

`run_id=synthetic-b0-b01`，`baseline_id=dd55b9fa5c87`，`gate_config_hash=7fa6f47a…`，合成审批人 `synthetic-owner`。

| 编号 | 环节 | 预期 | 实际 |
| --- | --- | --- | --- |
| C01 | `p2-admit` | run／baseline／配置／证据摘要可重算 | 四项全部重算一致（`evidence_ok=True`） |
| C02 | `p2-approve` 用错 `evidence_sha256` | `b0_approval_receipt_mismatch` 且不建 root | 同码，root 未创建 |
| C01b | 正式合成审批 | 保存基线 | exit 0，`<root>/<id>/approval.json` 存在 |
| C03 | 第二次审批 | 拒绝覆盖 | `b0_target_exists` |
| C04 | `baseline list` | 列出且标 P2 不放行 | `approved=yes p2_release_allowed=no` |
| C05 | `archive` | 归档含审批 | 13 个文件（7 run + 4 baseline 证据 + baseline/approval） |
| C06 | 撤掉原题集路径后 `verify`/`restore` | 两者仍可用 | 均 exit 0（移植证据自足，不依赖 `B0_CASES_PATH`） |
| C07 | 恢复后比对 | 逐字节一致、审批绑定不变 | 7 个工件全等；`approver=synthetic-owner`，`gate_result_sha256=evidence_sha256`，`artifact_sha256` 逐键相同 |
| C08 | 第二次 `restore` | 拒绝覆盖 | `b0_target_exists` |
| C09 | 归档删 `run/requests.jsonl` | 拒绝 | `归档文件集合不符（缺 ['run/requests.jsonl']）` |
| C10 | 归档加 `run/extra.json` | 拒绝 | `归档文件集合不符（多 ['run/extra.json']）` |
| C11 | 归档到已存在目录 | 拒绝且哨兵不变 | exit 3，`归档目标已存在，拒绝覆盖`，哨兵字节未变 |
| C12 | `p2-diff` 同基线 | 可分析但不放行 | `baseline_approved=true release_allowed=false`，`p2_release_status=blocked_pending_n_c_u_h2_evidence` |

### 4. 差异和路径边界（D，10 项）

第二条合成流水线用同一生成器、把绑定的流水线源码摘要改为 `f*64` 生成；`manifest.pipeline_version` 仍等于当前 `pipeline_version()`，两条都通过各自准入。

| 编号 | 场景 | 预期 | 实际 |
| --- | --- | --- | --- |
| D01 | 显式 `--baseline` 指向另一流水线、不给 `compare-with` | 默认拒绝 | `CrossVersionBaselineError`（`…+6fbde812…` ≠ `…+ffff…`） |
| D01b | 不给 `--baseline` | 按当前身份找不到基线即拒绝 | `BaselineError: baseline 不存在` |
| D02 | `--compare-with <基线>` | 仅分析、不放行 | exit 0，`comparison=explicit_cross_version`，`release_allowed=false` |
| D03 | 同 gate 版本、配置加 `notes` | 拒绝 | `b0_gate_file_not_approved` |
| D04 | 语料摘要不同的身份 | 不可比 | `BaselineComparabilityError`（`corpus_sha256` 不可比） |
| D05 | 语料源指向 `fixtures/acceptance` 之外 | 路径外逃拒绝 | `b0_corpus_path_invalid` |
| D06 | 真实硬链接 | 拒绝 | `b0_link_rejected`（`os.link` 真实成功） |
| D07 | 注入 `FILE_ATTRIBUTE_REPARSE_POINT` | 拒绝 | `b0_link_rejected` |
| D07b | 注入 `S_IFLNK` | 拒绝 | `b0_link_rejected` |
| D08 / D08b | 恢复目标已存在 | 拒绝且哨兵不变 | `b0_target_exists`；`unchanged=True` |

全部文件系统反例只落在本次隔离区内，哨兵 `sentinel.bin` 前后字节相等。

### 5. 候选、受限证据与 P2 发布（E，12 项）

| 编号 | 场景 | 预期 | 实际 |
| --- | --- | --- | --- |
| E01 | 合成 E2 候选归档 | 不可发布、无审批 | `state=candidate has_approval=false publishable=false release_baseline=false`，payload 内无 `approval.json` |
| E01b | 候选恢复 | 仍无审批 | `approval=None`，状态保持 candidate |
| E02 | manifest 声明 `holdout_details=true` | 拒绝归档 | `候选归档 payload 被既有证据链拒绝: holdout 相关 run 拒绝归档/恢复…` |
| E03 ×4 | `holdout_details` / `h2_axis_notes` / `private_case_marks` / `ocr_secret_key` | 拒绝 | 四项均 `b0_private_fields_rejected` |
| E04 | B0 准入证据 | 四轴 unknown、不放行 | `p2_release_allowed=false`，四轴全 `unknown`，状态 `blocked_pending_n_c_u_h2_evidence` |
| E04b | 已审批 B0 基线的差异 | 不能作为发布放行依据 | `CrossVersionBaselineError: comparison='analysis' 不能作为发布放行依据（p2_release_blocked_pending_n_c_u_h2_evidence）` |
| E05 | 正式 v0.3 跨场景缺项 | T207 缺项仍保留 | 接收记录仍记 `required unknown=2`（C27/C29，`forbidden_source_unmappable`）；B0 证据四轴全 unknown |
| E06 | H2 两个必要轴未知 | 保留且不被 B0 伪称闭合 | `p2_standards.holdout` 仍为 `total=30 min_pass=24`；`holdout` 轴 `unknown`；B0 manifest 无 `safety/cross_user/stale_source` 键、无 `holdout_*`/`private_*`/`h2_*` 键 |

## 缺口与未覆盖

1. **Windows 实体目录联接未跑**。`mklink /J` 需子进程，被守卫阻断，`test_verify_rejects_reparse_point` 因此跳过。同一拒绝分支已用注入 `lstat` 属性补验（D07/D07b），但"真实联接对象被 `safe_path` 挡下"这一条仍缺运行证据。建议在允许子进程的独立窗口补一次。
2. **`b0_diff_dataset_mismatch` 分支不可达**。B0 身份把 `dataset_sha256` 钉在冻结题集摘要上，任何能通过准入的配对都不会不同，`diff_b0_baseline` 的该分支无法构造。等价拒绝已在 `load_baseline` 的可比性检查实测（D04），题集／语料不符另有发送前拒绝（A05/A06）。
3. **真实 B0 请求、费用、调额、GO、正式基线接收与发布不在本轮**，仍按 T209 原任务书走独立授权与接收流程。
4. **H2 私有逐题证据未触碰**。E05/E06 以公开接收记录与 v0.3 配置为准，未解封任何密文。
5. **回环放行口径**已在上文单列；如后续判定要求回环也全阻，需改为在同一事件循环内复用、避免重复 `asyncio.run`。

## 复跑

从仓库根目录运行。脚本从本文件提取守卫入口 `entry.py` 与探针模块 `b0_probes.py`，在 `var/eval/t209-prep/b0-ia-<新 UUID>/` 下建独立隔离区。隔离区由脚本自身位置推导（`entry.py` 的父目录的父目录），因此新 UUID 目录名可任意，只要保持 `b0-ia-` 前缀（入口内有断言）。

```powershell
$report = 'docs/reports/OBS-EVAL/P2/T209-PREP/b0-wiring-independent.md'
$body = Get-Content -LiteralPath $report -Encoding UTF8 -Raw
$uuid = [guid]::NewGuid().ToString('N')
$area = "var/eval/t209-prep/b0-ia-$uuid"
New-Item -ItemType Directory -Path "$area/harness","$area/logs" -Force | Out-Null
$entry = [regex]::Match($body, '(?s)<!-- B0-IA-ENTRY-BEGIN -->\r?\n```python\r?\n(.*?)\r?\n```\r?\n<!-- B0-IA-ENTRY-END -->').Groups[1].Value
$probes = [regex]::Match($body, '(?s)<!-- B0-IA-PROBES-BEGIN -->\r?\n```python\r?\n(.*?)\r?\n```\r?\n<!-- B0-IA-PROBES-END -->').Groups[1].Value
if (-not $entry -or -not $probes) { throw 'Missing B0-IA harness entry' }
$utf8 = [System.Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText((Join-Path $area 'harness/entry.py'), $entry + "`n", $utf8)
[IO.File]::WriteAllText((Join-Path $area 'harness/b0_probes.py'), $probes + "`n", $utf8)
$OutputEncoding = $utf8
[Console]::OutputEncoding = $utf8
Push-Location backend
try {
    & ..\.venv\Scripts\python.exe -B -X utf8 "..\$area\harness\entry.py"
    $iaExit = $LASTEXITCODE
} finally { Pop-Location }
"B0-IA exit = $iaExit"
```

预期：pytest `114 passed, 2 skipped`，`PROBES_SUMMARY pass=57 fail=0 error=0`，`ENTRY_EXIT 0`。

## 证据路径

隔离区（git 忽略，绝对路径 `D:\GPT项目\市场部AI知识库\`）：

- 完整运行日志 `var/eval/t209-prep/b0-ia-c008628281234e84b9f19dc5af7dfb85/logs/acceptance-run.txt`
- 逐项探针记录 JSON `var/eval/t209-prep/b0-ia-c008628281234e84b9f19dc5af7dfb85/logs/probe-records.json`
- 守卫入口 `var/eval/t209-prep/b0-ia-c008628281234e84b9f19dc5af7dfb85/harness/entry.py`（SHA-256 `7e37605ee3f493dd54161eaf3a03baa0f2d5deee088a21cffe66ab1785b63086`）
- 探针模块 `var/eval/t209-prep/b0-ia-c008628281234e84b9f19dc5af7dfb85/harness/b0_probes.py`（SHA-256 `481254cfe723f0be74cc6546b064a5498c12c69b2608e4f52e9b9db0618a3f5b`）
- 合成运行件／审批记录／归档／恢复区／候选归档：`…/probes/{runs,admit,receipts,registry,archive,restored,candidates,links,occupied,configs,inputs,plans}`

脚本全文附于下，摘要即上文两条 SHA-256；两者与隔离区文件一致。

<details>
<summary>守卫入口 entry.py</summary>

<!-- B0-IA-ENTRY-BEGIN -->
```python
"""T209 正式 B0 接线独立验收 · 受守卫入口。

复用 R02 独立报告的九类守卫与 pytest 调用形态，截取至 ``from dataclasses import replace`` 前；
临时目录前缀改为 ``b0-ia-``，并按本任务书允许清单扩充公开输入。

运行方式（仓库 backend 目录）：
    ..\\.venv\\Scripts\\python.exe -B -X utf8 <本文件>
"""

import json
import os
import platform
import socket
import sqlite3
import sys
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
area = HERE.parent
repo = Path.cwd().parent
assert area.name.startswith("b0-ia-"), area
assert (repo / "backend" / "src" / "mktkb").is_dir(), repo

keep_env = {
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
}
stripped_env = sorted(key for key in os.environ if key.upper() not in keep_env
                      and ("KEY" in key.upper() or "TOKEN" in key.upper()
                           or "SECRET" in key.upper() or key.upper().startswith("MKTKB_")))
for key in list(os.environ):
    if key.upper() not in keep_env:
        del os.environ[key]
os.environ.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
                  TEMP=str(area), TMP=str(area))


def normalize(path):
    return os.path.normcase(os.path.abspath(os.fsdecode(path))).removeprefix("\\\\?\\")


def under(path, root):
    return path == root or path.startswith(root + os.sep)


temp = normalize(area)
roots = tuple(map(normalize, (area, repo / ".venv", Path(sys.base_prefix),
    repo / "backend" / "src", repo / "backend" / "tests")))

# 本任务书允许清单：v0.3 正式配置与历史模板、B0 题集、公开文档名映射、
# R1 入库配方及其 12 份公开源文件、B0 草案、T207 公开接收记录。
B0_SOURCES = (
    "fixtures/acceptance/variants/V03_物品位置表_历史V1.xlsx",
    "fixtures/acceptance/normal/D01_物品位置表.xlsx",
    "fixtures/acceptance/variants/V04_物品位置表_新版V3.xlsx",
    "fixtures/acceptance/normal/D02_合作店家信息.xlsx",
    "fixtures/acceptance/normal/D03_市场部工作指南.docx",
    "fixtures/acceptance/normal/D04_活动策划流程.docx",
    "fixtures/acceptance/normal/D05_物料领用规范.pdf",
    "fixtures/acceptance/normal/D06_店家资料维护说明.pdf",
    "fixtures/acceptance/normal/D07_活动申请扫描件.pdf",
    "fixtures/acceptance/normal/D08_仓库安全须知扫描件.pdf",
    "fixtures/acceptance/normal/D09_物料领用通知.png",
    "fixtures/acceptance/normal/D10_盘点通知.jpg",
)
PUBLIC_INPUTS = (
    "backend/pyproject.toml",
    "docs/evaluation/gate_v0_1.json",
    "docs/evaluation/gate_v0_2.json",
    "docs/evaluation/gate_v0_3.json",
    "docs/evaluation/gate_v0_3_approved.json",
    "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-R1.json",
    "docs/reports/OBS-EVAL/P2/T207/cases/document-codes.json",
    "docs/reports/OBS-EVAL/P2/T209-PREP/b0-inputs.draft.json",
    "docs/reports/OBS-EVAL/P2/T209-PREP/b0-request-plan.draft.json",
    "docs/reports/OBS-EVAL/P2/T207-RETEST-20261119/manager-receipt.md",
    "fixtures/evaluation/b0.jsonl",
) + B0_SOURCES

for rel in PUBLIC_INPUTS:
    assert (repo / rel).is_file(), f"allowlist input missing: {rel}"
for rel in B0_SOURCES:
    assert Path(rel).parent.as_posix().startswith("fixtures/acceptance"), rel

public_files = set(map(normalize, (repo / rel for rel in PUBLIC_INPUTS)))
# 刻意不存在的相对路径：test_p2_b0.py 用它断言 ``gate_config_unreadable``。
ABSENT_FIXTURES = {"backend/missing-approved-config.json"}
for rel in ABSENT_FIXTURES:
    assert not (repo / rel).exists(), f"absent fixture unexpectedly exists: {rel}"
public_files |= set(map(normalize, (repo / rel for rel in ABSENT_FIXTURES)))
hits = Counter()
loopback = Counter()
self_hits = Counter()
details = []
calibration = True


def is_loopback(address):
    """asyncio 在 Windows 上用 127.0.0.1 自建 self-pipe；只放行数字回环。"""
    if isinstance(address, tuple) and address:
        host = address[0]
        return isinstance(host, str) and (host == "::1" or host.startswith("127."))
    return False


def blocked(category, info):
    if calibration:
        self_hits[category] += 1
    else:
        hits[category] += 1
        stack = []
        frame = sys._getframe(1)
        while frame and len(stack) < 9:
            stack.append((Path(frame.f_code.co_filename).name, frame.f_code.co_name))
            frame = frame.f_back
        details.append((category, info, stack))
    raise PermissionError("B0-IA guard: " + category)


def check_path(raw, write=False, sqlite=False):
    if raw is None or isinstance(raw, int) or raw == ":memory:":
        return
    if os.fsdecode(raw).upper() == os.devnull.upper():
        return
    if sqlite and os.fsdecode(raw).startswith("file:"):
        uri = urlsplit(os.fsdecode(raw))
        if uri.netloc or uri.fragment or uri.query != "mode=ro":
            blocked("write_outside", "unexpected sqlite URI")
        raw = unquote(uri.path)
        if os.name == "nt" and raw[0:1] == "/" and raw[2:3] == ":":
            raw = raw[1:]
    path = normalize(raw)
    name = os.path.basename(path)
    parts = Path(path).parts
    if name == ".env" or name.startswith(".env.") or "credential" in name or (
        name in {"secrets.toml", "secrets.json"} or name.endswith((".key", ".pem", ".pfx"))
    ):
        blocked("credential", name)
    if "ledger" in name or name == "budget.json":
        blocked("ledger_budget", name)
    if name.startswith("go.") or "-go." in name or "_go." in name:
        blocked("go", name)
    if not under(path, temp) and (
        name.endswith((".enc", ".sealed", ".age")) or any(
            "private" in part or "sealed" in part or part in {"h2", "h2v3", "holdout"}
            for part in parts
        )
    ):
        blocked("private_h2", name)
    if not under(path, temp) and (write or sqlite):
        blocked("write_outside", (name, path if str(raw).lower().endswith("nul") else ""))
    if not under(path, temp) and any(
        part in {".ssh", ".aws", ".codex", ".agents"} for part in parts
    ):
        blocked("credential", name)
    if path not in public_files and not any(under(path, root) for root in roots):
        blocked("read_outside", name)


def audit(event, args):
    if event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex",
                 "socket.gethostbyaddr", "socket.getnameinfo"}:
        blocked("dns", event)
    if event in {"socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg"}:
        address = args[1] if len(args) > 1 else None
        if is_loopback(address):
            loopback[f"{event}->{address[0]}"] += 1
        else:
            blocked("socket", event)
    if event in {"subprocess.Popen", "_winapi.CreateProcess", "os.system", "os.exec",
                 "os.spawn", "os.startfile", "os.startfile/2", "os.posix_spawn", "os.fork"}:
        blocked("child_process", event)
    if event == "open":
        flags = args[2]
        write = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        check_path(args[0], write=write)
    if event == "sqlite3.connect":
        check_path(args[0], sqlite=True)
    if event in {"os.remove", "os.rmdir", "os.chmod", "os.mkdir", "os.utime", "os.truncate"}:
        check_path(args[0], write=True)
    if event in {"os.rename", "os.link", "os.symlink"}:
        check_path(args[0], write=True)
        check_path(args[1], write=True)


sys.addaudithook(audit)
if os.name == "nt":
    def no_os_version_command(system="", release="", version="", **_unused):
        return system, release, version
    platform._syscmd_ver = no_os_version_command

checks = {
    "credential": lambda: open(repo / ".env.guard-probe"),
    "ledger_budget": lambda: open(repo / "var" / "guard-probe-ledger.jsonl"),
    "go": lambda: open(repo / "var" / "guard-probe-go.json"),
    "private_h2": lambda: open(repo / "var" / "private" / "guard-probe-h2.sealed"),
    "write_outside": lambda: open(repo / "backend" / "guard-probe-write", "w"),
    "read_outside": lambda: open(repo / "guard-probe-unlisted"),
    "child_process": lambda: sys.audit("subprocess.Popen", None, None, None, None),
    "dns": lambda: socket.getaddrinfo("b0-ia-guard.invalid", 443),
}
with socket.socket() as probe:
    checks["socket"] = lambda: probe.connect(("192.0.2.1", 443))
    for category, attempt in checks.items():
        try:
            attempt()
        except PermissionError as exc:
            assert str(exc) == "B0-IA guard: " + category
        else:
            raise AssertionError(category)
assert self_hits == Counter({category: 1 for category in checks})
calibration = False
print("ISOLATED_RUN", area, flush=True)
print("GUARD_CALIBRATION", dict(self_hits), flush=True)
print("STRIPPED_ENV_CREDENTIAL_KEYS", stripped_env, flush=True)

sys.path.insert(0, str(repo / "backend" / "src"))
assert "mktkb.evaluation.p2_b0" not in sys.modules
import mktkb.evaluation.p2_b0 as isolated_import

assert isolated_import.B0_CASES_SHA256 == (
    "bd4f0f7ccc6e9f50ba630598c01b3519804447d4e0f3bfbc2facd54a5a521e4f")
print("FRESH_B0_IMPORT", isolated_import.B0_GATE_CONFIG_HASH,
      "guard_hits", sum(hits.values()), details, flush=True)

import pytest

subprocess_tests = {
    "test_verify_rejects_reparse_point",
    "test_import_and_report_path_make_zero_external_attempts",
}


class OfflineOnly:
    def pytest_collection_modifyitems(self, items):
        for item in items:
            if item.name in subprocess_tests:
                item.add_marker(pytest.mark.skip(
                    reason="B0-IA process guard blocks required subprocess"))


files = [
    "test_p2_b0.py", "test_p2_gate.py", "test_diff_release_gate.py",
    "test_baseline_portability.py", "test_p2_candidate_report.py",
]
code = pytest.main(
    ["-q", "-rs", "--tb=short", "-p", "no:cacheprovider", "-p", "no:logging",
     "--basetemp", str(area / "pytest")] + ["tests/evaluation/" + filename for filename in files],
    plugins=[OfflineOnly()],
)
print("PYTEST_EXIT", int(code), flush=True)
print("GUARD_OPERATIONAL", dict(hits), "loopback", dict(loopback), "detail", details, flush=True)

sys.path.insert(0, str(HERE))
import b0_probes  # noqa: E402

probe_exit = b0_probes.main(repo, area)
print("PROBE_EXIT", int(probe_exit), flush=True)
print("GUARD_FINAL", dict(hits), "loopback", dict(loopback), "detail", details, flush=True)

if code or hits or probe_exit:
    raise SystemExit(int(code or (86 if hits else probe_exit)))
```
<!-- B0-IA-ENTRY-END -->

</details>

<details>
<summary>探针模块 b0_probes.py</summary>

<!-- B0-IA-PROBES-BEGIN -->
```python
"""T209 正式 B0 接线独立验收探针（全部合成输入，在进程内守卫下运行）。

只在隔离目录内构造合成公开 B0 run / 合成 trace / 合成审批记录；
不读真实凭据、预算、账本、GO、正式基线与私有 H2。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import sys
import traceback
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

RECORDS: list[dict] = []


# --------------------------------------------------------------------------- #
# 记录 / 断言
# --------------------------------------------------------------------------- #


def record(pid: str, title: str, verdict: str, *, entry: str, expected: str,
           actual: str, code: str = "", note: str = "", side_effect: str = "") -> None:
    RECORDS.append({
        "id": pid, "title": title, "verdict": verdict, "entry": entry,
        "expected": expected, "actual": actual, "code": code, "note": note,
        "side_effect": side_effect,
    })
    print(f"[{verdict}] {pid} {title} :: expected={expected} actual={actual}"
          + (f" code={code}" if code else ""), flush=True)


def _code_of(exc: BaseException) -> str:
    for name in ("reason", "code"):
        value = getattr(exc, name, None)
        if isinstance(value, str) and value:
            return value
    text = str(exc)
    return text.split(":", 1)[0].strip()


def expect_code(pid: str, title: str, code: str, fn, *, entry: str, note: str = "",
                side_effect: str = "") -> None:
    try:
        value = fn()
    except ValueError as exc:
        got = _code_of(exc)
        record(pid, title, "PASS" if got == code else "FAIL", entry=entry,
               expected=code, actual=got or type(exc).__name__, code=got, note=note,
               side_effect=side_effect)
        return
    except Exception as exc:  # noqa: BLE001
        record(pid, title, "ERROR", entry=entry, expected=code,
               actual=f"{type(exc).__name__}: {exc}", note=note, side_effect=side_effect)
        return
    record(pid, title, "FAIL", entry=entry, expected=code,
           actual=f"no error, returned {type(value).__name__}", note=note,
           side_effect=side_effect)


def expect_raises(pid: str, title: str, exc_type: type, needle: str, fn, *,
                  entry: str, note: str = "", side_effect: str = "") -> None:
    try:
        value = fn()
    except exc_type as exc:
        ok = needle in str(exc)
        record(pid, title, "PASS" if ok else "FAIL", entry=entry,
               expected=f"{exc_type.__name__}({needle})", actual=f"{type(exc).__name__}: {exc}",
               note=note, side_effect=side_effect)
        return
    except Exception as exc:  # noqa: BLE001
        record(pid, title, "FAIL", entry=entry, expected=f"{exc_type.__name__}({needle})",
               actual=f"{type(exc).__name__}: {exc}", note=note, side_effect=side_effect)
        return
    record(pid, title, "FAIL", entry=entry, expected=f"{exc_type.__name__}({needle})",
           actual=f"no error, returned {type(value).__name__}", note=note,
           side_effect=side_effect)


def expect_true(pid: str, title: str, condition: bool, *, entry: str, expected: str,
                actual: str, note: str = "", side_effect: str = "") -> None:
    record(pid, title, "PASS" if condition else "FAIL", entry=entry, expected=expected,
           actual=actual, note=note, side_effect=side_effect)


# --------------------------------------------------------------------------- #
# 合成 B0 run（复用项目原生序列化器 + 真实结构临时 SQLite trace，零真实发送）
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def pipeline_patch(digest: str | None):
    if digest is None:
        yield
        return
    from mktkb.evaluation import p2_b0

    original = p2_b0.pipeline_source_sha256
    p2_b0.pipeline_source_sha256 = lambda: digest
    try:
        yield
    finally:
        p2_b0.pipeline_source_sha256 = original


def b0_inputs(repo: Path) -> tuple[Path, Path]:
    return (repo / "docs/evaluation/gate_v0_3_approved.json",
            repo / "docs/reports/OBS-EVAL/P2/T209-PREP/b0-request-plan.draft.json")


def build_b0_run(dest: Path, run_id: str, repo: Path, *, wrong: tuple[str, ...] = (),
                 pipeline_digest: str | None = None) -> Path:
    """按开发 fixture 的字段结构，用原生序列化器写一份完整公开 B0 运行件。"""
    from mktkb.evaluation.dataset import dataset_version
    from mktkb.evaluation.p2_b0 import (
        B0_BUSINESS_DATE, B0_CASES_SHA256, B0_LABEL_VERSION, build_b0_plan_binding,
        frozen_b0_cases, frozen_b0_corpus, load_approved_b0_config, sha256,
    )
    from mktkb.evaluation.p2_contracts import (
        P2_AUTHORIZATION_SCHEMA_VERSION, P2Authorization, P2RunPlan,
    )
    from mktkb.evaluation.p2_runner import (
        P2RunLedger, _attempt_audit, _binding_state, _write_artifacts,
    )
    from mktkb.evaluation.product_adapter import IngestReceipt, P2RunDataset, ProductPaths
    from mktkb.observability.contracts import SpanRecord, TraceRecord, required_spans
    from mktkb.observability.store import TraceRepository
    from mktkb.observability.versioning import pipeline_version

    approved, draft = b0_inputs(repo)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    paths = ProductPaths.of(dest / "app")
    paths.run_dir.mkdir(parents=True)
    config = load_approved_b0_config(approved)
    plan_document = json.loads(draft.read_text(encoding="utf-8"))
    with pipeline_patch(pipeline_digest):
        plan = P2RunPlan.from_dict({
            **plan_document, "b0_binding": build_b0_plan_binding(run_id),
        })
    cases = frozen_b0_cases()
    dataset = P2RunDataset("public", cases, {
        "dataset_version": dataset_version(cases, B0_LABEL_VERSION),
        "label_version": B0_LABEL_VERSION, "manifest_sha256": B0_CASES_SHA256,
        "suite": "b0", "case_count": len(cases),
    })
    corpus = frozen_b0_corpus()
    slots = {source["name"]: f"doc-{i:02d}" for i, source in enumerate(corpus, 1)}
    ingest = [
        IngestReceipt(source["upload_name"], source["sha256"], slots[source["name"]],
                      f"version-{index:02d}", "succeeded", source["publish"], index, 202,
                      200 if source["publish"] else None)
        for index, source in enumerate(corpus, 1)
    ]
    active: dict[str, tuple[str, str, int]] = {}
    version_counts: dict[str, int] = {}
    for item, receipt in zip(corpus, ingest, strict=True):
        name = item["name"]
        version_counts[name] = version_counts.get(name, 0) + 1
        if receipt.published:
            active[name] = (receipt.document_id, receipt.version_id, version_counts[name])
    adapter = SimpleNamespace(
        paths=paths, ingest_receipts=ingest, trace_enabled=True, trace_content_mode="hash",
        trace_identity_bound=True, rag_business_date=B0_BUSINESS_DATE,
        index_status=lambda: {"provider_mode": "live"},
        binding_components=lambda: {
            "pipeline_version": pipeline_version(), "index_revision": 11,
            "provider": {"chat": {"provider": "deepseek", "model": "deepseek-flash"}},
        },
    )
    binding = _binding_state(adapter, dataset, run_id, config)
    now = datetime.now(timezone.utc)
    authorization = P2Authorization(
        P2_AUTHORIZATION_SCHEMA_VERSION, plan.stage, plan.plan_id, plan.plan_sha256,
        "synthetic-go-reference", "a" * 64, 20, "synthetic-owner",
        now - timedelta(minutes=1), now + timedelta(minutes=40),
        "synthetic-ledger-reference", "b" * 64, "c" * 64,
        plan.stage_limit_cny, plan.stage_limit_cny,
        dict(plan.cost_centers_cny), dict(plan.cost_centers_cny),
        "unlimited", 0, "unlimited", 1.0, plan.operations, True,
    )
    ledger = P2RunLedger(run_id, plan.plan_id, plan.plan_sha256, "live", True,
                         plan.total_requests)
    ledger.reserved = ledger.settled_success = 40
    ledger.by_operation = {"answer": 40}
    codes = {name[:3]: name for name in slots}
    paths.trace_db.parent.mkdir(parents=True)
    with TraceRepository(paths.trace_db) as traces:
        for case in cases:
            key = case.case_id
            item = next(i for i in plan.items if i.operation == "answer" and i.case_id == key)
            trace_id = f"trace-{key}"
            ref = case.expected_sources[0]
            locator = dict(ref.get("locator") or {"page": 1})
            unit = f"unit-{key}"
            doc_name = codes[ref["doc_code"]]
            doc_id, version_id, version_number = active[doc_name]
            source = {"source_id": unit, "document_name": doc_name, "locator": locator}
            proof = {
                "unit_id": unit, "unit_key": ref.get("unit_key"), "locator": locator,
                "verified": True, "document_id": doc_id, "version_id": version_id,
                "version_number": version_number, "state": "published", "active": True,
                "in_run": True,
            }
            text = "（合成变异答案，非参考答）" if key in wrong else case.reference_answer
            product = {
                "trace_id": trace_id, "trace_status": "ok", "trace_path": "legacy",
                "replayed": False, "http_status": 200, "kind": "answer", "text": text,
                "question_sha256": sha256(case.question.encode("utf-8")),
                "client_request_id": f"request-{key}", "sources": [source],
                "retrieved": [{"unit_ids": [unit], "document_name": doc_name}],
                "evidence": [proof],
            }
            ticket = {
                "plan_sha256": plan.plan_sha256, "plan_id": plan.plan_id, "case_id": key,
                "turn": 1, "reservation_id": f"reservation-{key}", "operation": "answer",
                "nonce_len": 20, "item_id": item.item_id,
                "provider": item.price_profile.provider, "model": item.price_profile.model,
            }
            turn = {
                "turn": 1, "status": "ok", "error_code": None, "ticket": ticket,
                "product": product, "trace_id": trace_id, "item_id": item.item_id,
                "kind": "answer", "trace_path": "legacy",
            }
            ledger.cases.append({
                "schema_version": "p2-run-case/v0.1", "run_id": run_id, "case_id": key,
                "suite": "b0", "stratum": case.stratum, "visibility": "public",
                "conversation_id": f"conv-{key}", "status": "ok", "error_code": None,
                "planned_turns": 1, "turns_executed": 1, "turns": [turn],
            })
            ledger.requests.append({
                "schema_version": "p2-run-request/v0.1", "run_id": run_id, "case_id": key,
                "status": "ok", "execution": "live", "turn": 1, "item_id": item.item_id,
                "ticket": ticket, "client_request_id": product["client_request_id"],
                "provider_calls": {"outbound": 1},
                "product": {"trace_id": trace_id,
                            "question_sha256": product["question_sha256"]},
            })
            traces.write(TraceRecord(
                trace_id=trace_id, case_id=key, mode="local", scope="end_to_end",
                path="legacy", outcome_kind="answer",
                dataset_version=binding["dataset_version"], run_id=run_id,
                index_revision=str(binding["index_revision"]),
                manifest_sha256=binding["manifest_sha256"],
                pipeline_version=binding["pipeline_version"],
                config_hash=binding["config_hash"], status="ok",
            ), [SpanRecord(span_id=f"{trace_id}-{name}", trace_id=trace_id, name=name,
                           status="ok")
                for name in required_spans("legacy", "answer")])
    receipts = []
    for item in plan.items:
        if item.operation in {"index_embedding", "ocr"}:
            for phase, status in (("reserve", "reserved"), ("settle", "succeeded")):
                receipts.append({
                    "item_id": item.item_id, "operation": item.operation,
                    "case_id": item.case_id, "turn": item.turn, "page": item.page,
                    "phase": phase, "status": status,
                    "reservation_id": f"reservation-{item.item_id}",
                    "provider": item.price_profile.provider, "model": item.price_profile.model,
                    "cost_center": item.cost_center, "kind": item.price_profile.kind,
                    "charged_cny": 0.0,
                })
    adapter.attempt_receipts = lambda: receipts
    audit, error = _attempt_audit(plan, adapter, ledger)
    assert error is None, error
    audit["gate_reserved"] = audit["expected_reservations"]
    result = ledger.result(status="succeeded", attempt_audit=audit)
    counts = {"chat": 40, "embedding": 1, "rerank": 0, "ocr": 12}
    calls = sum(counts.values())
    network = {
        "transport_outbound": counts, "mock_intercepted": 0, "outbound_attempts": calls,
        "chat_outbound_attempts": 40, "rag_provider_posts": 1, "ocr_outbound_attempts": 12,
    }
    providers: dict[str, dict] = {
        name: {"outbound_network": count} for name, count in counts.items()
    }
    providers.update(outbound_network=calls, network=network,
                     live={"run_id": run_id, "mode": "live"})
    checks = [{"name": name, "ok": True, "detail": ""} for name in (
        "plan_identity", "stage", "not_expired", "not_before_issue", "operations",
        "request_cap", "production_ready", "live_gate",
    )]
    _write_artifacts(
        plan=plan, adapter=adapter, authorization=authorization, dataset=dataset,
        ledger=ledger, result=result, execution="live", checks=checks, planned_turns=40,
        executed_turns=40, duration_ms=1, started_utc=now.isoformat(), binding=binding,
        providers=providers, network=(calls, network), attempt_audit=audit,
        gate_config=config, b0_corpus=corpus,
    )
    return paths.run_dir


def cli_call(argv: list[str]) -> tuple[int, str, str]:
    from mktkb.evaluation import cli

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def admit_cli(run_dir: Path, approved: Path, out_path: Path | None = None
              ) -> tuple[int, str, str]:
    argv = ["baseline", "p2-admit", "--run", str(run_dir), "--gate-config", str(approved)]
    if out_path is not None:
        argv += ["--out", str(out_path)]
    return cli_call(argv)


def admit_api(run_dir: Path, approved: Path):
    from mktkb.evaluation.p2_b0 import check_b0_admission, load_approved_b0_config

    return check_b0_admission(run_dir, load_approved_b0_config(approved))


def cli_json(stdout: str) -> dict:
    start = stdout.find("{")
    if start < 0:
        raise AssertionError(f"no JSON payload in stdout: {stdout[:400]!r}")
    payload, _end = json.JSONDecoder().raw_decode(stdout[start:])
    return payload


def cli_error_code(stdout: str, stderr: str) -> str:
    for text in (stdout, stderr):
        for line in text.splitlines():
            if line.startswith("ERROR: "):
                body = line[len("ERROR: "):].strip()
                head, sep, tail = body.partition(": ")
                if sep and head.endswith(("Error", "Exception")):
                    body = tail
                return body.split(":", 1)[0].strip()
    try:
        payload = cli_json(stdout)
    except AssertionError:
        return ""
    return str(payload.get("error_code") or "")


# --------------------------------------------------------------------------- #
# 合成输入
# --------------------------------------------------------------------------- #


def load_b0_dataset_and_ingest(repo: Path):
    from mktkb.evaluation.p2_b0 import (
        B0_CASES_SHA256, B0_LABEL_VERSION, frozen_b0_cases,
    )
    from mktkb.evaluation.dataset import dataset_version
    from mktkb.evaluation.product_adapter import P2RunDataset, ingest_plan_from_document

    recipe_path = repo / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-R1.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    for source in recipe["sources"]:
        source["path"] = str(repo / source["path"])
    ingest = ingest_plan_from_document(recipe)
    cases = frozen_b0_cases()
    dataset = P2RunDataset("public", cases, {
        "dataset_version": dataset_version(cases, B0_LABEL_VERSION),
        "label_version": B0_LABEL_VERSION, "manifest_sha256": B0_CASES_SHA256,
        "suite": "b0", "case_count": len(cases),
    })
    return dataset, ingest, recipe


def load_b0_plan(repo: Path, run_id: str, *, digest: str | None = None):
    from mktkb.evaluation.p2_b0 import build_b0_plan_binding
    from mktkb.evaluation.p2_contracts import P2RunPlan

    _, draft = b0_inputs(repo)
    document = json.loads(draft.read_text(encoding="utf-8"))
    with pipeline_patch(digest):
        return P2RunPlan.from_dict({
            **document, "b0_binding": build_b0_plan_binding(run_id),
        })


def run_live_api(plan, *, run_id: str, out_dir: Path, dataset, ingest, gate_config
                 ) -> tuple[list, BaseException | None]:
    """调用真实 run_live_p2，但把真实门替换为注入的停止点（不发任何请求）。"""
    from mktkb.evaluation import p2_live
    from mktkb.evaluation.p2_authorization import P2AuthorizationError

    calls: list[str] = []
    original_env = p2_live.load_live_env
    original_gate = p2_live.open_live_gate

    def gate_guard(plan_, *, run_id, now):  # noqa: ANN001
        calls.append(str(run_id))
        raise P2AuthorizationError("synthetic_gate_guard", "the real send gate is disabled")

    p2_live.load_live_env = lambda *args, **kwargs: object()
    p2_live.open_live_gate = gate_guard
    error: BaseException | None = None
    try:
        asyncio.run(p2_live.run_live_p2(
            plan, run_id=run_id, out_dir=out_dir, dataset=dataset,
            ingest_plan=ingest, gate_config=gate_config,
        ))
    except BaseException as exc:  # noqa: BLE001
        error = exc
    finally:
        p2_live.load_live_env = original_env
        p2_live.open_live_gate = original_gate
    return calls, error


def cli_live(argv: list[str]) -> tuple[int, str, str]:
    """CLI live 入口，同样把真实门替换为注入停止点。"""
    from mktkb.evaluation import p2_live
    from mktkb.evaluation.p2_authorization import P2AuthorizationError

    original_env = p2_live.load_live_env
    original_gate = p2_live.open_live_gate

    def gate_guard(plan_, *, run_id, now):  # noqa: ANN001
        raise P2AuthorizationError("synthetic_gate_guard", "the real send gate is disabled")

    p2_live.load_live_env = lambda *args, **kwargs: object()
    p2_live.open_live_gate = gate_guard
    try:
        return cli_call(argv)
    finally:
        p2_live.load_live_env = original_env
        p2_live.open_live_gate = original_gate


def p2run_argv(repo: Path, plan_path: Path, out_dir: Path, approved: Path,
               run_id: str, ingest_path: Path) -> list[str]:
    return [
        "p2-run", "--mode", "live", "--run-id", run_id, "--plan", str(plan_path),
        "--gate-config", str(approved),
        "--cases", str(repo / "fixtures/evaluation/b0.jsonl"),
        "--ingest-plan", str(ingest_path),
        "--out", str(out_dir),
    ]


# --------------------------------------------------------------------------- #
# A. 发送前绑定
# --------------------------------------------------------------------------- #


def probe_A(out: Path, repo: Path, approved: Path) -> None:
    from mktkb.evaluation.p2_b0 import (
        B0_CASES_PATH, build_b0_plan_binding, load_approved_b0_config,
        validate_b0_live_inputs,
    )
    from mktkb.evaluation.p2_contracts import P2RunPlan

    dataset, ingest, recipe = load_b0_dataset_and_ingest(repo)
    _, draft = b0_inputs(repo)
    draft_document = json.loads(draft.read_text(encoding="utf-8"))
    ingest_path = out / "inputs" / "ingest-abs.json"
    ingest_path.parent.mkdir(parents=True, exist_ok=True)
    ingest_path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")

    # A01：CLI 合法合成计划抵达注入停止点
    run_id = "synthetic-b0-a01"
    plan_path = out / "plans" / "a01.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps({
        **draft_document, "b0_binding": build_b0_plan_binding(run_id),
    }, ensure_ascii=False), encoding="utf-8")
    target = out / "runs" / "a01"
    code, stdout, stderr = cli_live(
        p2run_argv(repo, plan_path, target, approved, run_id, ingest_path))
    expect_true(
        "A01", "CLI 合法绑定抵达注入停止点",
        code == 3 and "synthetic_gate_guard" in (stdout + stderr) and not target.exists(),
        entry="cli p2-run --mode live", expected="exit 3 + synthetic_gate_guard + 无输出目录",
        actual=f"exit={code} payload={stdout.strip()[:200]}", note="真实门被注入函数替换，未读 GO/预算/账本",
        side_effect=f"{target} exists={target.exists()}",
    )

    # A02：run_live_p2 API 同样抵达停止点
    run_id = "synthetic-b0-a02"
    plan = load_b0_plan(repo, run_id)
    config = load_approved_b0_config(approved)
    target = out / "runs" / "a02"
    calls, error = run_live_api(plan, run_id=run_id, out_dir=target, dataset=dataset,
                                ingest=ingest, gate_config=config)
    expect_true(
        "A02", "run_live_p2 API 合法绑定抵达注入停止点",
        isinstance(error, Exception) and _code_of(error) == "synthetic_gate_guard"
        and calls == [run_id] and not target.exists(),
        entry="api p2_live.run_live_p2", expected="synthetic_gate_guard + 1 次门调用 + 无输出目录",
        actual=f"{type(error).__name__}: {error}; gate_calls={calls}",
        side_effect=f"{target} exists={target.exists()}",
    )

    # A03：错 run ID
    run_id = "synthetic-b0-a03"
    wrong_plan = load_b0_plan(repo, "synthetic-b0-other")
    target = out / "runs" / "a03"
    calls, error = run_live_api(wrong_plan, run_id=run_id, out_dir=target, dataset=dataset,
                                ingest=ingest, gate_config=config)
    expect_true(
        "A03", "错 run ID 在发送前拒绝",
        _code_of(error) == "b0_plan_binding_mismatch" and not calls and not target.exists(),
        entry="api p2_live.run_live_p2", expected="b0_plan_binding_mismatch 且门调用 0 且无输出目录",
        actual=f"{_code_of(error)}; gate_calls={calls}", side_effect=f"{target} exists={target.exists()}",
    )

    # A04：错流水线摘要
    run_id = "synthetic-b0-a04"
    bad_plan = load_b0_plan(repo, run_id, digest="d" * 64)
    target = out / "runs" / "a04"
    calls, error = run_live_api(bad_plan, run_id=run_id, out_dir=target, dataset=dataset,
                                ingest=ingest, gate_config=config)
    expect_true(
        "A04", "错流水线摘要（旧/改源码）在发送前拒绝",
        _code_of(error) == "b0_plan_binding_mismatch" and not calls and not target.exists(),
        entry="api p2_live.run_live_p2", expected="b0_plan_binding_mismatch 且门调用 0",
        actual=f"{_code_of(error)}; gate_calls={calls}", side_effect=f"{target} exists={target.exists()}",
    )

    # A05：题集被改
    run_id = "synthetic-b0-a05"
    plan = load_b0_plan(repo, run_id)
    mutated_cases = list(dataset.cases)
    mutated_cases[0] = replace(mutated_cases[0], question=mutated_cases[0].question + "？")
    mutated_dataset = replace(dataset, cases=tuple(mutated_cases))
    target = out / "runs" / "a05"
    calls, error = run_live_api(plan, run_id=run_id, out_dir=target, dataset=mutated_dataset,
                                ingest=ingest, gate_config=config)
    expect_true(
        "A05", "题集不符在发送前拒绝",
        _code_of(error) == "b0_input_cases_not_frozen" and not calls and not target.exists(),
        entry="api p2_live.run_live_p2", expected="b0_input_cases_not_frozen",
        actual=f"{_code_of(error)}", side_effect=f"{target} exists={target.exists()}",
    )

    # A06：语料被改
    from mktkb.evaluation.product_adapter import P2IngestPlan

    run_id = "synthetic-b0-a06"
    plan = load_b0_plan(repo, run_id)
    mutated_sources = list(ingest.sources)
    mutated_sources[0] = replace(mutated_sources[0], publish=False)
    mutated_ingest = P2IngestPlan(sources=tuple(mutated_sources), label=ingest.label)
    target = out / "runs" / "a06"
    calls, error = run_live_api(plan, run_id=run_id, out_dir=target, dataset=dataset,
                                ingest=mutated_ingest, gate_config=config)
    expect_true(
        "A06", "语料不符在发送前拒绝",
        _code_of(error) == "b0_corpus_mismatch" and not calls and not target.exists(),
        entry="api p2_live.run_live_p2", expected="b0_corpus_mismatch",
        actual=f"{_code_of(error)}", side_effect=f"{target} exists={target.exists()}",
    )

    # A07：旧 v0.3（未审批）配置
    run_id = "synthetic-b0-a07"
    plan_path = out / "plans" / "a07.json"
    plan_path.write_text(json.dumps({
        **draft_document, "b0_binding": build_b0_plan_binding(run_id),
    }, ensure_ascii=False), encoding="utf-8")
    target = out / "runs" / "a07"
    old_config = repo / "docs/evaluation/gate_v0_3.json"
    argv = p2run_argv(repo, plan_path, target, old_config, run_id, ingest_path)
    code, stdout, stderr = cli_live(argv)
    expect_true(
        "A07", "旧/未审批 v0.3 配置在环境与 GO 之前拒绝",
        code == 3 and cli_error_code(stdout, stderr) == "b0_gate_config_not_approved"
        and not target.exists(),
        entry="cli p2-run --gate-config gate_v0_3.json",
        expected="exit 3 + b0_gate_config_not_approved + 无输出目录",
        actual=f"exit={code} code={cli_error_code(stdout, stderr)}",
        side_effect=f"{target} exists={target.exists()}",
    )

    # A08：被篡改的已审批配置（同 gate 版本、内容变化）
    tampered = out / "configs" / "gate_v0_3_approved_changed.json"
    tampered.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(approved.read_text(encoding="utf-8"))
    payload["notes"] = "synthetic changed config"
    tampered.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    run_id = "synthetic-b0-a08"
    plan_path = out / "plans" / "a08.json"
    plan_path.write_text(json.dumps({
        **draft_document, "b0_binding": build_b0_plan_binding(run_id),
    }, ensure_ascii=False), encoding="utf-8")
    target = out / "runs" / "a08"
    code, stdout, stderr = cli_live(p2run_argv(repo, plan_path, target, tampered, run_id, ingest_path))
    expect_true(
        "A08", "被篡改的已审批配置在发送前拒绝",
        code == 3 and cli_error_code(stdout, stderr) == "b0_gate_file_not_approved"
        and not target.exists(),
        entry="cli p2-run --gate-config <changed bytes>",
        expected="exit 3 + b0_gate_file_not_approved",
        actual=f"exit={code} code={cli_error_code(stdout, stderr)}",
        side_effect=f"{target} exists={target.exists()}",
    )

    # A09：旧计划无正式绑定的兼容性
    run_id = "synthetic-b0-a09"
    legacy_plan = P2RunPlan.from_dict(draft_document)
    legacy_hash = legacy_plan.plan_sha256
    target = out / "runs" / "a09"
    legacy_path = out / "plans" / "a09-legacy.json"
    legacy_path.write_text(json.dumps(draft_document, ensure_ascii=False), encoding="utf-8")
    code, stdout, stderr = cli_live(p2run_argv(repo, legacy_path, target, old_config, run_id,
                                               ingest_path))
    reported = cli_error_code(stdout, stderr)
    expect_true(
        "A09", "旧计划无正式绑定仍兼容（不被强制进入 B0 分支）",
        legacy_hash == "4362968a16a8ca4624396d808e5ffbefcb916dbbf369cf4e43a31abef2651e1f"
        and not reported.startswith("b0_")
        and reported == "synthetic_gate_guard",
        entry="cli p2-run（无 b0_binding）+ 未审批配置",
        expected="plan_sha256 不变、无 b0_* 拒绝、直达注入发送门",
        actual=f"plan_sha256={legacy_hash} code={reported} exit={code}",
        side_effect=f"{target} exists={target.exists()}",
        note="注入的 load_live_env 使既有 live_env_missing 分支不触发；"
             "A09b 单独实测真实 load_live_env 的拒绝码",
    )
    from mktkb.evaluation import p2_live as p2_live_module

    env_error = None
    try:
        p2_live_module.load_live_env()
    except ValueError as exc:
        env_error = exc
    expect_true(
        "A09b", "未注入时真实 load_live_env 在环境边界拒绝（凭据为零）",
        env_error is not None and _code_of(env_error) == "live_env_missing",
        entry="api p2_live.load_live_env",
        expected="live_env_missing",
        actual=f"{_code_of(env_error) if env_error else 'no error'}",
        note="本轮进程环境已剥离全部凭据类变量",
    )


# --------------------------------------------------------------------------- #
# B. 单批 B0 重评分
# --------------------------------------------------------------------------- #


def probe_B(out: Path, repo: Path, approved: Path) -> Path:
    from mktkb.evaluation.p2_b0 import load_approved_b0_config
    from mktkb.evaluation.p2_scoring import (
        P2_B0_EXACT_IDS, P2_B0_IDS, P2_B0_OCR_IDS, HARD_GATE_IDS,
    )

    run_dir = build_b0_run(out / "runs" / "b01", "synthetic-b0-b01", repo)

    # B01：正例
    admit_target = out / "admit" / "b01.json"
    admit_target.parent.mkdir(parents=True, exist_ok=True)
    code, stdout, stderr = admit_cli(run_dir, approved, admit_target)
    if code != 0 or not admit_target.is_file():
        record("B01", "p2-admit 正例（未能产出准入证据）", "ERROR",
               entry="cli baseline p2-admit --out",
               expected="exit 0 且写出准入证据",
               actual=f"exit={code} err={stderr.strip()[:500]}",
               note=stdout.strip()[:300])
        return run_dir
    proof = json.loads(admit_target.read_text(encoding="utf-8"))
    config = load_approved_b0_config(approved)
    gate_status = proof["hard_gate"]["gate_status"]
    checks = {
        "exit0": code == 0,
        "executed40": proof["b0"]["executed"] == 40 and proof["b0"]["planned"] == 40,
        "passed>=36": proof["b0"]["passed"] >= 36,
        "exact24": proof["b0"]["exact_passed"] == 24 and proof["b0"]["exact_planned"] == 24,
        "ocr8": proof["b0"]["ocr_executed"] == 8 and proof["b0"]["ocr_planned"] == 8,
        "hard8": set(gate_status) == set(HARD_GATE_IDS) and len(gate_status) == 8,
        "hard_pass": all(v in {"pass", "not_applicable"} for v in gate_status.values()),
        "applicability": proof["hard_gate"]["scored_count"] >= config.config.min_sample_for("b0"),
        "min_sample": proof["hard_gate"]["min_sample"] == config.config.min_sample_for("b0"),
        "real_calls53": proof["real_calls"] == 53,
        "release_blocked": proof["p2_release_allowed"] is False,
    }
    expect_true(
        "B01", "p2-admit 正例：40/40、≥36、精确 24/24、OCR 8/8、八项硬门禁",
        all(checks.values()),
        entry="cli baseline p2-admit --out",
        expected="全部计数与八项硬门禁符合 v0.3 标准",
        actual=json.dumps({
            "exit": code, "b0": proof["b0"], "hard": gate_status,
            "min_sample": proof["hard_gate"]["min_sample"],
            "scored_count": proof["hard_gate"]["scored_count"],
            "real_calls": proof["real_calls"], "checks": checks,
        }, ensure_ascii=False),
        side_effect=f"admission proof -> {out / 'admit' / 'b01.json'}",
    )
    not_applicable = sorted(k for k, v in gate_status.items() if v == "not_applicable")
    expect_true(
        "B01b", "硬门禁适用性：na 项显式记录且必需三项 pass",
        all(gate_status[name] == "pass" for name in
            ("exact_value_contract", "citation_required", "trace_integrity")),
        entry="p2-admit proof.hard_gate", expected="exact_value_contract/citation_required/trace_integrity 均为 pass",
        actual=f"not_applicable={not_applicable}",
    )

    # B02：低于 36
    others = [cid for cid in P2_B0_IDS
              if cid not in set(P2_B0_EXACT_IDS) and cid not in set(P2_B0_OCR_IDS)]
    assert len(others) >= 5, others
    below = build_b0_run(out / "runs" / "b02", "synthetic-b0-b02", repo,
                         wrong=tuple(others[:5]))
    expect_code("B02", "正确数低于 36 被拒", "b0_score_threshold_not_met",
                lambda: admit_api(below, approved), entry="api check_b0_admission",
                side_effect="40 行仍完整，仅 5 条非精确非 OCR 答案被改错")

    # B03：精确少 1
    exact_off = build_b0_run(out / "runs" / "b03", "synthetic-b0-b03", repo,
                             wrong=(P2_B0_EXACT_IDS[0],))
    expect_code("B03", "精确题少 1（23/24）被拒", "b0_score_threshold_not_met",
                lambda: admit_api(exact_off, approved), entry="api check_b0_admission",
                side_effect="仅一条精确题答案被改错")

    # B04：OCR 未执行（分层证据）
    from mktkb.evaluation.p2_score_run import load_document_codes, score_run
    from mktkb.evaluation.p2_b0 import (
        B0_ARTIFACTS, B0_DOCUMENT_CODES, frozen_b0_cases,
    )

    ocr_copy = out / "runs" / "b04"
    ocr_copy.mkdir(parents=True, exist_ok=True)
    for name in B0_ARTIFACTS:
        shutil.copyfile(run_dir / name, ocr_copy / name)
    lines = (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    dropped = P2_B0_OCR_IDS[0]
    kept = [line for line in lines if json.loads(line)["case_id"] != dropped]
    (ocr_copy / "cases.jsonl").write_text("\n".join(kept) + "\n", encoding="utf-8")
    cases = frozen_b0_cases()
    codes = {name: code for name, code in load_document_codes(B0_DOCUMENT_CODES).items()}
    score = score_run(ocr_copy, cases=cases, document_codes=codes,
                      allowed_doc_codes=set(codes.values()))
    tally = score.scorecard.suites["b0"]
    blocks = {block.code for block in score.scorecard.blocks}
    expect_true(
        "B04a", "OCR 未执行在评分层被识别（8→7）",
        tally.ocr_executed == 7 and tally.required_passed is False
        and "ocr_not_executed" in blocks,
        entry="api p2_score_run.score_run", expected="ocr_executed=7 且 required_passed=False",
        actual=f"ocr_executed={tally.ocr_executed} blocks={sorted(blocks)}",
    )
    expect_code("B04b", "OCR 缺题在准入层被拒（行集不完整先触发）",
                "b0_rows_incomplete", lambda: admit_api(ocr_copy, approved),
                entry="api check_b0_admission",
                note="准入先以 40 行完整性拒绝；OCR 分母证据由 B04a 单独给出")

    # B05：缺 trace
    missing_trace = out / "runs" / "b05"
    shutil.copytree(run_dir.parent.parent, missing_trace)
    missing_run = retarget_trace(missing_trace)
    shutil.rmtree(missing_trace / "app" / "data")
    expect_code("B05", "缺 trace 库被拒", "b0_evidence_file_missing",
                lambda: admit_api(missing_run, approved),
                entry="api check_b0_admission", side_effect="删除合成 trace sqlite")

    # B06：出站不可核
    unknown = out / "runs" / "b06"
    shutil.copytree(run_dir.parent.parent, unknown)
    summary_path = unknown / "app" / "p2-run" / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["network"]["available"] = False
    summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    expect_code("B06", "出站不可核被拒", "b0_outbound_evidence_invalid",
                lambda: admit_api(unknown / "app" / "p2-run", approved),
                entry="api check_b0_admission",
                note="summary.network.available=False（未通过交叉校验的计数不得当实测）")

    # B07：旧 R1 流水线
    r1 = out / "runs" / "b07"
    shutil.copytree(run_dir.parent.parent, r1)
    manifest_path = r1 / "app" / "p2-run" / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["pipeline_version"] = "d3ca88d2c515"
    manifest["formal_b0"]["plan"]["b0_binding"]["pipeline_source_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    expect_code("B07", "旧 R1 流水线证据被拒", "b0_current_pipeline_or_corpus_changed",
                lambda: admit_api(r1 / "app" / "p2-run", approved),
                entry="api check_b0_admission",
                note="pipeline_version=R1 观察值 d3ca88d2c515 且绑定流水线摘要非当前源码")

    # B08：mock 执行
    mock = out / "runs" / "b08"
    shutil.copytree(run_dir.parent.parent, mock)
    manifest_path = mock / "app" / "p2-run" / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["execution"] = "dry_run"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    expect_code("B08", "mock/dry_run 执行被拒", "b0_run_identity_invalid",
                lambda: admit_api(mock / "app" / "p2-run", approved),
                entry="api check_b0_admission")

    # B09：评分确实执行（输入变异 → 分数可见变化）
    pristine = score_run(run_dir, cases=cases, document_codes=codes,
                         allowed_doc_codes=set(codes.values()))
    mutated = score_run(below, cases=cases, document_codes=codes,
                        allowed_doc_codes=set(codes.values()))
    expect_true(
        "B09", "评分确实执行：输入变异改变通过数",
        pristine.scorecard.suites["b0"].passed == 40
        and mutated.scorecard.suites["b0"].passed == 35,
        entry="api score_run", expected="原样 40 通过 / 5 条改错后 35 通过",
        actual=f"pristine={pristine.scorecard.suites['b0'].passed} "
               f"mutated={mutated.scorecard.suites['b0'].passed}",
    )

    # B10：trace 内容检查确实执行（删 span）
    broken = out / "runs" / "b10"
    shutil.copytree(run_dir.parent.parent, broken)
    broken_run = retarget_trace(broken)
    trace_db = broken / "app" / "data" / "observability" / "qa-traces.sqlite3"
    with sqlite3.connect(trace_db) as conn:
        conn.execute("DELETE FROM spans WHERE trace_id = ?", (f"trace-{P2_B0_IDS[0]}",))
        conn.commit()
    expect_code("B10", "trace 内容被破坏被拒（证明 trace 检查执行）",
                "b0_hard_gate_blocked",
                lambda: admit_api(broken_run, approved),
                entry="api check_b0_admission",
                side_effect=f"删除 {P2_B0_IDS[0]} 的全部 span")
    return run_dir


def retarget_trace(copied_root: Path) -> Path:
    """把复制出来的 manifest.trace_store 指向复制体自身的 trace 路径。"""
    manifest_path = copied_root / "app" / "p2-run" / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["trace_store"] = str(
        copied_root / "app" / "data" / "observability" / "qa-traces.sqlite3")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return copied_root / "app" / "p2-run"


# --------------------------------------------------------------------------- #
# C. 审批和移植
# --------------------------------------------------------------------------- #


def probe_C(out: Path, repo: Path, approved: Path, run_dir: Path) -> dict:
    from mktkb.evaluation.baseline import (
        APPROVAL_FILENAME, BASELINE_FILENAME, baseline_id as b0_baseline_id, load_baseline,
        restore_baseline, verify_archive,
    )
    from mktkb.evaluation.p2_b0 import B0_ARTIFACTS
    from mktkb.evaluation.p2_b0_baseline import B0_BASELINE_ARTIFACTS
    from mktkb.evaluation.p2_contracts import payload_sha256

    root = out / "registry"
    admit_out = out / "admit" / "c01.json"
    admit_out.parent.mkdir(parents=True, exist_ok=True)
    code, stdout, stderr = admit_cli(run_dir, approved, admit_out)
    if code != 0 or not admit_out.is_file():
        record("C01", "p2-admit 证据绑定自洽（准入未通过）", "ERROR",
               entry="cli baseline p2-admit",
               expected="exit 0", actual=f"exit={code} err={stderr.strip()[:500]}")
        return {"proof": {}, "archive": out / "archive" / "c05", "root": root,
                "restored_root": out / "restored" / "baselines",
                "runs_root": out / "restored" / "runs", "baseline_id": ""}
    proof = json.loads(admit_out.read_text(encoding="utf-8"))
    recomputed = payload_sha256({
        key: value for key, value in proof.items()
        if key not in {"baseline_id", "evidence_sha256"}
    })
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    admission = admit_api(run_dir, approved)
    expect_true(
        "C01", "p2-admit 证据绑定自洽",
        code == 0 and proof["run_id"] == admission.run.manifest.run_id
        and proof["baseline_id"] == b0_baseline_id(admission.run)
        and proof["gate_config_hash"] == "7fa6f47a445f9643eb7f2e5ae78a72411007da38a56fca1082657870b2eab094"
        and proof["evidence_sha256"] == recomputed,
        entry="cli baseline p2-admit",
        expected="run_id/baseline_id/gate_config_hash/evidence_sha256 均可重算",
        actual=f"run_id={proof['run_id']} baseline_id={proof['baseline_id']} "
               f"recomputed_baseline_id={b0_baseline_id(admission.run)} "
               f"gate={proof['gate_config_hash']} "
               f"evidence_ok={proof['evidence_sha256'] == recomputed}",
    )

    receipt = out / "receipts" / "c01-receipt.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({
        "schema_version": "mktkb.p2.b0.approval.v0.1", "scope": "t209_b0_baseline",
        "decision": "approved", "run_id": proof["run_id"],
        "baseline_id": proof["baseline_id"], "evidence_sha256": proof["evidence_sha256"],
        "approver": "synthetic-owner", "approved_at": "2026-11-20T11:11:00+08:00",
        "reason": "synthetic isolated acceptance",
    }, ensure_ascii=False), encoding="utf-8")
    approve_argv = ["baseline", "p2-approve", "--run", str(run_dir),
                    "--gate-config", str(approved), "--root", str(root),
                    "--receipt", str(receipt)]

    # C02：错审批摘要
    wrong_receipt = out / "receipts" / "c02-receipt.json"
    wrong_receipt.write_text(json.dumps({
        **json.loads(receipt.read_text(encoding="utf-8")), "evidence_sha256": "e" * 64,
    }, ensure_ascii=False), encoding="utf-8")
    code, stdout, stderr = cli_call([
        "baseline", "p2-approve", "--run", str(run_dir), "--gate-config", str(approved),
        "--root", str(root), "--receipt", str(wrong_receipt),
    ])
    expect_true(
        "C02", "错审批摘要被拒且不建 root",
        code == 3 and "b0_approval_receipt_mismatch" in stderr and not root.exists(),
        entry="cli baseline p2-approve", expected="exit 3 + b0_approval_receipt_mismatch",
        actual=f"exit={code} err={stderr.strip()[:200]}", side_effect=f"{root} exists={root.exists()}",
    )

    # C01b：正式审批
    code, stdout, stderr = cli_call(approve_argv)
    expect_true(
        "C01b", "合成审批记录保存 B0 基线",
        code == 0 and root.is_dir() and (root / proof["baseline_id"] / APPROVAL_FILENAME).is_file(),
        entry="cli baseline p2-approve --receipt",
        expected="exit 0 且 <root>/<baseline_id>/approval.json 存在",
        actual=f"exit={code} {stdout.strip()[:200]} err={stderr.strip()[:200]}",
    )

    # C03：重复审批
    code, stdout, stderr = cli_call(approve_argv)
    expect_true(
        "C03", "重复审批被拒（不覆盖既有基线）",
        code == 3 and ("b0_target_exists" in stderr or "已存在" in stderr),
        entry="cli baseline p2-approve（第二次）", expected="exit 3 + b0_target_exists",
        actual=f"exit={code} err={stderr.strip()[:200]}",
    )

    # C04：列表
    code, stdout, stderr = cli_call(["baseline", "list", "--root", str(root)])
    expect_true(
        "C04", "baseline list 列出已审批 B0 且标注 p2_release_allowed=no",
        code == 0 and proof["baseline_id"] in stdout and "approved=yes" in stdout
        and "p2_release_allowed=no" in stdout,
        entry="cli baseline list", expected="approved=yes 且 p2_release_allowed=no",
        actual=stdout.strip()[:300],
    )

    # C05：归档
    archive_path = out / "archive" / "c05"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    code, stdout, stderr = cli_call([
        "baseline", "archive", "--baseline", proof["baseline_id"], "--root", str(root),
        "--out", str(archive_path),
    ])
    record_things = verify_archive(archive_path)
    expect_true(
        "C05", "archive 归档已审批 B0 证据链",
        code == 0 and record_things.has_approval is True and record_things.identity.is_p2_b0
        and len(record_things.files) == len(B0_ARTIFACTS) + len(B0_BASELINE_ARTIFACTS) + 2,
        entry="cli baseline archive", expected="approved=yes 且文件集 = 7 run + 4 baseline + baseline/approval",
        actual=f"exit={code} files={len(record_things.files)} approved={record_things.has_approval}",
    )

    # C06：verify / restore（撤掉原题集路径依赖）
    from mktkb.evaluation import p2_b0 as p2_b0_module

    original_cases_path = p2_b0_module.B0_CASES_PATH
    p2_b0_module.B0_CASES_PATH = out / "missing-b0.jsonl"
    try:
        code_verify, verify_out, verify_err = cli_call(
            ["baseline", "verify", "--archive", str(archive_path)])
        restored_root = out / "restored" / "baselines"
        runs_root = out / "restored" / "runs"
        code_restore, restore_out, restore_err = cli_call([
            "baseline", "restore", "--archive", str(archive_path), "--root",
            str(restored_root), "--runs-root", str(runs_root),
        ])
    finally:
        p2_b0_module.B0_CASES_PATH = original_cases_path
    expect_true(
        "C06", "撤掉原题集路径后 verify/restore 仍可用（移植证据自足）",
        code_verify == 0 and code_restore == 0 and "archive ok" in verify_out
        and "restored baseline_id" in restore_out,
        entry="cli baseline verify / restore（B0_CASES_PATH 指向缺失文件）",
        expected="两者 exit 0",
        actual=f"verify={code_verify} restore={code_restore} "
               f"err={verify_err.strip()[:120]}{restore_err.strip()[:120]}",
    )

    # C07：恢复后逐字节比对全部公开工件 + 审批关系
    restored_baseline = load_baseline(proof["baseline_id"], restored_root)
    target_run = Path(restored_baseline.run_dir)
    identical = all(
        (target_run / name).read_bytes() == (run_dir / name).read_bytes()
        for name in B0_ARTIFACTS
    )
    expect_true(
        "C07", "恢复后公开 run 工件逐字节一致且审批关系不变",
        identical and restored_baseline.approval is not None
        and restored_baseline.approval.gate_result_sha256 == proof["evidence_sha256"]
        and restored_baseline.approval.approver == "synthetic-owner"
        and dict(restored_baseline.artifact_sha256) == proof["artifact_sha256"],
        entry="api baseline.load_baseline（恢复后）",
        expected="7 个工件字节一致 + approval 绑定同一 evidence_sha256",
        actual=f"identical={identical} approver={getattr(restored_baseline.approval, 'approver', None)}",
    )

    # C08：重复恢复被拒
    expect_code("C08", "重复恢复被拒（不覆盖既有目标）", "b0_target_exists",
                lambda: restore_baseline(archive_path, restored_root),
                entry="api restore_baseline（第二次）")

    # C09：缺工件
    broken = out / "archive" / "c09"
    shutil.copytree(archive_path, broken)
    (broken / "run" / "requests.jsonl").unlink()
    expect_raises("C09", "归档缺工件被拒", ValueError, "文件集合", 
                  lambda: verify_archive(broken), entry="api verify_archive")

    # C10：加入未列入清单的文件
    extra = out / "archive" / "c10"
    shutil.copytree(archive_path, extra)
    (extra / "run" / "extra.json").write_text("{}", encoding="utf-8")
    expect_raises("C10", "归档出现未列入清单的文件被拒", ValueError, "文件集合",
                  lambda: verify_archive(extra), entry="api verify_archive")

    # C11：归档到已有目标
    existing = out / "archive" / "c11"
    existing.mkdir(parents=True, exist_ok=True)
    sentinel = existing / "sentinel.bin"
    sentinel.write_bytes(b"c11-sentinel-\x00\x01")
    before = sentinel.read_bytes()
    code, stdout, stderr = cli_call([
        "baseline", "archive", "--baseline", proof["baseline_id"], "--root", str(root),
        "--out", str(existing),
    ])
    expect_true(
        "C11", "归档到已有目标被拒且既有目标字节不变",
        code == 3 and sentinel.read_bytes() == before,
        entry="cli baseline archive --out <existing>",
        expected="exit 3 且 sentinel 字节不变",
        actual=f"exit={code} err={stderr.strip()[:160]} unchanged={sentinel.read_bytes() == before}",
    )

    # C12：p2-diff 同基线
    code, stdout, stderr = cli_call([
        "baseline", "p2-diff", "--run", str(run_dir), "--gate-config", str(approved),
        "--root", str(restored_root),
    ])
    diff_payload = cli_json(stdout)
    expect_true(
        "C12", "p2-diff 同基线可分析且不放行 P2",
        code == 0 and diff_payload["baseline_approved"] is True
        and diff_payload["release_allowed"] is False
        and diff_payload["p2_release_status"] == "blocked_pending_n_c_u_h2_evidence",
        entry="cli baseline p2-diff", expected="baseline_approved=true 且 release_allowed=false",
        actual=f"exit={code} release_allowed={diff_payload.get('release_allowed')} "
               f"status={diff_payload.get('p2_release_status')}",
    )
    return {
        "proof": proof, "archive": archive_path, "root": root,
        "restored_root": restored_root, "runs_root": runs_root,
        "baseline_id": proof["baseline_id"], "budget": proof,
    }


# --------------------------------------------------------------------------- #
# D. 差异和路径边界
# --------------------------------------------------------------------------- #


def probe_D(out: Path, repo: Path, approved: Path, ctx: dict) -> None:
    from mktkb.evaluation.baseline import BaselineIdentity, load_baseline
    from mktkb.evaluation.gate import GATE_VERSION_V0_3
    from mktkb.evaluation.p2_b0 import (
        build_b0_plan_binding, check_b0_admission, load_approved_b0_config,
        read_member, safe_path, validate_b0_live_inputs,
    )
    from mktkb.evaluation.p2_contracts import P2RunPlan

    fake_digest = "f" * 64
    second = build_b0_run(out / "runs" / "d01", "synthetic-b0-d01", repo,
                          pipeline_digest=fake_digest)
    _, draft = b0_inputs(repo)
    draft_document = json.loads(draft.read_text(encoding="utf-8"))

    # D01：跨流水线默认拒绝（显式选中另一流水线基线、但不给 compare-with）
    with pipeline_patch(fake_digest):
        code, stdout, stderr = cli_call([
            "baseline", "p2-diff", "--run", str(second), "--gate-config", str(approved),
            "--root", str(ctx["restored_root"]), "--baseline", ctx["baseline_id"],
        ])
    expect_true(
        "D01", "跨流水线默认拒绝",
        code == 3 and "CrossVersionBaselineError" in stderr,
        entry="cli baseline p2-diff --baseline <另一流水线>",
        expected="exit 3 + CrossVersionBaselineError",
        actual=f"exit={code} err={stderr.strip()[:220]}",
        note="同身份默认拒绝：pipeline_version 不同必须显式 compare-with",
    )
    with pipeline_patch(fake_digest):
        code, stdout, stderr = cli_call([
            "baseline", "p2-diff", "--run", str(second), "--gate-config", str(approved),
            "--root", str(ctx["restored_root"]),
        ])
    expect_true(
        "D01b", "未指定基线时按当前流水线身份找不到基线即拒绝",
        code == 3 and "baseline 不存在" in stderr,
        entry="cli baseline p2-diff（无 --baseline）",
        expected="exit 3 + baseline 不存在",
        actual=f"exit={code} err={stderr.strip()[:200]}",
    )

    # D02：显式 compare-with → 仅分析
    with pipeline_patch(fake_digest):
        code, stdout, stderr = cli_call([
            "baseline", "p2-diff", "--run", str(second), "--gate-config", str(approved),
            "--root", str(ctx["restored_root"]), "--compare-with", ctx["baseline_id"],
        ])
    payload = cli_json(stdout)
    expect_true(
        "D02", "显式 compare-with 可分析且 release_allowed=false",
        code == 0 and payload["release_allowed"] is False
        and payload["baseline_approved"] is True
        and payload["comparison"] == "explicit_cross_version",
        entry="cli baseline p2-diff --compare-with",
        expected="exit 0 且 comparison=explicit_cross_version / release_allowed=false",
        actual=f"exit={code} comparison={payload.get('comparison')} "
               f"release_allowed={payload.get('release_allowed')}",
    )
    with pipeline_patch(None):
        pass

    # D03：同 gate 版本但配置摘要变化
    changed = out / "configs" / "d03-changed.json"
    changed.parent.mkdir(parents=True, exist_ok=True)
    body = json.loads(approved.read_text(encoding="utf-8"))
    body["notes"] = "synthetic same-version changed configuration"
    changed.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    code, stdout, stderr = cli_call([
        "baseline", "p2-admit", "--run", str(out / "runs" / "b01" / "app" / "p2-run"),
        "--gate-config", str(changed),
    ])
    expect_true(
        "D03", "同 gate 版本而配置摘要变化被拒",
        code == 3 and "b0_gate_file_not_approved" in stderr,
        entry="cli baseline p2-admit --gate-config <changed>",
        expected="exit 3 + b0_gate_file_not_approved",
        actual=f"exit={code} err={stderr.strip()[:200]}",
    )

    # D04：语料摘要变化 → baseline 不可比（题集受冻结摘要约束，无合法可差分对）
    admission = check_b0_admission(out / "runs" / "b01" / "app" / "p2-run",
                                   load_approved_b0_config(approved))
    identity = admission.run.manifest
    fabricated = BaselineIdentity(
        dataset_version=identity.dataset_version, pipeline_version=identity.pipeline_version,
        mode="live", scope="end_to_end", gate_version=GATE_VERSION_V0_3,
        corpus_sha256="d" * 64,
    )
    expect_raises("D04", "语料摘要不同即不可比（load_baseline 拒绝）", ValueError,
                  "corpus_sha256",
                  lambda: load_baseline(ctx["baseline_id"], ctx["restored_root"],
                                       expected=fabricated),
                  entry="api baseline.load_baseline(expected=<corpus 改>)",
                  note="b0_diff_dataset_mismatch 分支因冻结题集摘要恒定不可达；"
                       "等价拒绝在 load_baseline 的可比性检查实测")

    # D05：路径外逃（语料源在 fixtures/acceptance 之外）
    from mktkb.evaluation.product_adapter import IngestSource, P2IngestPlan

    dataset, ingest, recipe = load_b0_dataset_and_ingest(repo)
    escaped_sources = list(ingest.sources)
    escaped_sources[0] = IngestSource(
        path=repo / "docs/evaluation/gate_v0_3.json", name=escaped_sources[0].name,
        publish=True,
    )
    escaped = P2IngestPlan(sources=tuple(escaped_sources), label="d05")
    run_id = "synthetic-b0-d05"
    plan = P2RunPlan.from_dict({
        **draft_document, "b0_binding": build_b0_plan_binding(run_id),
    })
    expect_code(
        "D05", "语料路径外逃被拒", "b0_corpus_path_invalid",
        lambda: validate_b0_live_inputs(
            plan, run_id=run_id, dataset=dataset, ingest_plan=escaped,
            gate_config=load_approved_b0_config(approved),
            out_dir=out / "runs" / "d05",
        ),
        entry="api validate_b0_live_inputs", note="源路径指向 fixtures/acceptance 之外",
    )

    # D06：硬链接
    hard_dir = out / "links" / "d06"
    hard_dir.mkdir(parents=True, exist_ok=True)
    original = hard_dir / "evidence.json"
    original.write_text("{}", encoding="utf-8")
    linked = hard_dir / "linked.json"
    try:
        os.link(original, linked)
        real_link = True
    except OSError as exc:  # Windows 权限
        real_link = False
        link_error = f"{type(exc).__name__}: {exc}"
    if real_link:
        expect_code("D06", "硬链接被拒（真实文件系统）", "b0_link_rejected",
                    lambda: read_member(linked), entry="api p2_b0.read_member",
                    side_effect="os.link 成功，真实硬链接证据")
    else:
        code = _injected_nlink_case(linked)
        record("D06", "硬链接被拒（lstat/stat 注入补验）",
               "PASS" if code == "b0_link_rejected" else "FAIL",
               entry="api p2_b0.read_member（注入 st_nlink=2）",
               expected="b0_link_rejected", actual=code,
               note=f"真实 os.link 不可用：{link_error}", side_effect="真实硬链接证据缺口，见报告")

    # D07：目录联接 / 重解析点（注入 lstat 属性）
    reparse_code = _injected_reparse_case(out / "links" / "d07")
    record("D07", "重解析点/目录联接被拒（lstat 注入补验）",
           "PASS" if reparse_code == "b0_link_rejected" else "FAIL",
           entry="api p2_b0.safe_path（注入 reparse 属性）",
           expected="b0_link_rejected", actual=reparse_code,
           note="真实 mklink /J 需子进程，本轮由进程守卫阻断")
    symlink_code = _injected_symlink_case(out / "links" / "d07b")
    record("D07b", "符号链接被拒（lstat 注入补验）",
           "PASS" if symlink_code == "b0_link_rejected" else "FAIL",
           entry="api p2_b0.safe_path（注入 S_IFLNK）",
           expected="b0_link_rejected", actual=symlink_code)

    # D08：已有目标 + 哨兵字节不变
    from mktkb.evaluation.baseline import restore_baseline

    occupied = out / "occupied" / "runs" / "synthetic-b0-b01"
    occupied.mkdir(parents=True, exist_ok=True)
    sentinel = occupied / "sentinel.bin"
    sentinel.write_bytes(b"d08-sentinel-\xfe\xff")
    before = sentinel.read_bytes()
    expect_code(
        "D08", "恢复目标已存在被拒且哨兵不变", "b0_target_exists",
        lambda: restore_baseline(ctx["archive"], out / "occupied" / "baselines",
                                 runs_root=out / "occupied" / "runs"),
        entry="api restore_baseline（目标已存在）",
        note="比较哨兵前后字节",
    )
    expect_true(
        "D08b", "既有目标哨兵字节未变", sentinel.read_bytes() == before,
        entry="filesystem", expected="sentinel 字节不变",
        actual=f"unchanged={sentinel.read_bytes() == before}",
    )


def _injected_nlink_case(path: Path) -> str:
    import pathlib

    from mktkb.evaluation import p2_b0

    if not path.exists():
        path.write_text("{}", encoding="utf-8")
    real_stat = pathlib.Path.stat
    real = os.stat(str(path))

    def fake_stat(self, *args, **kwargs):  # noqa: ANN001
        if self == path:
            return SimpleNamespace(
                st_mode=real.st_mode, st_nlink=2, st_size=real.st_size,
                st_file_attributes=0, st_ino=real.st_ino, st_dev=real.st_dev,
            )
        return real_stat(self, *args, **kwargs)

    pathlib.Path.stat = fake_stat
    try:
        p2_b0.read_member(path)
        return "no error"
    except ValueError as exc:
        return _code_of(exc)
    finally:
        pathlib.Path.stat = real_stat


def _injected_reparse_case(directory: Path) -> str:
    import pathlib

    from mktkb.evaluation import p2_b0

    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "junction.json"
    target.write_text("{}", encoding="utf-8")
    real_lstat = pathlib.Path.lstat
    real = real_lstat(target)

    def fake_lstat(self, *args, **kwargs):  # noqa: ANN001
        if self == target:
            return SimpleNamespace(
                st_mode=real.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
                st_nlink=1,
            )
        return real_lstat(self, *args, **kwargs)

    pathlib.Path.lstat = fake_lstat
    try:
        p2_b0.safe_path(target)
        return "no error"
    except ValueError as exc:
        return _code_of(exc)
    finally:
        pathlib.Path.lstat = real_lstat


def _injected_symlink_case(directory: Path) -> str:
    import pathlib

    from mktkb.evaluation import p2_b0

    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "symlink.json"
    target.write_text("{}", encoding="utf-8")
    real_lstat = pathlib.Path.lstat

    def fake_lstat(self, *args, **kwargs):  # noqa: ANN001
        if self == target:
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_nlink=1)
        return real_lstat(self, *args, **kwargs)

    pathlib.Path.lstat = fake_lstat
    try:
        p2_b0.safe_path(target)
        return "no error"
    except ValueError as exc:
        return _code_of(exc)
    finally:
        pathlib.Path.lstat = real_lstat


# --------------------------------------------------------------------------- #
# E. 候选 / 受限证据 / P2 发布
# --------------------------------------------------------------------------- #


def probe_E(out: Path, repo: Path, approved: Path, ctx: dict) -> None:
    from mktkb.evaluation import p2_candidate_report as pr
    from mktkb.evaluation.baseline import (
        BaselineArchiveError, approve_baseline, load_baseline, save_baseline,
    )
    from mktkb.evaluation.p2_b0 import check_b0_admission, load_approved_b0_config
    from mktkb.evaluation.report import require_release_baseline

    sys.path.insert(0, str(repo / "backend"))
    from tests.evaluation.test_report import (  # noqa: E402
        make_case, make_gate, make_manifest, make_row, write_run,
    )

    # E01：合成 E2 候选归档 → 不可发布、无审批
    cases = tuple(make_case(f"Q{index:03d}") for index in range(1, 31))
    rows = [make_row(case, status="pass") for case in cases]
    run = write_run(out / "e01", "run-e01", rows=rows,
                    manifest=make_manifest(run_id="run-e01"), cases=cases)
    source_root = out / "e01" / "baselines"
    baseline = save_baseline(run, source_root)
    axes = tuple(pr.AxisEvidence.create(axis=axis, planned=30, passed=30,
                                        not_applicable=0, unknown=0, violations=0)
                 for axis in ("safety", "cross_user", "cross_entity", "stale_source"))
    report = pr.build_split_report(
        reference=pr.ReferenceSource.create(
            source_kind="synthetic-mirror",
            document="docs/reports/OBS-EVAL/P2/T207-RETEST-20261119/manager-receipt.md",
            plan_id="probing",
            code_version="synthetic"),
        execution=pr.build_execution(
            round_id="probing",
            runs=(pr.RunOutcome("s0", "synthetic_clean", "succeeded", 30, 30),)),
        quality=pr.build_quality(
            round_id="probing", total=30, passed=30, failed=0, errors=0,
            safety_violations=0, min_pass=24, thresholds_approved=False, verified=True,
            scenario_verifications=(("s0", True),)),
        evidence=pr.build_evidence(round_id="probing", total=30, missing_evidence_cases=0,
                                   axes=axes, verified=True),
        soft=(pr.SoftStatus.not_run("ragas", recorded_status="NOT-RUN", detail="合成"),),
        funding=pr.FundingStatus.create(
            ledger_current_sha256="a" * 64, ledger_previous_sha256="b" * 64,
            ledger_change_cause="legitimate_spend", go_current_sha256="c" * 64,
            go_archived_sha256="d" * 64, archived_line_moment="合成"),
    )
    candidate_dir = out / "candidates" / "e01"
    candidate = pr.archive_candidate(
        baseline_id_value=baseline.baseline_id, root=source_root, out_dir=candidate_dir,
        report=report, reason="synthetic candidate archive",
    )
    candidate_manifest = json.loads(
        (candidate_dir / pr.CANDIDATE_FILENAME).read_text(encoding="utf-8"))
    expect_true(
        "E01", "合成 E2 候选归档：publishable=false / 无 approval / 不可作为 release baseline",
        candidate_manifest["has_approval"] is False
        and candidate_manifest["publishable"] is False
        and candidate_manifest["release_baseline"] is False
        and candidate_manifest["gate_approved"] is False
        and candidate_manifest["state"] in {"candidate", "blocked"}
        and not (candidate_dir / pr.CANDIDATE_PAYLOAD_DIR / "baseline" / "approval.json").exists(),
        entry="api p2_candidate_report.archive_candidate",
        expected="has_approval=false 且 publishable/release_baseline/gate_approved 均 false",
        actual=f"state={candidate_manifest['state']} "
               f"has_approval={candidate_manifest['has_approval']} "
               f"publishable={candidate_manifest['publishable']} "
               f"release_baseline={candidate_manifest['release_baseline']}",
    )
    restored = pr.restore_candidate(candidate_dir, out / "e01-restore" / "baselines")
    expect_true(
        "E01b", "候选恢复后仍无审批、仍不可发布",
        restored.baseline.approval is None
        and pr.candidate_state_for_report(report) in {"candidate", "blocked"},
        entry="api p2_candidate_report.restore_candidate",
        expected="approval 为空且状态保持 candidate/blocked",
        actual=f"approval={restored.baseline.approval} state={pr.candidate_state_for_report(report)}",
    )

    # E02：holdout 声明被拒绝
    holdout_run = write_run(
        out / "e02", "run-e02", rows=rows,
        manifest=make_manifest(run_id="run-e02", holdout_details=True), cases=cases)
    holdout_root = out / "e02" / "baselines"
    holdout_baseline = save_baseline(holdout_run, holdout_root)
    expect_raises(
        "E02", "声明 holdout 明细的 manifest 拒绝归档", ValueError, "holdout",
        lambda: pr.archive_candidate(
            baseline_id_value=holdout_baseline.baseline_id, root=holdout_root,
            out_dir=out / "candidates" / "e02", report=report,
            reason="synthetic holdout refusal"),
        entry="api p2_candidate_report.archive_candidate",
        note="holdout_details=true（逐题明细）",
    )

    # E03：合成私有字段探针
    from mktkb.evaluation.p2_b0 import public_json

    for label, payload in (
        ("holdout_details", {"holdout_details": []}),
        ("h2_axis", {"h2_axis_notes": "synthetic"}),
        ("private_mark", {"private_case_marks": {}}),
        ("ocr_secret", {"ocr_secret_key": "synthetic"}),
    ):
        expect_code(f"E03-{label}", f"私有字段 {label} 被拒", "b0_private_fields_rejected",
                    lambda payload=payload: public_json(json.dumps(payload).encode("utf-8")),
                    entry="api p2_b0.public_json")

    # E04：单次 B0 准入/审批/差异均无法放行 P2
    admission = check_b0_admission(out / "runs" / "b01" / "app" / "p2-run",
                                   load_approved_b0_config(approved))
    expect_true(
        "E04", "准入证据显式禁止 P2 放行",
        admission.proof["p2_release_allowed"] is False
        and admission.proof["p2_release_status"] == "blocked_pending_n_c_u_h2_evidence"
        and set(admission.proof["p2_release_evidence"].values()) == {"unknown"}
        and set(admission.proof["p2_release_evidence"]) == {
            "negative", "boundary", "update_delete", "holdout"},
        entry="api check_b0_admission proof",
        expected="p2_release_allowed=false 且四轴证据均为 unknown",
        actual=json.dumps(admission.proof["p2_release_evidence"], ensure_ascii=False)
        + " " + admission.proof["p2_release_status"],
    )
    from mktkb.evaluation import report as report_module
    from mktkb.evaluation.baseline import CrossVersionBaselineError, baseline_identity

    config = load_approved_b0_config(approved)
    current = check_b0_admission(out / "runs" / "b01" / "app" / "p2-run", config,
                                 allow_quality_regression=True)
    previous = load_baseline(ctx["baseline_id"], ctx["restored_root"],
                             expected=baseline_identity(current.run))
    run_diff = report_module.diff_runs(previous, current.run, comparison="analysis",
                                       compare_with=None, config=config.config)
    expect_raises(
        "E04b", "已审批 B0 基线的差异仍不能作为 P2 发布放行", CrossVersionBaselineError,
        "不能作为发布放行依据",
        lambda: require_release_baseline(run_diff),
        entry="api report.require_release_baseline",
        note=f"release_allowed={run_diff.release_allowed} "
             f"reason={run_diff.release_blocked_reason}",
    )

    # E05：正式 v0.3 跨场景证据缺项保留（N/C/U/H2）
    receipt = repo / "docs/reports/OBS-EVAL/P2/T207-RETEST-20261119/manager-receipt.md"
    text = receipt.read_text(encoding="utf-8")
    expect_true(
        "E05", "正式 v0.3 的跨场景缺项（N/C/U/H2）在 T207 接收记录中仍保留",
        "required unknown=2" in text and "C27" in text and "C29" in text
        and "forbidden_source_unmappable" in text
        and set(admission.proof["p2_release_evidence"].values()) == {"unknown"},
        entry="docs T207-RETEST manager-receipt + B0 admission proof",
        expected="接收记录仍记 required unknown=2（C27/C29），B0 证据四轴全 unknown",
        actual=f"required_unknown_2={'required unknown=2' in text} "
               f"axes={sorted(admission.proof['p2_release_evidence'].items())}",
    )

    # E06：H2 的 2 个必要轴未知仍未被 B0 环节关闭
    standards = json.loads(approved.read_text(encoding="utf-8"))["p2_standards"]
    manifest = json.loads(
        (out / "runs" / "b01" / "app" / "p2-run" / "run_manifest.json")
        .read_text(encoding="utf-8"))
    manifest_keys = set(manifest)
    axis_names = {"safety", "cross_user", "stale_source"}
    expect_true(
        "E06", "H2 两个必要轴未知保留，B0 未伪称已闭合",
        standards["holdout"]["total"] == 30 and standards["holdout"]["min_pass"] == 24
        and admission.proof["p2_release_evidence"]["holdout"] == "unknown"
        and set(admission.proof["p2_release_evidence"].values()) == {"unknown"}
        and not (axis_names & manifest_keys)
        and not any(key.startswith(("holdout_", "private_", "h2_")) for key in manifest_keys),
        entry="gate_v0_3_approved.json p2_standards + B0 manifest/proof",
        expected="H2 分母仍在 v0.3 配置内，但 B0 证据对 holdout 轴保持 unknown 且不含四轴逐题证据",
        actual=f"holdout_total={standards['holdout']['total']} "
               f"holdout_axis={admission.proof['p2_release_evidence']['holdout']} "
               f"axis_keys_in_manifest={sorted(axis_names & manifest_keys)} "
               f"holdout_keys_in_manifest="
               f"{sorted(k for k in manifest_keys if k.startswith(('holdout_', 'private_', 'h2_')))}",
    )


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #


def main(repo: Path, area: Path) -> int:
    repo = Path(repo).resolve()
    area = Path(area).resolve()
    out = area / "probes"
    if out.exists():
        import shutil as _shutil

        _shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    approved, _ = b0_inputs(repo)
    print("PROBES_BEGIN", area, flush=True)
    try:
        probe_A(out, repo, approved)
        run_dir = probe_B(out, repo, approved)
        ctx = probe_C(out, repo, approved, run_dir)
        probe_D(out, repo, approved, ctx)
        probe_E(out, repo, approved, ctx)
    except BaseException:  # noqa: BLE001
        traceback.print_exc()
        RECORDS.append({
            "id": "FATAL", "title": "探针执行中断", "verdict": "ERROR", "entry": "",
            "expected": "", "actual": traceback.format_exc(), "code": "", "note": "",
            "side_effect": "",
        })
    summary = {
        "records": RECORDS,
        "pass": sum(1 for item in RECORDS if item["verdict"] == "PASS"),
        "fail": sum(1 for item in RECORDS if item["verdict"] == "FAIL"),
        "error": sum(1 for item in RECORDS if item["verdict"] == "ERROR"),
    }
    (area / "logs" / "probe-records.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PROBES_SUMMARY pass={summary['pass']} fail={summary['fail']} "
          f"error={summary['error']}", flush=True)
    return 1 if (summary["fail"] or summary["error"]) else 0
```
<!-- B0-IA-PROBES-END -->

</details>
