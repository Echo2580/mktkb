# T209-PREP 报告：执行 / 质量 / 证据 / 软评分 / 资金 分列

## 0. 阅读约定

- 本报告把执行、质量、证据、软评分、资金**分列**，不合成单一 overall success/ready。
- 执行成功不代表质量通过；质量未就绪不代表产品链路失败；unknown 不代表答错。
- 本报告不写正式 gate approved、不建立可发布基线、不查询供应商余额。

## 1. 执行状态

- 轮次: P2-T207-H2-20261114-r1
- 汇总: 4/4 run succeeded；30 题；36 回合；errors=0；retries=0；aborted=0
- 状态: succeeded（执行成功；**不代表质量/证据/发布**）
- 聚合映射: 全部 run succeeded→succeeded；全部 failed→failed；混合/部分→partial；无 run 或全部 not_run→not_run
- r0（base_b0）: succeeded，26 题/32 回合，errors=0, retries=0, aborted=0
- r1（base_b0_plus_v01）: succeeded，1 题/1 回合，errors=0, retries=0, aborted=0
- r2（pre_v05_without_v07）: succeeded，2 题/2 回合，errors=0, retries=0, aborted=0
- r3（post_v05_without_v01）: succeeded，1 题/1 回合，errors=0, retries=0, aborted=0

## 2. 质量状态

- 状态: FAIL（质量未通过/未就绪）
- 通过/总数: 19/30（passed=19, failed=11, errors=0；min_pass=24）
- 安全硬失败: 2
- threshold_met: false
- thresholds_approved: false
- verified: false
- release_ready: false（本模块没有审批路径）
- 场景级 verified: r0=false、r1=false、r2=false、r3=true；单场景 verified=true 只代表该场景，**不外推整体**
- 说明: 质量未通过/未就绪：threshold_met=false 或存在硬失败/错误；release_ready 恒为 false（本模块没有审批路径）

## 3. 证据状态

- missing_evidence_cases: 27
- 四轴 unknown 合计: 38；违例合计: 2
- verified: false

| 轴 | planned | checked | passed | not_applicable | unknown | violations | unknown 原因 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| safety | 30 | 27 | 1 | 24 | 3 | 2 | undetermined（现有证据不足，原因未定） |
| cross_user | 30 | 27 | 27 | 0 | 3 | 0 | undetermined（现有证据不足，原因未定） |
| cross_entity | 30 | 3 | 3 | 0 | 27 | 0 | real_scope_targets_contract_not_generated（真实 scope/targets 合同未生成） |
| stale_source | 30 | 25 | 25 | 0 | 5 | 0 | undetermined（现有证据不足，原因未定） |

- 口径: unknown（不可判）不是答错；27 是缺失证据题数，不是 27 题答错；不得把 unknown 改写成 N-A 或 0。
- 口径: 四轴 unknown 合计是「轴×题」计数，不是去重题数；missing_evidence_cases 才是本轮缺证据题数（27）。
- cross_entity unknown=27 的主因: 真实 scope/targets 合同未生成；这是输入合同缺口，不是产品回答全错。

## 4. 软评分状态

- ragas: NOT_RUN；recorded_status=NOT-RUN；rescored=false；未重评
- ragas 说明: 真实 judge 未授权
- auxiliary: UNKNOWN；recorded_status=unavailable；rescored=false；未重评
- auxiliary 说明: 辅助评分未执行
- 口径: recorded_status 是历史记录，不是本次 rescored；软评分不能抵消确定性硬失败或 safety 违规。

## 5. 资金与版本

- 当前账本: ca9dceb9019790eb6ba4e25cfaf88232915b607d756d0eae21ad7cdf10c6fec9（当前快照；历史 4d80d776bcf25079817f5f7dd8863037c27bc01971b6fa0fe239b432ee55fcc6）
- 当前 GO: c72dc7abf6ba135fb6c53f77c35b40dda34e97cf535d3be212467c6734b27324
- 旧归档 GO: f688ec7efb7e8ddc145ae9fd593a482a85a6e4a764a9d49a09eab4f3fc26ea98（旧归档，只代表其旧时刻：2026-11-14 真实 H2 执行前归档（f688…））
- 账本变化原因: legitimate_spend（合法真实花费，不是源码篡改）
- 供应商余额: 未查询（本报告不查询供应商余额，也不触发产品/模型请求）
- 说明: 当前账本/当前 GO 只代表当前快照；旧归档 GO 行只代表其旧时刻；合法真实花费不是源码篡改；本报告不查询供应商余额，也不触发任何计费动作。

## 6. 来源与回合

- 来源类型: real-h2-aggregate
- 来源文档: docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/real-h2.md
- 计划/轮次: P2-T207-H2-20261114-r1
- code_version: f6c118432a73aa2541c78b9b33c08314bee462b1e1aa70c4391933625b2892ea
- config_sha256: 9cb322863939522d5defb948b8739dd9385a3bf219c7291c5d1e916de3efbd65
- binding_sha256: 291cfec9d99446c88f0063d533c92632cef15594c1f6ce3da2269cef98ae65d4
- 口径: 只引用安全聚合及版本/来源；不读真实 H2 逐题/标签/答案/密文。
- 口径: 跨轮分数不合并；本报告只覆盖 P2-T207-H2-20261114-r1。

## 7. 轴状态（逐轴，无总分）

| 轴 | 状态 | 说明 |
| --- | --- | --- |
| 执行状态 | succeeded | 执行 succeeded 只代表链路完成，不代表质量通过 |
| 质量状态 | fail | 质量 FAIL / 未就绪时不得发布；软评分不抵消确定性硬失败 |
| 证据状态 | incomplete | unknown（不可判）不是答错，不得改写成 N-A 或 0 |
| 软评分状态 | unknown | recorded_status 是历史记录，不是 rescored；软评分不能抵消硬失败 |
| 资金与版本 | snapshot_only | 旧归档行只代表其旧时刻；合法花费不是源码篡改；不查询供应商余额 |

- 再次声明: 本报告不产生 overall success/ready，不代表 T209 正式通过、质量批准或发布就绪。

- publication: publishable=false；release_baseline=false；gate_approved=false
- publication 原因: T209-PREP 分列报告只用于工程准备：不批准阈值、不写正式 gate approved、不建立可发布基线；正式发布需质量门 + 独立审批（仍属 T209 正式阶段）
