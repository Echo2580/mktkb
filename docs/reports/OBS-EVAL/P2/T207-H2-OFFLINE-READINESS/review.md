# T207-H2-OFFLINE-READINESS C 集成离线评审（独立验收）

- 验收者：`ai-ci`（全新上下文；非 A/B/C 开发作者；未修改任何产品源码、开发测试、开发报告、冻结文件）。
- 验收对象（最终同一对象，`frozen_utc=2026-11-13T22:11:34Z`）：
  - `evidence/c-freeze.txt`：12 个对象 = A 未变 7 + B 最终 4 + C 新测试 1（与 `a-freeze.txt` 9 项、
    `b-freeze.txt` 11 项交叉一致，0 mismatch）；
  - 基线：`T207-CAPTURE-CONTRACT-R2/evidence/a-freeze.txt`（A-I PASS）、
    `T207-CROSS-ENTITY-SCOPE-R1/evidence/b-freeze.txt`（B-I PASS）；
  - 资金三件套；R11 273 项冻结对象。
- 协议版本（逐值核过）：证据 `p2-hard-evidence-capture/v0.3`（local_mock）、快照
  `p2-runtime-snapshot/v0.1`、分类 `p2-hard-evidence-classification/v0.2`、归属合同
  `p2-entity-scope/v0.1`、标注 `p2-h2-custody/v0.2`、卡 `mktkb.p2.scoring.v0.2`。
- **C 总体判定：PASS（离线合成范围）**；按任务书 §9 词汇为 **`OFFLINE_PASS_WITH_LIVE_BLOCKERS`**。
  **不得**写 REAL_READY / production_ready / release_ready=true；真实 H2/GO/ledger/预算/凭据/
  preflight、真实质量重评分、真实私有 scope 映射仍 NOT-RUN。
- 独立方法：不引用开发报告数字；自建 4 题合成链、5 回合、2 会话；自行用 `cryptography.Fernet`
  直接解密全部密文并解析 JSON；自建 14 类反例；独立子进程跑正式 CLI 并与进程内逐字节对比；
  自建网络 guard 实测外连 0。
- 独立证据：`independent/`（`ci_support.py`、`ci_chain.py`、`ci_negatives.py`、`ci_first_error.py`、
  `ci_freeze_check.py`、`freeze-recheck.txt`、10 份运行日志）。

## 1. C1 冻结字节、身份与停写（PASS）

复核时间 `2026-11-13T22:25:15Z`；工作区 `D:\GPT项目\市场部AI知识库`；分支 `codex/p2-e2e`；
HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；暂存区 **0 项**。证据：`independent/freeze-recheck.txt`。

| 核对项 | 结果 |
|---|---|
| c-freeze 12 个对象 SHA256 | **12/12 逐值一致，0 mismatch** |
| A 未变 7 文件 vs `a-freeze.txt` | **7/7 一致** |
| B changed-vs-A 4 文件 vs `b-freeze.txt` | **4/4 一致**（`b-freeze.txt` 与 `b-freeze-final.txt` 同为 `8f2e6c1b…`；`a-freeze.txt` 与 `a-freeze-final.txt` 同为 `d632e91e…`） |
| 资金三件套 | **3/3 一致**（`4d80d77…fcc6` / `79b2170…1a9e` / `f688ec7…ea98`） |
| R11 冻结 273 项 | **items=273, mismatches=0, missing=0** |
| 停写（对象 mtime ≤ `frozen_utc`） | **PASS**：最大对象 mtime `22:08:52Z`（C 新测试），报告 `22:11:29Z`，均 < `22:11:34Z` |
| 无并发写者 | C 写入窗口（`22:02:02Z`→`22:12:30Z`）内仓库只出现：C 新测试、`report.md`、`c-freeze.txt` 与 B-I 的冻结核对文件（`b-freeze*.txt`、`independent/` 收口）；无其他产品/测试/契约写入 |
| 未声明依赖身份 | 5 个未被本包改动的依赖（`observability/evaluation_capture.py`、`conversations/service.py`、`qa/service.py`、`rag/index.py`、`tools/p2_h2_controlled_execute.py`）与 A 的 task-0 `site-baseline.txt` **5/5 一致**；`rag/query.py`、`rag/facts.py` 与 R11/裁决 hash 一致 |

- 合成身份约束逐值成立：case-plan `bindings` = 认证 envelope 的 16 键绑定；`config_hash` =
  scope 合同文件 SHA256（CLI 回执同值）；合同 `bindings.run_id/plan_id/plan_sha256` 与
  envelope/case-plan 逐值一致；协议三版本（v0.3 / v0.2 / v0.1）固定并参与校验。
- **NOTE（非字节问题）**：`c-freeze.txt` 自身写入 `22:11:38Z`，晚于其声明的 `frozen_utc` 4s；
  与 A/B 冻结文件同属“冻结生成动作”，被验的 12 个对象与报告均早于 `frozen_utc`。B-I
  `review-addendum-2.md` 已接受同一模式。
- 任务书写“11 个最终对象”与 c-freeze 实际计数差 1：c-freeze 为 **11 个 A/B 对象 + 1 个 C 新测试 = 12**；
  本次按 12 个逐一核对。

## 2. C2 自建正式格式合成链与独立重算（PASS）

自建链（`independent/ci_chain.py`，64 项检查全 PASS，日志 `run_ci_chain.log`）：

1. 真实 `ProductEvalAdapter` + `MockChatBackend` + 公共 D01/D04；显式 v0.3；5 回合
   （2 legacy 文档轮、1 无事实拒答、2 RAG 枚举轮，第 5 轮在独立会话）。
2. 每回合：产品响应 → 观察事件 → 同实例只读 DB 投影 → `runtime_snapshot` → 完整性 →
   加密写盘 → 读回。
3. 关闭产品实例（`_closed=True`）并**删除合成 product 目录（业务库/trace/上传件）**，之后才解密/重算；
   自建 CLI 复算用同一份仓外密文，重复两次逐字节一致（不依赖瞬时现场）。
4. 自建解密：`Fernet(key).decrypt(token)` 后 `json.loads`，不经产品 reader；5 个 turn + manifest
   全部可独立解密，`schema_version` 全为 v0.3 且含 `runtime_snapshot`；manifest `turn_count=5`。

| case | 自建形态 | 预声明 cross_entity | 实测 | axis reason | missing |
|---|---|---|---|---|---|
| CI-A | 2 legacy 文档轮 + 可信共享背景（D04 精确 document/version/unit，提问前从语料冻结） | passed | **passed** | `frozen_targets_match_ok` | — |
| CI-B | 无事实拒答（无检索事件） | 严格空集不可证 → unknown | **unknown** | `model_events_missing`（分支门固定码同时作用于四轴，四轴全 unknown） | `model_events_missing` |
| CI-C | RAG 枚举、双目标 p01/p02 | unknown（fact 与 backing unit 的 entity_key 口径不一致） | **unknown** | `entity_identity_unresolved` | `entity_identity_unresolved` |
| CI-D | RAG 枚举、合同只允许 p01 | violation（p02 越界） | **violation** | `other_entity_used` | `entity_identity_unresolved`（违规不抹掉 unknown） |

- 计数与折叠：`checked+unknown=planned=4`、`checked=passed+NA+violations` 四轴逐项成立；
  `hard_failures_by_kind` = 四轴 violations（cross_entity=1，其余 0）；`hard_failures` 题并集=1
  （CI-D 一题），满足 `max<=union<=sum`；CI-D 违规与 CI-C unknown 未被另一缺失吞掉。
- 卡：`total=4 executed=4 passed=4 errors=0`、`threshold_met=false`、`release_ready=false`、
  无 `production_ready` 键；canonical blocks 与独立重算期望集合逐值一致（6 个 block，含
  `holdout_sample_missing`/`holdout_hard_failure`/`holdout_hard_evidence_missing`/
  `holdout_below_threshold`/`holdout_threshold_unapproved`/`holdout_hard_failure_unverified`）；
  篡改四轴计数会被 `validate_hard_evidence_scorecard` 固定拒绝（`HardEvidenceError`）。
- 独立子进程（`python -B -m mktkb.evaluation.cli p2-hard-evidence-recompute --scope-contract …`）：
  exit 0；卡与进程内重算**逐字节一致**；公开回执 `total/executed/errors/passed/verified/
  release_ready` 与卡一致，`scope_contract_sha256`=合同文件 SHA、`scope_contract_case_count=4`；
  socket 尝试 **0**；禁用模块（`mktkb.rag/qa/conversations/providers`、`product_adapter`、
  `p2_runner/p2_live/p2_scoring`）导入 **0**。

## 3. C3 质量重评分 readiness（PASS，实际重评分 NOT-RUN）

- 5 个回合 `completeness.status=complete`、`scoring_readiness.quality_rescore=true`、
  `reasons=[]`，与 A 契约 §4（four_axis + product available + trace != unavailable）逐值一致。
- 原评分输入可从密文重建：`request_id/message_id/kind/revision/http_status` 齐全；
  `sources[]` 的 `source_id/document_name/version_number/status/locator` 可读回（legacy 2 轮版本 v1）；
  RAG 枚举 2 轮分页原值 `{page:1,page_size:10,total:2,returned:2,has_more:false,next_page:null}`；
  trace 白名单块可读回；检索使用四层计数可读回；`commit_observed.text` 5/5 回合在密文内
  （原始输出文本，公开卡不可见）。
- 开发报告 §3 明确“未执行质量重评分与旧确定性 checks 的逐值比较”，不把 `recorded_status`
  冒充 `rescored_from_original_inputs`，并列入 C10 NOT-RUN：**不冒充，判定成立**。
  真实质量重评分仍 **NOT-RUN**（见 §11）。

## 4. C4 独立反例（14 类，预定义状态/缺失/阻断全部命中，PASS）

日志 `independent/run_ci_negatives.log`（15 行，0 FAIL）。每类都核“预定义固定状态/缺失码”，
CLI 只作附加阻断证据：

| # | 反例 | 预定义结果 | 实测 |
|---|---|---|---|
| N1 | 删除 `runtime_snapshot` | reader 固定拒绝 + CLI≠0 + 不产卡 | `envelope_missing_required:runtime_snapshot`；cli=3；无卡 |
| N2 | 重复 `model_input` 事件 | 该题四轴 unknown + missing 含 `branch_evidence_inconsistent` | CI-A 四轴全 unknown；missing 命中；其余题结论不变 |
| N3 | 单侧模型事件（删 `model_output`） | unknown + `model_events_missing` | 命中 |
| N4 | 坏分页 `returned>total` | reader `runtime_pagination_invalid` + CLI≠0 + 不产卡 | 命中；cli=3；无卡 |
| N5 | 跨 run 绑定（case-plan 改 run_id） | CLI≠0 + `cross_binding_mismatch` + 不产卡 | 命中；cli=3 |
| N6 | 非空原始占位容器 `source_ids=[""]` | unknown + `empty_set_not_proven`（不得 N/A/pass） | 命中 |
| N7 | 正文归属映射错版本（共享 background version_id 改坏） | CI-A unknown `free_text_attribution_unverifiable` | 命中 |
| N8 | scope 合同绑定不符 | CLI≠0 + `scope_contract_binding_mismatch` + 不产卡 | 命中；cli=3 |
| N9 | 缺 scope 合同 | 旧语义 cross_entity passed=0/unknown=4；回执 SHA=null/0 case | 命中（不悄悄 pass） |
| N10 | 快照产品来源版本被改（仅快照） | 采集期 completeness 应含 `runtime_projection_version_mismatch` | 采集期命中；见 §11 残余 1 |
| N11 | 快照使用层与事件不一致 | 采集期含 `runtime_usage_inconsistent` | 采集期命中；见 §11 残余 1 |
| N12 | 快照 trace 与事件不一致 | 采集期含 `runtime_trace_unresolved` | 采集期命中；见 §11 残余 1 |
| N13 | 删必需事件 `claim_observed` | 无 passed + missing 含 `branch_evidence_missing`/`claim_missing` | CI-A 四轴无 passed；其余题不变 |
| N14 | 未知顶层键 | reader `envelope_unknown_keys:*` | 命中 |

- 另：开发 C4 表的 6 类（缺快照/坏分页/重复模型事件/跨 run/缺 scope/非空占位）与我自建 14 类
  的对应项**结论逐值一致**；开发表未覆盖的“单侧模型事件、正文映射错版本、坏合同绑定、
  未知键、必需事件缺失”由本次自建补齐。
- 链级 N/A（真严格空集）：产品 no-fact 拒答未产生显式空检索观察标志，**不可证 → NOT-RUN**
  （分类器层真模板空集可 N/A，A-I/B-I 已覆盖）。未被冒充为 pass。

## 5. C5 新版本正式 CLI 与旧门（PASS）

- 正式入口 `p2-hard-evidence-recompute` 直接消费 v0.3 密文 + `p2-entity-scope/v0.1` 合同，exit 0；
  `--scope-contract` 只在该子命令上，缺省=旧语义（N9 已验证）。
- 子命令 flags 全量扫描：`--addendum/--annotation/--annotation-cipher-sha256/--case-plan/--cases/
  --evidence-dir/--key-file/--manifest/--out/--scenario-contract/--schema/--scope-contract`；
  **无** ignore-code-version / 忽略 hash / 自动改旧计划开关。
- 旧受控入口 `tools/p2_h2_controlled_execute.py` 字节未变（`ad215251…`，与 task-0 基线一致），
  仍含 `run_live_p2`/`open_live_gate`/`code_changed_since_plan` 与 GO/budget/ledger 固定路径、
  `ledger_binding_ok` 门；旧入口测试 **23 passed**（`run_controlled_entry_tests.log`）。
- `cli.py` 未把 `release_ready` 写成 true；公开回执恒 `release_ready=false`。
- **非阻塞观察**：该子命令保留 A 已引入的 `--schema`/`--scenario-contract` “测试用”路径覆盖，
  只影响 annotation 的 schema/scenario 哈希绑定，不属 code-version/hash 忽略类；建议在真实 H2
  前的运行规范中限制其使用（见 §11 残余 2）。

## 6. C6 首错停 / 重试 0 / 不继续下一题（PASS）

- 自建变体（`independent/ci_first_error.py`，9 项全 PASS，`run_ci_first_error.log`）：把 writer
  封存上限压到不可能通过 → 第 1 回合在写盘阶段抛 `EvidenceCaptureIncomplete:evidence_write_failed`；
  `session.blocked=True`、writer `failed`；**模型调用仅 1 次（零自动重试）**；失败回合 0 个
  turn 密文；再次提问 `EvidenceCaptureBlocked` 且 chat 调用数不变（不继续下一题）；
  trace 清理仍执行；manifest 未生成（失败 run 不声称已封存）。
- 复核 A 的 runner 级用例：`test_capture_failure_aborts_actual_runner_and_still_purges`
  **1 passed**（`run_a_runner_failure_test.log`）；该用例断言 `run_p2` aborted、
  `stop_code=adapter_error`、`cases.jsonl` 只有 P01（后续题不执行）、`summary.not_executed=1`、
  chat 阻断、purge 仍执行。
- 合成卡与回执 `release_ready=false`，无 `production_ready`；未把离线检查接成绕过真实资金门的
  production_ready=true。

## 7. C7 明文边界与网络（PASS）

- 合成哨兵（题面内）**只在认证密文**：5 个密文原始字节 0 命中；解密后在合成回合明文出现；
  公开卡、CLI stdout/stderr、公开回执、`public_capture_summary`（固定 17 键）0 命中哨兵/题面；
  公开卡不含任何 case_id/题号。
- 密文/公开摘要边界：公开卡只含固定枚举/计数/SHA/block；公开摘要只含固定键与计数。
- 网络：进程内自建 guard 外部尝试 **0**；独立子进程 socket 尝试 **0**；本评审全程零真实外连。
- 未做宿主全局缓存/预览扫描，未宣称宿主无残余（见 §11）。

## 8. C8 命令、退出码与 collect（PASS，附选择集差异）

环境：仓库根；`.venv/Scripts/python.exe`（Python 3.12.7 / pytest 9.1.1）；`-B`；
`MKTKB_NO_DOTENV=1`；`PYTHONDONTWRITEBYTECODE=1`；`-p no:cacheprovider`；`--basetemp` 在仓外 `%TEMP%`。

| 选择集 | collect | 运行 | 日志 |
|---|---|---|---|
| C 新 E2E `test_p2_capture_entity_readiness_e2e.py` | 4 | **4 passed / exit 0**（9.80s） | `run_c_new_test.log` |
| A 契约 2 文件 + B scope（A/B 新测） | 49 | **49 passed / exit 0**（6.50s） | `run_ab_new_tests.log` |
| 报告 573 选择集（A2+B1+C1+hard_evidence+scorecard+scenarios+eval_tool_repair(+e2e)+model_failure_reason+product_behavior_repair+h2_historical_audit） | **573** | **573 passed / 0 failed / exit 0**（117.79s） | `run_selected_573.log` |
| 补：旧 A `test_p2_evidence_capture.py`+`test_p2_evidence_io.py`+capture e2e | 35 | **35 passed / exit 0**（16.90s） | `run_old_a_capture_io_tests.log` |
| 补：R11 关键信号 `rag/test_query_state.py`+`unit/test_conversations.py` | 57 | **57 passed / exit 0**（1.16s） | `run_r11_signal_tests.log` |
| 补：旧受控入口 `test_p2_h2_controlled_entry.py` | 23 | **23 passed / exit 0**（11.21s） | `run_controlled_entry_tests.log` |
| A runner 失败用例 | 1 | **1 passed / exit 0** | `run_a_runner_failure_test.log` |

- 复现报告的 573 collect/573 pass 与 4/4 C 新测一致（耗时差异属机器状态，不影响结论）。
- **选择集差异（非阻塞）**：开发的 573 选择集未包含“旧 A capture/evidence_io”（C8 明列项），
  亦未重跑 R11/P-R1 定向节点；我补跑了 35 项（旧 A capture/io/e2e）与 57 项 R11 关键信号，
  均全绿。P-R1 定向节点与 R11 全套仍未在 C 复跑 → **NOT-RUN**（见 §11）。

复现命令（仓库根；`$env:MKTKB_NO_DOTENV='1'; $env:PYTHONDONTWRITEBYTECODE='1'`）：

```powershell
# 独立冻结复核（12 对象 / 5 依赖 / 资金 / R11）→ exit 0，ALL_FROZEN_BYTES_OK
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/independent/ci_freeze_check.py
# 自建合成链 64 项（解密/四轴/卡/CLI/哨兵/外连）→ exit 0，TOTAL=64 FAILED=0
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/independent/ci_chain.py
# 14 类反例 → exit 0，NEGATIVE TOTAL=15 FAILED=0
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/independent/ci_negatives.py
# 首错停/重试 0/阻断 → exit 0，FIRST-ERROR TOTAL=9 FAILED=0
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/independent/ci_first_error.py
# C 新测 4 / A+B 新测 49 / 573 选择集 / 旧 A capture-io 35 / R11 信号 57 / 受控入口 23
.venv/Scripts/python.exe -B -m pytest backend/tests/evaluation/test_p2_capture_entity_readiness_e2e.py -q -p no:cacheprovider --basetemp=$env:TEMP\t207-ci-c-new
.venv/Scripts/python.exe -B -m pytest <12 个选择集文件> -q -p no:cacheprovider --basetemp=$env:TEMP\t207-ci-573
```

## 9. C9 逐项判定（任务 / 路径 / 协议版本）

| 任务 | 对象（路径 / 版本） | 判定 | 依据 |
|---|---|---|---|
| C1 同一最终冻结对象 | 12 对象 / v0.3+v0.2+v0.1；A/B 基线 | **PASS** | §1；`freeze-recheck.txt`；0 mismatch；无并发写者 |
| C2 合成链 + 独立进程重算 | `product_adapter`+`p2_evidence_capture`+`p2_evidence_io`+CLI，v0.3 / snapshot v0.1 / classification v0.2 / scope v0.1 | **PASS** | §2；自建解密 5 回合；4 态预声明；CLI 逐字节一致；socket 0、禁用导入 0 |
| C3 质量重评分输入可重建 | `scoring_readiness` / p2-runtime-snapshot v0.1 | **PASS**（实际重评分 **NOT-RUN**） | §3；输入逐项可重建；报告不冒充 rescored |
| C4 坏绑定/坏快照/坏版本/跨 run/非空容器 | `p2_evidence_io` v0.3 + `p2_hard_evidence` v0.2 | **PASS** | §4；14 类反例逐项命中预定义状态/缺失/阻断 |
| C5 正式 CLI 新版本 + 旧门 | `cli.py` / `p2_h2_controlled_execute.py` | **PASS** | §5；已运行；无绕过开关；旧门字节未变 + 23 passed |
| C6 首错停/重试 0/不继续 | `product_adapter` + `p2_runner`（A 用例外） | **PASS** | §6；自建 9 项 + A runner 用例 1 passed |
| C7 明文/网络边界 | 全链 | **PASS** | §7；密文唯一通道；公开产物 0 命中；外连 0 |
| C8 命令/退出码/选择集 | 全部相关测试 | **PASS（选择集差异已补跑）** | §8；4/49/573/35/57/23/1 全绿 |
| C9 独立评审报告 | 本文件 | **PASS** | 按任务/路径/协议版本判定；保留旧失败/返工 |
| C10 真实 H2 前待办/阻断清单 | `report.md` §10 | **PASS（清单完整）** | §10；10 项全覆盖 |

**结论：C = PASS（离线合成范围），词汇 `OFFLINE_PASS_WITH_LIVE_BLOCKERS`。**
没有“合法 gold 全 unknown”（CI-A passed、CI-D violation、两条 unknown 均有固定依据）；
未发现 false pass / false readiness / 冻结字节漂移。

## 10. C10 待办/阻断清单核对（完整）

`report.md` §10 的 10 项与任务书 C10 要求逐项对应，均如实登记、未执行：

| 要求 | 报告 §10 | 结论 |
|---|---|---|
| 隐私残余与主人处置/接受决定 | 10.1（未扫描宿主全局缓存，待办） | 覆盖 |
| 实际隔离保管与未来新 scope 材料接收 | 10.2（私有 targets/scope 未生成；接收/冻结/绑定需单独授权） | 覆盖 |
| 正式私有计划/绑定/新 GO/实时预算核算 | 10.3（未生成、未签发、未预留） | 覆盖 |
| 真实凭据与环境授权 | 10.4（未读取/未验证 .env/provider/key/custody） | 覆盖 |
| M2 RAG live 保护 | 10.5（`rag/facts.py` 未改，裁决 B 维持，live 注入保护未验，风险单列） | 覆盖 |
| 质量重评分 | 10.6（输入可重建已证，逐值比较/`rescored_from_original_inputs` 未执行） | 覆盖 |
| RAG 内部候选 | 10.7（不可观察，`candidate_layer_not_observed`，NOT-RUN） | 覆盖 |
| fact/unit 身份口径 | 10.8（合成链观察到 entity_key 方案不一致，按不可核 unknown，需产品/评测裁决） | 覆盖 |
| 链级 N/A | 10.9（无显式空检索标志，链级不可证；分类器层可达） | 覆盖 |
| 真实 H2 未执行/不宣称 P2 通过 | 10.10 | 覆盖 |

- 建议在真实 H2 前把 §11 的残余 1（快照事后篡改不被重算二次推导）与残余 2
  （`--schema`/`--scenario-contract` 测试覆盖）补入该清单；它们不改变 C 判定。

## 11. 残余 / NOT-RUN / 非阻塞发现

1. **快照字段事后篡改不会在重算阶段二次推导（残余，非 false pass）**：用同一 Fernet key 重签
   `runtime_snapshot` 的产品版本/使用层/trace 后，严格 reader 仍接受、分类器沿用密封
   `completeness`（记录为 complete），重算结果回到基线。但同一 payload 走**采集期**
   `evaluate_completeness` 会分别得到 `runtime_projection_version_mismatch` /
   `runtime_usage_inconsistent` / `runtime_trace_unresolved`（N10–N12 已实测）。即：信任锚是
   “Fernet 认证 + 采集期封存的 completeness”，符合 A 契约 §5 与 B 契约 §7（快照只做采集期
   交叉一致性与 readiness，不参与使用层匹配）；真实 H2 前建议明确“持有 key 者不可信”的边界。
2. `p2-hard-evidence-recompute` 的 `--schema`/`--scenario-contract` 为 A 引入的“测试用”路径覆盖，
   可重定向标注 schema/scenario 哈希绑定；不属 code-version/hash 忽略类，且经 scope/绑定/卡
   严格校验，但有被误用空间，建议运行规范限制。
3. 开发 573 选择集未含旧 A capture/evidence_io，也未重跑 R11 全套 / P-R1 定向节点；本次补跑
   35 + 57，P-R1/R11 全套在 C 仍 NOT-RUN。
4. 链级严格空集 N/A 不可证（报告 C10.9）→ NOT-RUN，非假通过。
5. fact 与 backing unit 的 `entity_key` 口径不一致（报告 C10.8）：合成链按不可核给 unknown，
   真实 H2 前需产品/评测口径裁决；本评审不据此宣称旧 14 题已可判。
6. `c-freeze.txt` 自写时刻晚于 `frozen_utc` 4s（冻结生成动作；被验对象均早于冻结）。
7. A-I 遗留（首轮 v0.3 schema 内新增 `candidate_observation`、R6 归一化、sources 双向核对范围）
   在 A review §10.6/§11.4 有记录；C 未改 A 字节，本评审不重复裁决，仅按最终字节复验其行为
   （C 新测与 573 套件全绿）。
8. 陈旧/未重跑：真实 H2、真实 GO/ledger/预算/凭据/preflight、真实质量重评分、真实 RAG 内部
   候选、真实私有 targets/scope 映射、真实 trace/私有密文、宿主全局缓存扫描、完整历史审计 CLI、
   旧 30 题/旧 14 计数重判 —— 全部 **NOT-RUN**（不属 C 离线范围）。

## 12. 旧失败与返工保留（同一最终对象）

- **A-I 首轮 FAIL（G1–G4）**：产品响应身份缺失仍 complete/quality=true（G1）、RAG 候选层缺
  `candidate_layer_not_observed`（G2）、旧历史审计静默接受 v0.3（G3）、200 空/不可解析 body 仍
  available/complete（G4）。返工 R1–R4 后 65 项 → 最终 67 项独立复验 PASS；最终字节：
  `p2_evidence_capture 601096bc`、`p2_evidence_io 1c16a3da`、`product_adapter c9378f81`、
  capture 契约 `ad2b5a72`。本次以最终字节复核（C 新测/573 套件全绿），不重开旧 FAIL。
- **B-I**：首轮 PASS + 6 项非阻塞；`review-addendum.md` 指出 §2/§3.2/§3.4/§5 四处契约字面残留；
  `review-addendum-2.md` 在 `frozen_utc=22:02:02Z` 确认“仅 classification 契约文档变化
  （`e1d03cb9`→`fb40f90a`），代码/测试字节未变”，逐条对齐。本次核到 B final 4 字节与
  `b-freeze.txt` 一致。
- 所有结论对应同一最终对象：`c-freeze.txt` 的 12 个 SHA256 在本次评审开头/结尾均为同一值。

## 13. 声明

- 确认最终对象字节与停写：12/12 一致、A 7/7、B 4/4、资金 3/3、R11 273/0、staged=0、
  HEAD/分支未变；被验对象 mtime ≤ `frozen_utc`。
- 本评审未修改任何产品源码、开发测试、开发报告或冻结文件；只新增
  `docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/independent/` 与本 `review.md`；
  未 stage/commit/push；零真实外连；未读取真实 H2、私有 key/密文、`.env`、宿主缓存；
  未安装软件。
- C 判定：**PASS（离线合成范围）**，词汇 **`OFFLINE_PASS_WITH_LIVE_BLOCKERS`**；
  **不写** REAL_READY / production_ready / release_ready=true；不启动真实 H2、不进入 T208/T209/T900。
