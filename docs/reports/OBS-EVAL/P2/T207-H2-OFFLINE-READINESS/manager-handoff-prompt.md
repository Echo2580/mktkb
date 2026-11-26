# T207 交接提示词（给经理，2026-11-14）

> 用途：把 T207 离线交付 + 真实 H2 四状态运行结果，完整交接给下一位项目经理/验收协调者。
> 本文件为公开安全摘要，不含题面/答案/逐题 ID/私有 key。可直接复制下方“提示词正文”。

---

## 提示词正文（复制给经理）

你是 T207 的项目经理/验收协调者。请先读懂以下事实，再安排后续。当前**不是**“P2 已通过”，而是“离线对象已独立验收通过、真实 H2 已跑完但质量未通过”。不要用旧报告或旧 GO 覆盖本轮结论。

### 一、现在的事实状态

1. **T207 离线部分已完成并独立验收**
   - 0 基线/契约 → A 采集契约 → A-I 独立验收 → B cross_entity 归属 → B-I 独立验收 → C 集成离线评审，全部走完。
   - A-I 首轮 FAIL（G1–G4），定向返工后 PASS；B-I 首轮 PASS 后补契约字面收口，最终 PASS；C 独立评审 PASS。
   - 最终词汇：**`OFFLINE_PASS_WITH_LIVE_BLOCKERS`**。没有 REAL_READY / production_ready / release_ready=true。
   - 新契约：`docs/evaluation/p2-hard-evidence-capture-v0_2.md`、`docs/evaluation/p2-hard-evidence-classification-v0_2.md`。
   - A 最终冻结、B 最终冻结、C 最终对象均在 `docs/reports/OBS-EVAL/P2/` 下，代码/测试/契约字节 12/12 复核一致。

2. **真实 H2 已按主人 2026-11-14 指令真实执行**
   - 旧计划因 `code_changed_since_plan` 已失效；已为当前工作树重新生成私有计划 `P2-T207-H2-20261114-r1`（code `f6c11843…`，30 题/36 回合），并为 r0–r3 分别签发绑定该 run 计划的新 GO。
   - 四个 run **全部 succeeded**：30/30 题、36/36 回合 `complete`，零重试、零中止；旧 run 的 `product_service_error` 未复现。
   - 真实发送 108 次；尝试 117 次（9 次单次失败，无重试）；账本结算 **0.2182299 元**；阶段余额约 12.87 元；40 元上限未触碰；资金预留/结果 1:1 配对，无重复、无孤儿。

3. **真实 H2 质量结论：未通过**
   - 整体 `verified=false`、`threshold_met=false`、`release_ready=false`。
   - 30 题中：19 passed、11 failed、0 error；**2 个 safety 硬失败**（r0、r2 各一）；**27 题缺证据**。
   - 四轴合计：safety 1 pass / 2 violation / 3 unknown；cross_user 27 pass / 3 unknown；**cross_entity 3 pass / 27 unknown**；stale_source 25 pass / 5 unknown。
   - cross_entity 的 27 unknown 是**真实 scope/targets 映射尚未生成**，不是采集链失败；不能用合成通过声称旧 14 题已可判。
   - r3 的 `verified=true` 仅限其 1 题场景，不能外推整体。

### 二、资金/GO/账本变化（必须知悉，不要“恢复旧 hash”）

- 旧 GO `P2-LIVE-GO.json`（`f688ec7e…`）已**原样归档**为
  `docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.t207-h2-run-20261114.pre.archived.json`；
  r0/r1/r2 GO 也各自归档；当前固定 GO 是 r3 GO（`c72dc7ab…`）。
- 共享账本因真实花费从 `4d80d776…` 变为 `ca9dceb9…`；`budget.json` 未变（`79b21700…`）。
- 这是主人 2026-11-14 授权的真实 H2 合法副作用；R11 的 271 个产品源码文件仍未变，只有 GO/账本两个资金对象变化。**不要把旧 hash 写回**，也不要用旧 GO 继续跑。

### 三、你接手后的第一优先级

1. **safety 硬失败私有定位**：先做 2 个 safety 违规的逐题私有定位（真实泄漏/注释口径/检索层问题），只输出固定 reason 码与私有 case 索引，不把题面/答案写入公开报告；定位后再决定产品返工或标注裁决。
2. **真实 scope 合同**：生成/验收真实 targets/scope 映射（B 包未来输入），再定向复跑 cross_entity；在合同缺失时保持 unknown，不得放宽。
3. **质量 fail 分诊**：11 题 quality fail 与 27 题缺证据分开处理；质量重评分需先证明原评分输入可重建，再比较旧 checks，不能把 `recorded_status` 冒充 rescored。
4. **定向复跑**：用新计划/新 GO/新预算，不拼接旧分数；复跑前保护本轮密文/卡/回执，不覆盖。
5. **最终质量评审**：另起独立上下文验收，不由开发自审；未达门就停，不用“大部分通过”放行。

### 四、禁止事项

- 不得宣称 P2 通过、production_ready、release_ready=true 或“旧 4 fail/14 unknown 已清零”。
- 不得把旧 15/4/1/6 + 额外 4 题与本轮结果拼接、重算或改写旧历史。
- 不得读取/外传真实 H2 题面、答案、私有 key、私有密文、宿主缓存；公开报告只用安全聚合。
- 不得复用旧 GO/旧计划绕过 `code_changed_since_plan`；不得加 ignore-code/hash 开关。
- 不得进入 T208/T209/T900，除非主人另行授权。

### 五、关键路径

- 真实 H2 记录：`docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/real-h2.md`
- 四 run 证据：`D:\mktkb-p2-t207-h2-20261114\runs\r0..r3\`（card、evidence 密文、seal、run-receipt）
- 离线报告/验收：
  - `docs/reports/OBS-EVAL/P2/T207-CAPTURE-CONTRACT-R2/`（report + review）
  - `docs/reports/OBS-EVAL/P2/T207-CROSS-ENTITY-SCOPE-R1/`（report + review）
  - `docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/`（report + review + c-freeze）
- 冻结清单：`a-freeze.txt` / `b-freeze.txt` / `c-freeze.txt`

### 六、请你向主人交付

1. 一页状态：离线门链结果、真实 H2 四 run 结果、资金/GO/账本变化、当前阻断项。
2. 下一步计划：safety 定位、真实 scope 合同、质量分诊、定向复跑的时间/责任人/验收人。
3. 明确未决项：2 个 safety 硬失败性质、27 个 cross_entity unknown、11 个 quality fail、质量重评分未执行。
