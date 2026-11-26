# T207-H2-OFFLINE-READINESS 集成离线评审对象报告（任务 C）

- 状态：**C 开发/证据完成；独立评审待做（`review.md` 由独立验收者写，本报告不预填 PASS）**。
- 对象：A 最终冻结（`T207-CAPTURE-CONTRACT-R2/evidence/a-freeze.txt`）+ B 最终冻结
  （`T207-CROSS-ENTITY-SCOPE-R1/evidence/b-freeze.txt`）+ C 新测试与封存清单。
- 边界：真实 H2/GO/ledger/预算/凭据/preflight 全部未执行；只用公共 fixtures、合成题/合同/key/临时库；
  零真实外连；不写 REAL_READY/production_ready/release_ready=true。

## 1. C1 同一最终冻结对象

- A 与 B 的事实源：`a-freeze.txt`（A-I 最终 PASS，frozen_utc 2026-11-13T21:30:22Z）、
  `b-freeze.txt`（B-I 最终 PASS，frozen_utc 2026-11-13T22:02:02Z）。
- C 只新增 `backend/tests/evaluation/test_p2_capture_entity_readiness_e2e.py`（合成链/负例）
  与本报告/证据；未改 A/B 源码、reader、分类器、契约、旧入口。最终清单见 `evidence/c-freeze.txt`。
- 身份约束：合成 case-plan 的 `bindings` 逐值等于认证 envelope 的 16 键绑定；`config_hash` =
  scope 合同文件字节 SHA256；合同 `bindings.run_id/plan_id/plan_sha256` 与 envelope/case-plan
  逐值一致；CLI 回执记录合同 SHA 与 case 数。

## 2. C2 正式格式合成链路（实际装配 + 独立进程）

`test_v03_capture_to_offline_recompute_and_public_card`：

1. 真实 `ProductEvalAdapter` + `MockChatBackend` + 公共 D01/D04；采集显式 v0.3；5 个合成回合
   （2 个 legacy 文档轮、1 个 no-fact 拒答、2 个 RAG 枚举轮，其中 1 轮在独立会话）。
2. 每回合：产品响应 → 观察事件 → 同实例只读 DB 投影 → `runtime_snapshot` → 完整性 → 加密写盘
   → 立即读回校验。
3. 关闭产品实例后 **删除合成 product 目录（业务库/trace/上传件）**；随后所有读回只来自仓外密文。
4. 独立子进程 `p2-hard-evidence-recompute`（零模型/检索/实时 DB）严格读回 + 四轴重算；
   回执/公开卡与进程内重算逐字节一致。
5. 子进程守卫：socket 尝试 0；未导入 `mktkb.rag/mktkb.qa/mktkb.conversations/mktkb.providers/
   product_adapter`（sitecustomize 记录为空）。

预声明 gold（合成合同，不是从答案生成；合同在提问前从语料结构 + 合成 case 冻结）：

| case | 形态 | cross_entity 预声明 | 实测 |
|---|---|---|---|
| RD-A | 2 legacy 文档轮 + 可信共享背景（D04 精确 document/version/unit） | passed | passed |
| RD-B | no-fact 拒答（无检索事件） | 严格空集不可证 → unknown（分支固定码） | unknown（`model_events_missing` 等） |
| RD-C | RAG 枚举、双目标（p01/p02） | unknown（fact.entity_key 与 backing unit.entity_key 方案不一致，不可核） | unknown（`entity_identity_unresolved`） |
| RD-D | RAG 枚举、合同只允许 p01 | violation `other_entity_used`（p02 越界） | violation |

四轴折叠/计数/`missing`/canonical blocks/`release_ready=false` 与卡校验均通过。

## 3. C3 质量重评分

- 已证明：每个 turn 的 `scoring_readiness.quality_rescore=true`，且 `runtime_snapshot` 保全
  产品 kind/request/message/revision、sources 版本、pagination、trace、检索使用分层。
- **未执行**质量重评分与旧确定性 checks 的逐值比较：本包不把 `recorded_status` 冒充
  `rescored_from_original_inputs`；该能力列入 C10 的 NOT-RUN 阻断项，不作为 PASS 声明。

## 4. C4 负例/坏证据（同一链路）

`test_negative_mutations_are_rejected_or_unknown` 实际执行：

| 反例 | 结果 |
|---|---|
| 删除 `runtime_snapshot` | 严格 reader 固定拒绝；CLI 非 0，**不产卡** |
| 坏 pagination（`returned>total`，枚举轮） | 严格 reader 固定拒绝；CLI 非 0，不产卡 |
| 重复 `model_input` | reader 放行，但 turn 级分支门 → 四轴 unknown；`missing` 含 `branch_evidence_inconsistent`，不 pass |
| 跨 run 绑定（case-plan 改 run_id） | `read_encrypted_evidence` 绑定不符 → CLI 非 0，不产卡 |
| 缺 scope 合同 | 旧语义：cross_entity passed=0、unknown=4；回执合同 SHA=null/0 case，不悄悄 pass |
| 非空原始占位容器（`source_ids=[""]`） | 严格空集证明失败 → unknown `empty_set_not_proven` |

另：`test_classifier_level_not_applicable_still_reachable` 证明分类器层真模板空集 + `no_entity_scope`
仍可达 N/A（链路上 no-fact 拒答未产生显式空检索观察标志，故链路级 N/A 为 NOT-RUN，非假通过）。

## 5. C5 新版本入口与旧门

- `p2-hard-evidence-recompute --scope-contract` 可选；缺省旧语义；提供时严格加载并记录文件 SHA/case 数。
- 未新增 any `--ignore-code-version`/忽略 hash/自动改旧计划开关（测试断言）。
- 旧受控入口 `tools/p2_h2_controlled_execute.py` 未改，仍含 `run_live_p2`/`open_live_gate`/
  `code_changed_since_plan`；真实 GO/ledger/预算门未绕开（旧套件 573 项覆盖）。

## 6. C6 首错停/重试 0

- 采集失败首错停：复用 A 已验证的 `test_capture_failure_aborts_actual_runner_and_still_purges`
  （writer 失败 → `run_p2` aborted、后续题不再执行、chat 调用被阻断、seal/purge 仍执行）。
- 本 C 链不接真实 run 门；合成卡 `release_ready=false`，不写 production_ready。

## 7. C7 明文/安全边界

- 合成哨兵只出现在认证密文；公开卡/CLI stdout/stderr/回执 0 命中。
- 公开卡不含 case_id/题面/答案；合同 SHA 与计数为公开安全聚合。
- 子进程 socket 0、禁用模块导入 0、无 `>`/tee/dump 明文导出；证据根/输出均在仓外临时目录。

## 8. C8 实际命令/退出码/选择集

环境：仓库根、`.venv/Scripts/python.exe -B`、`MKTKB_NO_DOTENV=1`、`PYTHONDONTWRITEBYTECODE=1`、
`-p no:cacheprovider`；合成 basetemp 在仓外。

| 选择集 | collect | 运行 |
|---|---|---|
| C 新 E2E（4 项） | 4 | **4 passed** |
| A 契约 2 文件 + B scope + C E2E + hard_evidence + scorecard + scenarios + eval_tool_repair(+e2e) + model_failure_reason + product_behavior_repair + h2_historical_audit | **573 collected** | **573 passed, 0 failed**（129.74s） |
| R11 273 项 / 资金三件套 | — | 0 mismatch / 3 一致 |
| 旧 A/B 独套件（A-I 67 + B-I 103） | — | 分别 67 / 103 passed（A-I、B-I 独立证据） |

未机械全仓重跑；选择集覆盖新增 A/B/C、固定子因、T104/R11 关键信号、旧历史审计与工具链。

## 9. C9 独立评审

待独立验收者写 `docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/review.md`：
按任务/路径/协议版本给 PASS/FAIL/NOT-RUN；缺核心门或合法 gold 全 unknown 不得全包通过。
开发侧不预填 PASS、不代验。

## 10. C10 真实 H2 执行前待办/阻断清单（只登记，不执行）

1. **隐私残余**：本包未扫描宿主全局缓存；真实 H2 前的隐私残余与主人处置/接受决定仍待办。
2. **隔离保管与新 scope 材料**：真实私有 targets/scope 映射尚未生成/更新；未来材料接收、
   版本冻结与合同绑定需单独授权。
3. **正式计划/绑定/新 GO/实时预算**：未生成、未签发、未预留；真实 H2 需新的私有计划、
   plan/GO/ledger 绑定与预算核算（本包不签 GO）。
4. **真实凭据与环境授权**：未读取/未验证真实 .env、provider、holdout key、custody 会话。
5. **M2 RAG live 保护**：`rag/facts.py` 未改；裁决 B 维持现状；live 注入保护未验，风险单列。
6. **质量重评分**：原评分输入可重建已证明，但旧确定性 checks 的逐值比较与
   `rescored_from_original_inputs` 声明仍未执行（NOT-RUN）。
7. **真实 RAG 内部候选**：不可观察，按 `candidate_layer_not_observed` NOT-RUN；不得当空候选。
8. **产品 fact/unit 身份口径**：合成链观察到 RAG fact 的 `entity_key` 与 backing unit 的
   `entity_key` 方案不一致（本包按不可核给 unknown）；真实 H2 前需产品/评测口径裁决，
   不得为追求 checked 增长放宽。
9. **链级 N/A**：no-fact 拒答未产生显式空检索观察标志，链级 N/A 不可证（分类器层可达）；
   真实 run 前需确认产品是否应提供该观察标志或接受该轴 unknown。
10. **真实 H2 执行/验收**：本包未执行、未重跑旧 4 fail/14 unknown；不得宣称 P2 通过、
    旧问题清零或 production_ready。

## 11. 交付停止点

本包完成文件与证据后**暂停**：不签 GO、不启动真实 H2、不进入 T208/T209/T900。
后续由主人安排独立评审/真实准入。
