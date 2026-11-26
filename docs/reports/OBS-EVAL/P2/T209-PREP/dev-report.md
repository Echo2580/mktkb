# T209-PREP 开发自测报告（报告分列 + candidate/blocked 归档/校验/恢复）

- 任务：P2-T209-PREP（E2 离线工程准备），不批准阈值、不建立可发布真实质量基线。
- 仓库/分支/HEAD：`D:/GPT项目/市场部AI知识库` / `codex/p2-e2e` / `97b0066726e5b8d6f94cbc0b63a890084550c106`。
- 结论：**D1 定向返工完成，开发自测通过**；独立复验与经理接收由验收/经理执行，本报告不代写独立结论，
  不写 `T209_PREP_PASS`，不声称正式 T209 通过。
- 真实质量门保持失败：19/30、11 fail、2 safety、27 缺证据、`threshold_met=false`、`verified=false`、`release_ready=false`。

## 1. 范围与边界

- 只做 E2 允许的两项能力：①执行/质量/证据/软评分/资金**分列报告**；②candidate/blocked 的
  `archive→verify→restore→list/diff` 离线编排。
- 零真实产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额调用；零新增真实预留/付费/GO；
  不启动服务；不读 `.env`、真实 H2 逐题/标签/答案/私有密文/key/保管会话；不查询供应商余额。
- 未改动 E0 安全分诊、E1 T208 六个冻结对象、C 冻结 12 对象、`docs/evidence/LOCAL-R1-20261101/**`、
  生产锁、正式 baseline / 真实报告；未 stage/commit/push/reset/clean/切分支/worktree。
- 新增文件仅 2 个代码/测试文件 + 本报告目录；既有 `report.py` / `baseline.py` / `gate.py` 与
  四个既有测试文件 **0 字节修改**（hash 见 §8）。

## 2. 接口对账：复用与未改理由

| 既有接口 | 本包用途 | 是否修改 |
|---|---|---|
| `baseline.archive_baseline` / `verify_archive` / `restore_baseline` | 候选归档的 `payload/` 原样复用其证据链（身份六要素、产物摘要、gate/approval 绑定、holdout 拒绝、目标已存在拒绝） | 否 |
| `baseline.BaselineIdentity` / `load_baseline` / `gate_result_digest` | 身份重算、恢复后复核、审批/门禁摘要语义 | 否 |
| `report.diff_runs` / `require_release_baseline` | 验证“候选恢复出的 baseline 仍未审批、不能成为 release baseline” | 否 |
| `gate.GateResult` / `QualityResult` / `load_gate_config` | 仅测试夹具构造当前 gate 与默认配置；新模块不重算正式门禁 | 否 |
| `tests/evaluation/test_report.py` 等四个文件 | 复用其合成 run 构造与既有回归基线 | 否 |

**为什么新增 `backend/src/mktkb/evaluation/p2_candidate_report.py` 而不是改三个既有模块：**

1. 既有 `report.py` 的公开语义是「单个 RunDiff + GateResult 的报告」，其字段与默认行为被
   P0/P1/T205 多处依赖；把“五轴分列 + 无 overall”塞进去会改变其单一报告语义并扩大回归面；
2. 候选归档需要新的 manifest 契约（`publishable/release_baseline/gate_approved` 恒为 false、
   状态由报告事实派生、payload 摘要清单），不属于 baseline 的“已审批 release 证据”语义；
3. 新模块以组合方式调用既有归档/恢复函数，既有默认语义、错误码与 schema 全部不变；实测四个
   既有测试文件 80 passed，零回归（§4）。

## 3. 实现摘要

### A. 分列报告（`p2_candidate_report.py`）

- `ExecutionStatus`：run 级 `succeeded/failed/partial/not_run`、题数/回合/errors/retries/aborted；
  `succeeded` 只表示链路完成，渲染时强制注明“不代表质量/证据/发布”。
- `QualityStatus`：total/passed/failed/errors/safety、`threshold_met`（`total==30 and passed>=min_pass`）、
  `thresholds_approved`、`verified`、`release_ready`（**结构常量 false**）、`status`（fail/not_ready/pass）、
  场景级 verified 列表。`verified=true` 必须所有场景 verified 且证据完整，否则拒绝构造。
- `EvidenceStatus`/`AxisEvidence`：真实四轴 `safety/cross_user/cross_entity/stale_source`，
  planned/checked/passed/not_applicable/unknown/violations 与 unknown 原因码；计数必须自洽。
- `SoftStatus`：Ragas/auxiliary 的 `status`、`recorded_status`、`recorded_scores`、`rescored`、
  `rescored_scores`、`rescored_reason`；未重评时禁止携带 rescored 分数；`not_run` 禁止携带分数。
- `FundingStatus`：当前账本/当前 GO/旧归档 GO 分列；`archived_scope=historical_archive`；
  `provider_balance_queried` 必须 false；账本变化只允许记 `legitimate_spend`。
- `SplitReport`：五轴 + `publication`（三项 false）。`to_dict()` **没有** `overall_success/ready`；
  `from_dict()` 严格重校验并做 canonical 等值，拒绝未知字段、派生字段漂移与题干/标签/逐题明文字段。
- `parse_card()`：解析与 `p2_hard_evidence.aggregate_holdout` 同构的公开聚合卡；拒绝
  `release_ready=true`、`detail_export=true`、`threshold_met` 与计数不一致、四轴计数不自洽。

### B. candidate/blocked 归档

- 布局：`<out>/candidate_manifest.json` + `<out>/payload/`（既有 baseline archive 原字节）。
- manifest 字段集合固定（18 项，见 `CANDIDATE_MANIFEST_KEYS`）：`publishable/release_baseline/
  gate_approved/has_approval` 恒 false；`state` 由报告事实派生（有硬失败/未达阈值/证据缺失/unknown
  → `blocked`，否则 `candidate`），调用方不能自带 state/publishable 参数。
- `archive_candidate`：源 baseline 必须**未审批**；holdout、已审批源、已存在目标、正式 registry/
  受保护证据目录一律拒绝；先写暂存目录并自校验，通过后才上架。
- `verify_candidate_archive`：manifest 精确字段/类型、payload 文件集合与 SHA256、内层
  `verify_archive`、identity/run_id/suite/审批关系、report canonical 摘要、state 派生一致性；
  符号链接/Windows junction 一律拒绝。
- `restore_candidate`：先 verify，再拒绝正式 registry、归档内部、已存在目标；恢复只重写
  `baseline.json.run_dir`；恢复后复核 approval is None、identity/run_id 一致，失败回滚。
- `list_candidates` / `diff_candidates`：只读、确定性排序；diff 永不求和/合并分数，
  跨轮或跨 pipeline/scope/dataset 身份标为不可比（`scores_comparable=false`）。

## 4. 红绿与命令/计数

工作目录均为 `D:\GPT项目\市场部AI知识库`；环境均含
`MKTKB_NO_DOTENV=1 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8`，pytest 均带
`-p no:cacheprovider`。

### 4.1 先红（实现前真实输出）

- 命令：`.venv\Scripts\python.exe -m pytest backend/tests/evaluation/test_p2_candidate_report.py -p no:cacheprovider -q`
- 结果：**exit_code=1，1 error during collection**：
  `ImportError: cannot import name 'p2_candidate_report' from 'mktkb.evaluation'`。
- 证据：`evidence/01-red.txt`（原始红输出；meta 为绿灯后补注，正文未改）。

### 4.2 转绿（定向）

| 命令（省略公共 env/flag） | 结果 | exit | 证据 |
|---|---|---|---|
| `pytest backend/tests/evaluation/test_p2_candidate_report.py -q` | **40 passed**, 1 warning | 0 | `evidence/02-green-new.txt` |
| `pytest test_report.py test_baseline_portability.py test_diff_release_gate.py test_p2_gate.py -q` | **80 passed**, 1 warning | 0 | `evidence/03-green-existing.txt` |
| 新文件 + 四个既有文件 `--collect-only -q` | **120 tests collected**（40+80） | 0 | `evidence/07-collect.txt` |
| `pytest ...test_p2_candidate_report.py -v` | 40 PASSED（逐项矩阵） | 0 | `evidence/06-tests-verbose.txt` |

未跑全仓测试、未装浏览器/新依赖、未启动服务。

### 4.3 D1 定向返工（执行失败被误述为未执行）

- **D1 现象（验收上下文发现）**：`build_execution` 在 4 个 run 全部 `failed` 时把聚合
  status 算成 `not_run`；`ExecutionStatus.failed` 枚举不可达；独立证据为
  `docs/reports/OBS-EVAL/P2/T209-PREP/independent/09_edge_probe.txt`
  （`all_failed_aggregate_status=not_run`、`failed_status_reachable_by_builder=False`）。
- **根因**：旧聚合公式 `succeeded==len ? succeeded : succeeded==0 ? not_run : partial` 把
  “没有任何 succeeded”等同于“未执行”，既没有 `failed` 分支，又因 builder 拒绝空 runs
  使真正的 `not_run`（0 run）也不可达；语义把“执行失败”和“未执行”混为一谈。
- **修复**（只改执行聚合与渲染，不动其他语义）：

  | 输入 | 聚合 status |
  |---|---|
  | 全部 run `succeeded`（且 errors/aborted=0） | `succeeded` |
  | 全部 run `failed` | `failed` |
  | 混合（含 partial/部分未开始） | `partial` |
  | 0 run | `not_run` |
  | 全部 run `not_run` | `not_run` |

  `failed_runs` 只计显式 `failed`（以及标记 succeeded 但带 errors/aborted 的异常 run）；
  builder 现在接受空 runs 表示“未开始”，`to_dict`/`from_dict` 往返保留空列表；
  渲染状态文案按枚举显示“执行成功/执行失败/执行部分完成/未执行”，并新增聚合映射行。
- **新增回归**（`test_p2_candidate_report.py`）：
  - `test_execution_aggregate_status_mapping[runs0-succeeded]`：4 succeeded→`succeeded`；
  - `test_execution_aggregate_status_mapping[runs1-failed]`：4 failed→`failed`（不是 `not_run`）；
  - `test_execution_aggregate_status_mapping[runs2-partial]`：2 succeeded+2 failed→`partial`；
  - `test_execution_aggregate_status_mapping[runs3-not_run]`：全部 not_run→`not_run`；
  - `test_execution_aggregate_status_mapping[runs4-not_run]`：0 run→`not_run`；
  - `test_failed_execution_report_renders_failed_not_not_run`：报告渲染
    `状态: failed（执行失败…`、含聚合映射行、不得出现 `状态: not_run`，`to_dict` 的
    execution/axes 均为 `failed`。
- **红→绿**：修复前该子集 4 failed、2 passed（`evidence/12-d1-red.txt`，exit 1）；
  修复后 6 passed（`evidence/13-d1-green.txt`，独立探针
  `all_failed_aggregate_status=failed`、`failed_status_reachable_by_builder=True`、
  混合=`partial`、0 run/全 not_run=`not_run`）。
- **旧→新 hash**（SHA256）：
  - `p2_candidate_report.py`：`d9d67c4467…3349bf` → `597be014f67ecb13…5b41405`；
  - `test_p2_candidate_report.py`：`c6ec2fdd21…fc8d41` → `f1edcaed7a50b416…0e46811`；
  - 本 `dev-report.md` 旧 hash `25aeec6f2d…f18f4eefd`；新 hash 以 `11-freeze.txt` 为准。

## 5. 报告分列示例（合成镜像，只含公开聚合计数）

`evidence/04-report-example.md` 由 `evidence/render_example.py` 生成（合成镜像：四 run succeeded、
30 题/36 回合、19/30、11 fail、2 safety、27 缺证据、cross_entity 27 unknown）。关键输出：

```text
## 1. 执行状态
- 汇总: 4/4 run succeeded；30 题；36 回合；errors=0；retries=0；aborted=0
- 状态: succeeded（执行成功；**不代表质量/证据/发布**）
- 聚合映射: 全部 run succeeded→succeeded；全部 failed→failed；混合/部分→partial；无 run 或全部 not_run→not_run

## 2. 质量状态
- 状态: FAIL（质量未通过/未就绪）
- 通过/总数: 19/30（passed=19, failed=11, errors=0；min_pass=24）
- 安全硬失败: 2
- threshold_met: false
- verified: false
- release_ready: false（本模块没有审批路径）
- 场景级 verified: r0=false、r1=false、r2=false、r3=true；单场景 verified=true 只代表该场景，**不外推整体**

## 3. 证据状态
- missing_evidence_cases: 27
- 四轴 unknown 合计: 38；违例合计: 2
| cross_entity | 30 | 3 | 3 | 0 | 27 | 0 | real_scope_targets_contract_not_generated（真实 scope/targets 合同未生成） |
- 口径: unknown（不可判）不是答错；27 是缺失证据题数，不是 27 题答错；不得把 unknown 改写成 N-A 或 0。

## 4. 软评分状态
- ragas: NOT_RUN；recorded_status=NOT-RUN；rescored=false；未重评
- auxiliary: UNKNOWN；recorded_status=unavailable；rescored=false；未重评

## 5. 资金与版本
- 当前账本: ca9d…（当前快照；历史 4d80…）
- 当前 GO: c72d…
- 旧归档 GO: f688…（旧归档，只代表其旧时刻）
- 账本变化原因: legitimate_spend（合法真实花费，不是源码篡改）
- 供应商余额: 未查询
```

对应验收点：

- **无单一总体成功/就绪**：`to_dict()` 只有 `report_kind/axes/publication` 等五轴字段，无
  `overall_success/overall/ready`；渲染串含“不合成”且不含“总体通过/全部通过”。
- **质量 FAIL/未就绪**：19/30 未达 24、2 safety、`threshold_met=false`、`verified=false`、
  `release_ready=false`。
- **单 scenario 不外推**：构造 `verified=true` + 仅 r3 true 会抛
  `整体 verified=true 不能由单个 scenario verified=true 外推`；真实镜像整体为 false。
- **缺 scope ≠ 27 题答错**：quality `failed=11`，evidence `missing=27`；渲染明确
  “27 是缺失证据题数，不是 27 题答错”，并注明四轴 unknown 合计是「轴×题」计数。
- **recorded_status ≠ rescored**：软评分逐项打印 `recorded_status=...；rescored=false；未重评`；
  `rescored=true` 但无 rescored 分数/原因会被拒绝。
- **跨轮不合并**：`build_split_report` 要求 execution/quality/evidence/reference 同一 round/plan，
  不同 round 抛“跨轮分数不得合并”；`diff_candidates` 跨轮 `scores_comparable=false`。
- **资金行分列**：当前账本 `ca9d…`、当前 GO `c72d…`、旧归档 `f688…` 三者分开；旧行只代表旧时刻；
  合法花费不写成源码篡改；不查询供应商余额（`provider_balance_queried` 仅接受 false）。

## 6. candidate 不可发布证据

`evidence/05-chain-demo.txt`（系统临时目录，非仓库/非正式 registry）完整链路输出：

```text
source_baseline=1967b1addd51 run=run-t209-synthetic approved=False
report_state=candidate
archive state=candidate publishable=False release_baseline=False files=5
verify state=candidate baseline_id=1967b1addd51 has_approval=False files=5
restore state=candidate run=run-t209-synthetic approval_is_none=True baseline_is_approved=False
list count=1 candidate-a:candidate:publishable=False
diff same_identity=True same_round=True files_changed=0 scores_comparable=True score_merge_allowed=False
tamper_rejected=candidate_manifest.publishable 必须为 false（candidate/blocked 不可发布）
chain_demo=OK
```

结构性不可发布证据：

1. manifest 的 `publishable/release_baseline/gate_approved/has_approval` 必须为 false（写入即 false，
   verify 强制校验；额外字段 `approved` 亦被字段集合拒绝）；
2. 源 baseline 已审批 → 拒绝归档；候选 manifest/payload 出现 approval → 拒绝；
3. `restore_candidate` 后 `load_baseline(...).approval is None`、`approved=False`，无 `approval.json`；
4. 对恢复出的 baseline 调 `diff_runs(...gate=exit0...)` → `release_allowed=false`，
   `release_blocked_reason=baseline_unapproved`，`require_release_baseline` 抛错；
5. `approve_baseline` 被 monkeypatch 成 boom 时链路仍通过，证明流程从不调用审批；
6. 取消态由报告事实派生（quality fail → blocked），只改 manifest `state` 会被
   “与报告事实派生状态不一致”拒绝；改报告则 canonical/摘要校验拒绝。

## 7. 反例（fail-closed）矩阵

`evidence/06-tests-verbose.txt` 为逐项 PASSED 清单；以下均为合成输入、严格拒绝且不留下半成品。

| 反例 | 测试 | 观测拒绝点（关键词） |
|---|---|---|
| 同 gate 版本但配置变化 / 旧 gate 复用 | 既有 `test_diff_release_gate.py::test_same_gate_version_but_changed_config_blocks_old_gate_result`、`test_config_drift_after_approval_blocks_release`；`test_p2_gate.py::test_same_gate_version_config_change_is_hard_block` | `gate_config_drift` / `baseline_gate_config_drift` / hard block（既有链，未改） |
| 陈旧 / 跨 scope / 跨 pipeline 结果 | `test_diff_between_archives_of_different_rounds_is_not_score_comparable`、`test_diff_between_archives_of_different_pipeline_is_not_comparable`；既有 `test_report.py::test_diff_cross_version_is_rejected_by_default` | 跨轮“不得合并”；跨身份 `scores_comparable=false`；跨版本默认拒绝 |
| 缺 artifact | `test_verify_rejects_missing_artifact`；既有 `test_archive_rejects_missing_run_artifact` | 文件集合不符 / 缺产物 |
| 缺/伪造审批 | `test_archive_refuses_approved_source_and_writes_nothing`、`test_verify_rejects_metadata_upgrade_or_state_flip[has_approval]`；既有 `test_restore_without_approval_is_not_approved` | 已审批源拒绝；`has_approval=false` 强制；缺审批不冒充 |
| 路径逃逸 | `test_verify_rejects_inner_manifest_path_escape` | `archive_manifest 文件路径非法` |
| 重解析（Windows junction） | `test_verify_rejects_reparse_point` | `不允许符号链接/重解析点`（未 skip，实跑 PASSED） |
| 覆盖旧目录/目标已存在 | `test_archive_refuses_existing_target_without_touching_it`、`test_restore_refuses_existing_target`；既有 `test_restore_refuses_existing_baseline_or_run_target` | 目标已存在，拒绝覆盖 |
| 正式 registry / 受保护证据目录 | `test_restore_refuses_formal_registry_root_and_inside_archive` | `位于正式 registry 或受保护证据/报告目录内` |
| 摘要漂移（payload） | `test_verify_rejects_payload_digest_drift` | `sha256 与清单不符` |
| 摘要漂移（report） | `test_verify_rejects_report_digest_drift` | `report 摘要漂移` |
| 元数据抬升（publishable/release_baseline/gate_approved/额外 approved/state 翻转） | `test_verify_rejects_metadata_upgrade_or_state_flip[...]`（6 参数） | 对应字段必须 false / 字段集合不符 / state 派生不一致 |
| 导出 H2 题干/标签/逐题明文 | `test_report_rejects_private_per_case_payload`、`test_archive_refuses_holdout_source`、`test_card_release_ready_true_or_detail_export_is_rejected` | 题干/标签字段拒绝；holdout 拒绝；`detail_export=true` 拒绝 |
| 未登记额外文件 | `test_verify_rejects_unregistered_extra_file` | 文件集合不符 |
| 无样本计数矛盾 / 阈值伪造 | `test_card_threshold_met_must_match_counts` | `threshold_met` 与计数不一致
| 发布就绪伪造 | `test_card_release_ready_true_or_detail_export_is_rejected` | `release_ready` 必须 false |

## 8. 保护件（开工前/完工后一致）

- 快照：`evidence/00-protected-pre.txt`（开工前）与 `evidence/09-protected-post.txt`（完工后）；
  逐行比较：**67/67 行，changed_lines=0，RESULT=IDENTICAL**（`evidence/10-protected-compare.txt`）。
- 显式 SHA256（摘录，完整见快照）：
  - 账本 `ca9dceb9…fec9`；budget `79b21700…b1a9e`；当前 GO `c72dc7ab…7324`；
    旧归档 GO `f688ec7e…ea98`；
  - 生产锁 `requirements.lock e7c09cb8…ff49`、`requirements-dev.lock 2e8a23b1…9881`；
  - 正式 baseline `bc6f6f906db1/baseline.json 1924faf8…`、`approval.json 80113647…`；
  - 复用模块 `report.py 48b76efc…`、`baseline.py b3162edd…`、`gate.py 7e54fbf6…`；
  - C 冻结 12 项全部一致（`c_freeze_items=12`，逐项 hash 与 `c-freeze.txt` 相同）；
  - E0 六文件、E1 五文件（含 ragas 锁）逐项 hash 一致；`real-h2.md 6a8bde93…`。
- 大目录仅做元数据指纹（相对路径+字节数+mtime_ns），**不读取文件内容**，避免触碰私有逐题/密文边界：
  `docs/evidence/LOCAL-R1-20261101`（48,814 files / 5,102,939,498 bytes）、
  `T207-H2-OFFLINE-READINESS`（22 files）、`T208-OFFLINE`（90 files）三者前后指纹一致。

## 9. 零真实调用 / 零预留

- 新测试 40 项全部挂 `acceptance.support.netguard.t09_network_guard`：任何外部 socket/DNS/httpx
  尝试都会使测试失败；`-k zero_external` 单独 PASSED。
- 独立解释器探针在 import 前替换 `socket.create_connection/getaddrinfo/socket.connect` 并断言
  0 次尝试（`test_import_and_report_path_make_zero_external_attempts`）。
- 新模块源码扫描 `httpx|requests|urllib|openai|deepseek|anthropic|socket|urlopen|score_ragas|
  product_adapter|QaEngine`：**0 行命中**（`evidence/08-zero-real-calls.txt`）。
- 未查询供应商余额、未读 `.env`、未启动服务、未新增依赖、未写正式 ledger/GO、未产生真实预留。

## 10. 冻结清单

- 路径：`docs/reports/OBS-EVAL/P2/T209-PREP/evidence/11-freeze.txt`。
- 覆盖：本包新增的 1 个模块、1 个测试、本报告、`evidence/` 下全部脚本/文本/示例
  （含 D1 返工证据 `12-d1-red.txt`、`13-d1-green.txt`），共 20 个对象；
  清单自身因自引用不可能列入，文件头注明。既有文件 0 改动（§2/§8 已证）。

## 11. NOT-RUN / 残余未知

1. 真实 H2 逐题、私有 run 目录、密文/key、保管会话、供应商余额均 **未读取/未查询**；
   报告只引用 `real-h2.md` 的公开安全聚合与版本/来源。
2. 真实 run card **未直接消费**（在私有目录）；示例用与其同构的合成镜像卡验证解析与分列，
   正式阶段需用真实聚合卡重放。
3. 候选归档的 report 是轮次级聚合，payload 是具体 run 证据；manifest 分别绑定 payload 身份/摘要
   与 report 摘要，但不校验“该 run 是否属于该轮四 run 集合”（无公开绑定字段）；正式 T209 需要
   由正式 run/计划提供该绑定。
4. candidate manifest 无外部签名：能证明“与建立时字节一致”并结构性拒绝发布，不能证明建立者
   当时输入的事实为真；真相证明依赖正式 run、审批与独立验收。
5. `docs/evidence/LOCAL-R1-20261101/**` 仅做元数据指纹（5.1GB/48,814 文件），未做全树内容 hash；
   原因是不读取私有证据内容。显式资金/GO 文件已逐字节 SHA256。
6. 本机 Windows 普通符号链接需管理员权限，重解析反例用 junction 实测（PASSED）；POSIX symlink
   未在本机执行。
7. 未新增 HTML 渲染或 candidate CLI（本包未要求）；既有 `render_html`/CLI 未改。
8. E0/T208/T209 正式状态：E0 安全分诊与 E1 T208 仅作为保护对象核对，本次不重开；
   T209 正式阈值批准、正式 release baseline、H2 复跑仍 **NOT-RUN**，质量门保持失败。

## 12. 判定

A/B 功能、坏输入 fail-closed、候选不可发布、既有相关测试不回归、零真实调用、保护件/冻结清单
均满足；D1（all-failed→not_run）已按定向返工修复并加回归，记为：
**D1 返工后开发自测通过，待独立复验**。不构成独立验收、不构成正式 T209 通过，也不改变
H2 `24/30 + 硬失败 0` 标准或任何真实质量结论。验收上下文的 `independent-review.md` /
`independent/**` 未由本包修改或代替。
