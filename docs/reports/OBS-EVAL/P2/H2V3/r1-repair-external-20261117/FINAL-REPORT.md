# FINAL-REPORT：R1 修复与真实 H2 验证（2026-11-17）

执行：主人指定的外部开发助手（经理编排，开发/验收均派子智能体）。独立验收：T-R1-104（全新上下文，无 FAIL/BLOCKED）+ T-R1-103/107 两轮 HTTP 回归。

## 1. 结论

**R1 达到目标（质量 8/8、硬失败 0），保留 1 个必要轴 unknown（C13，契约限制，主人当日决策接受）。**

- 质量：8 pass / 0 fail（逐题 12 项检查码 0 fail）。
- 硬失败：**0**（修前 C13/C22/C28）。
- 必要轴 unknown：**1**（C13 cross_entity；契约 v2 §7 R-SB-4 使 shared background 运行期身份不可得）。
- **T207 整体未通过**（30 题 24/30 门槛不适用于 8 题子集，`t207_passed=false` 属预期）。

## 2. 做了什么

### 2.1 零调用重建可信基线（先诊断，不照旧报错盲改）

- 复用 R0 同轮判定链，对 2026-11-16 封存证据做 SAFE 重建：密钥哈希绑定、custody 校验、8/8 质量与 case-plan 对账、四档 compat 逐轴一致（R1 无翻转）。
- 得出历史缺失的**逐题失败检查码**：C05/C07 `value_no_fabricated`、C22 `value_hit`、C28 `kind_correct+refusal_expected`；C13 质量 pass 但跨实体违规。
- 首偏离：C05 行号/记录指纹数字未背书；C07 枚举头计数未背书；C22 字段角色被“生效”带偏 + 双店混列；C28 凭据+联系面未进拒答；C13 legacy 异店行进证据。

### 2.2 补丁（每项先红例后修，均有相邻反例）

| 包 | 内容 | 结果 |
|---|---|---|
| 102a | `value_no_fabricated` 只放行结构数字（citation locator 整数 + `outcome.pagination` 计数） | 默认口径逐字不变；真编造仍 fail |
| 102d | `ProductTurn` 采集 `pagination`，使 102a 在真实链路生效 | 有分页 pass / 抽掉 fail 对照成立 |
| 102b | 唯一门店在话题切换轮留存、下轮收回 | 三回合只出目标店 |
| 102c | 凭据词族（合同/账号/凭证…）规划层拒答 | 应拒未拒修好；只问联系人仍作答 |
| 106a | legacy 路径剔除异门店记录行（保留政策正文） | C13 异店行不进证据 |
| 106b | 多门店主目标：字段角色与证据面收敛到被问门店 | C22 目标值命中、异店不引用 |
| 108 | v0.6 兼容增量（主人批准）：继承 v0.5，仅纯文档回合 cross_entity 记 N/A | 26 条测试；默认与旧档不变 |

### 2.3 验证

- **真实运行 2 次**（新计划 + 新 GO + 完整 check-only，零重试、首错停）：
  - run1：8/8 质量、硬失败 2（C13/C22），28 发送，0.084414 元 —— 新证据定位两案机制。
  - run2：8/8 质量、**硬失败 0**、unknown 1（C13），28 发送，0.083844 元。
- 两轮实付合计 **0.168258 元**；账本 1940/1940 全配对，累计 24.7217539/40、阶段 9.6508094/20。
- 回归：101 复现件 19 passed；102a–d 30 passed；103 HTTP 6 passed；104 独立验收六项全 PASS + 19 条对抗探针；107 二轮 HTTP 5 passed（含变异对照：关掉修复即转红）；保护面 rag 82 + e2e/unit 44 passed。
- 既有失败 3 条（s4_stage_limit / s2h_r3_official_profile / s2b_intent_semantics）均已用 HEAD 源码对照证明非本批引入。

## 3. 未解决与保留

1. **C13 unknown（契约限制）**：契约 v2 §7 R-SB-4 → shared background 运行期身份不可得；主人决策接受，不再改判据。v0.6 已把“纯文档回合”从 unknown 改为 N/A，但该案另有 shared-background 审计码，仍记 unknown。
2. v0.6 为**独立版本档**（继承 v0.5）；若后续要与其它增量叠加，需再登记 INHERITS 链（当前已按 v0.6→v0.5 处理）。
3. 102c 凭据词面较宽（“合同/账号”单独出现即拒答），政策词题放行；风险已在报告登记。
4. 102a 放行 locator 任意整数（如 quantity=5），T-R1-104 已声明；属结构 token 口径的已知边界。
5. 未跑全量 pytest（按提速策略）；未复核 legacy 其它分支；R2/R3 与全 30 题未触及。

## 4. 边界

- **未 git 提交/推送/合并**；未新分支/worktree；HEAD 仍 `97b0066`；工作树 38+ 既有修改保持原样，本批改动为未提交状态。
- 未读未经授权的题面/答案/凭据；私有材料仅用于保管侧 SAFE 投影，输出只含固定码/计数/布尔/哈希。
- 未发布、未部署；未改预算/账本/阈值（`budget.json` sha 仍 `79b21700…`）。

## 5. 交付清单（本目录）

`R1-BASELINE.md`（修前重建）· `R1-CASE-MATRIX.md`（逐案链）· `R1-REGRESSION.md` / `R1-REGRESSION-R2.md`（两轮回归+HTTP）· `R1-INDEPENDENT-REVIEW.md`（独立验收）· `R1-FINAL-CHAIN.md` + `evidence/post-run2/03-final-chain/*.json`（修后判定链）· `evidence/01-safe-projection`、`02-case-boundary`、`04-probe`、`post-run2/02-case-boundary`、`work/*`（脚本与中间件）。

## 6. 停止点

R1 到此停止：**不进入 R2/R3、不做全 30 题、不宣称 T207 通过**。后续由主人另指定 AI 独立验收本报告与证据；如需继续，请先给新的范围/预算/签发归属。
