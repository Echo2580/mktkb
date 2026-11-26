# Q1a-2 真实 scope/targets 合同 v1：生成报告（保管 A）

- 状态：**已生成，待保管 B 独立复核**；未冻结、未质量放行、未产生任何运行期四轴证据。
- 本报告只含安全聚合与公开 schema 路径；无题号、题面、答案、目标值、逐题 hash 或交叉表。
- 合同版本：`q1a-scope-targets-contract/v1`；分析身份仍为 Q1a-3 的 `Q1A-RESCORE-20261114-r1`（本包不执行 Q1a-3）。

## 1. 入口自检（先做，后干活）

使用既有受控入口 `tools/p2_h2_controlled_execute.py::load_private_bundle`（内部调用 `load_p2_dataset` 与 `load_scenario_contract`，并按 v0.3 manager acceptance 校验 addendum；未新写解密/dump 工具）。结果为 PASS：

- `dataset_version=P2-HOLDOUT-v2`；`label_version=p2-holdout-v2-2026-11-10`。
- 冻结 30 题 / 36 回合 / 30 个唯一 case；按加载序复算 `cases_sha256=a0ad48c9…c3c3`，与公开 binding 一致。
- v0.2 标注 30 题同序、唯一覆盖；`scenario_counts=base_b0:26, base_b0_plus_v01:1, pre_v05_without_v07:2, post_v05_without_v01:1, unknown:0`。
- v0.2 轴计数：safety 2/28/0、cross_user 30/0/0、cross_entity 28/0/2、stale_source 30/0/0；v0.3 addendum 恰整体替换 4 个 gap 轴（120 轴中 116 轴逐值不变），合并后 cross_entity 30/0/0。
- manifest / cases / source_map / ingest_plan / scenario_contract / schema / v0.2 密文 / v0.2 复核密文 / v0.3 密文 / v0.2 manager / v0.2 review aggregate / v0.3 manager 共 12 项输入 SHA256 与公开记录逐值一致。
- `socket_attempts=0`、`dns_attempts=0`、`provider_entry_attempts=0`。

## 2. 交付物

| 类型 | 路径 | SHA256 / 字节 |
|---|---|---|
| 公开 schema | `docs/evaluation/q1a-scope-targets-contract-v1.md` | `cb1257fac56a68e5eef791c23cffba9d4e915e5e9a840abce7bde5b96e0e4690` |
| 公开聚合 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/annotation-aggregate.json` | `9abfa5f25617b03bb8566b031335610eb66c00d0c6aa0323371a9287143e7089`；25133 B |
| 本报告 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/annotation-report.md` | 本文件 |
| 私有密文 | `D:\mktkb-q1a2-scope-contract\scope-targets-contract-v1.fernet` | `467dbf7706df26f2069a79e2b344b53c0e10c03ff830ed62efff9b5dfd16f461`；47012 B |

私有密文为新目录独占创建，未覆盖任何既有文件；明文只在受控进程内存，未写明文脚本/日志/JSON/临时文件/数据库。

## 3. 合同内容（安全聚合）

- 覆盖：30/30 题、120/120 轴；每轴恰 7 字段（`applicability`、`criterion`、`reason`、`target_refs`、`targets`、`as_of`、`temporal_intent`），逐值等于合并后的 v0.2+v0.3 冻结标注；未新增/删除/改写任何轴语义。
- 四轴适用性：

| 轴 | required | not_applicable | unknown |
|---|---:|---:|---:|
| safety | 2 | 28 | 0 |
| cross_user | 30 | 0 | 0 |
| cross_entity | 30 | 0 | 0 |
| stale_source | 30 | 0 | 0 |
| **合计** | **92** | **28** | **0** |

- `unknown` 总数：0。该 0 来自 v0.2+v0.3 冻结合并标注的既有状态（v0.3 已解析 4 个 gap）；本包**没有**把任何 unknown 改成 `not_applicable`，也没有新增 unknown。
- `basis` 分布（每轴恰 1 个固定 code）：

| basis | 计数 |
|---|---:|
| `frozen_label_target` | 21 |
| `frozen_question_scope` | 62 |
| `public_corpus_structure` | 32 |
| `case_business_date_baseline` | 5 |
| `no_provable_basis_keep_unknown` | 0 |
| **合计** | **120** |

- 按轴：

| 轴 | basis 分布 |
|---|---|
| safety | `frozen_label_target` 2；`frozen_question_scope` 28 |
| cross_user | `frozen_question_scope` 30 |
| cross_entity | `frozen_label_target` 19；`frozen_question_scope` 4；`public_corpus_structure` 7 |
| stale_source | `public_corpus_structure` 25；`case_business_date_baseline` 5 |

- 4 个 v0.3 gap 轴的 `basis` 逐值保留：2×`case_business_date_baseline`、1×`frozen_label_target`、1×`frozen_question_scope`；其余 116 轴只新增 basis 来源分类，轴值不变。
- basis 赋值规则是确定性优先级（v0.3 gap 例外 → unknown 保留 → 按轴/`criterion`/refs/targets/as_of 分类），完整规则在公开 schema §4；`basis` 只作来源分类，不参与 pass/fail 折叠。

## 4. 绑定（旧 run 只读）

- 旧 run binding payload `291cfec9…65d4`（复算一致）；文件 `3108b87b…75ee`。
- 4 个旧 run 的 `run_id` / `plan_id` / `plan_sha256` 逐值绑定，按 `run_index=0..3` 与场景顺序排列；未改写旧 binding。
- 题集/标签/场景：`dataset_version=P2-HOLDOUT-v2`、`label_version=p2-holdout-v2-2026-11-10`、`cases_sha256=a0ad48c9…c3c3`、`scenario_contract_sha256=39c7e161…74ad`。
- 标注来源：v0.2 密文 `3d60c273…e4d0`、v0.2 复核密文 `963918ff…a2c3`、v0.3 addendum `80a8c4a1…9b2f`；v0.2/v0.3 密文与已接收报告均未覆盖。

## 5. 输入保全

- 49 项保护件（C 冻结 12、资金 3、H2 questions/labels 密文与 manifest、v0.2/v0.3 密文与公开报告、旧 run binding、4×card、4×case-plan、4×receipt、4×seal-manifest、4×evidence manifest）**before/after 逐项 SHA256 全等**；无缺失、无变更。
- C 冻结 **12/12** 一致；`p2_hard_evidence.py=fba6e606…` 未改；`p2_h2_historical_audit.py=e95e1b39…` 未改。
- 资金：ledger `ca9dceb9…`、budget `79b21700…`、GO `c72dc7ab…` 前后一致（与 c-freeze 参考的差异为既有状态，本包未写）。
- 仓库：分支 `codex/p2-e2e`、HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`、暂存区空；开工 216 项（15 tracked modified + 201 untracked）在收尾时按集合逐行不变。
- 收尾新增 untracked 仅：本包 3 个公开文件 + Q1a-1b 并行产生的 3 个开发文件（`p2_evidence_rescore_axes.py`、`test_p2_evidence_rescore_axes.py`、`p2-evidence-rescore-v0_2.md`）；保管 A 未读取、未修改后者，也不计入本包产物。

## 6. 零真实调用与边界

- 零真实调用：network=0、socket=0、DNS=0、provider=0、model=0、retrieval=0、embedding=0、rerank=0、OCR=0、judge=0、product_tests=0、real=0、reservation=0、new GO=0。
- 未读 `.env`、runbook、T207 scoring、真实产品回答/trace/评分/旧助手会话；未从答案反推 scope/targets；未派子助手。
- 未 stage/commit/push/合并/部署；未新建 worktree/切分支；未启动服务。
- 公开产物隐私扫描：3 个公开文件、135 个 needles（30 case_id、题面、标签值、target 身份/类型/过滤值）；`sensitive_hits=0`、`key_material_hits=0`；仅 3 个 substring-only 命中，均为公开 schema 词或 4 字符类型作为更长 token 的子串。
- 合同不产生 `checked` / `passed` / `violations` / `verified` / `threshold_met` / `release_ready`；不授权真实 H2。

## 7. 未验证项与残余

1. **待保管 B 独立复核**：逐题 30/30、逐轴 120/120、7 字段、basis、绑定、密文 SHA256；复核前不得当作质量通过或真实运行依据。
2. 合同尚未被 Q1a-1b 的 matcher/适配器实际消费，也未在 Q1a-3 的真实旧 evidence 上运行；消费可行性未验证。
3. 运行期 cross_user owner、cross_entity 实体/记录身份、stale_source 实际日期使用、全局禁值禁源仍未验证；`0 unknown` 不代表运行期证据充分。
4. `basis` 只是来源分类，不是质量结论；合同本身不证明任何真实产品行为正确。
5. 未证明 T207/Q1A 通过；未产生 release/threshold 结论。

## 8. 过程偏差（如实披露）

- 入口使用既有组合受控入口 `load_private_bundle`，而非直接逐个调用三个 loader 模块；该入口内部仍只调用 `load_p2_dataset` 与 `load_scenario_contract`，并以 v0.3 acceptance 校验 addendum。未新造 dump/解密工具；入口与依赖文件 SHA256 已记录在聚合的 `entry_files`。
- `basis` 是本次新增的投影分类，不改变冻结轴值；v0.3 的 4 个 gap 轴 basis 原样保留。
- 合并后 `unknown=0` 是冻结标注的既有状态，不是本包升级或降级。
- 首次聚合状态对比按字节 newline 计算导致误报“不一致”；改为按 status 行集合与 canonical 排序 hash 复核，确认 216 项既有行不变。
- 并行 Q1a-1b 新增 3 个 untracked 开发文件；本包未触碰，收尾按集合排除后核对既有 216 项。

## 9. 结论

合同 v1 已写入仓外新密文，公开 schema 与安全聚合已就位；30/30 覆盖、120/120 轴、0 unknown、basis 分布与 49 项输入保全均自核通过。**下一步：保管 B 独立复核；复核前停止，不进入 Q1a-3，不宣称质量通过。**
