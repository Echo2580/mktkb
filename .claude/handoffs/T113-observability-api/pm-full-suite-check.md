# T113 全量环境恢复复跑（PM 记录，非验收方判定）

> 用途：补齐独立验收 `review.md` §3 的「全量 0 failed」环境缺口。PM 材料，随簿记入库；**不改变验收方对代码 6/7 项的独立 PASS 判定**。

## 1. 背景（验收方 BLOCKED 事实，保留）

- 独立验收方（全新上下文 `wb / cn:deepseek-v4.1-flash / reasoning_effort=max`）判定 T113 **PASS**，但第 7 项全量在验收沙箱 **BLOCKED（环境，非代码）**：
  - 两次全量：`1755 passed / 85 failed / 18 errors`（759.09s，未 patch 0o700）与 `1812 passed / 46 failed`（505.08s，patch 0o700 后）；两次总数均 **1858**，与开发自报一致。
  - 46 项失败全为沙箱对 `docs/evidence` 只读：43 个 `acceptance/test_t09_*` 写 `docs\evidence\T09\D1\actual\...`、3 个 `rag/test_budget*`/`test_s4_stage_limit.py` 写 `docs\evidence\...\budget\live-ledger.jsonl.lock`；**无 observability/T113 失败**。
  - 证据：`.claude/handoffs/T113-observability-api/review.md` §3、`docs/reports/OBS-EVAL/P1/evidence/verify/T113/03-tests-and-regression.md` §A。

## 2. 恢复动作（PM，获主人一次性更宽权限后）

- 前提：工作树仅含验收产物与 PM 材料，交付树仍为 `9edc003`（`git diff 9edc003..HEAD --stat` 只动 `.claude/handoffs/**`）。
- 命令（cwd=仓库根）：
  ```text
  $env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
  .\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t113-pm-full
  ```
- 结果：**1858 passed, 1 warning in 474.19s (0:07:54)**，**0 failed / 0 error**；既有两个 flake 本轮未出现。
- 日志：`.claude/handoffs/_scratch/pm-full-pytest-20261109.log`（gitignored，5.2KB 摘要 + dots）。

## 3. 结论与边界

- 在交付树 `9edc003` 上，全量「0 failed / 0 error」**成立**；第 7 项的环境阻断已解除。
- 本记录属**环境恢复复跑**，不是验收方判定；验收方未完成的全量复跑事实仍以其 `review.md` §3/§5 为准（已如实入库）。
- 当前会话文件策略已切换为 `danger-full-access`（主人 2026-11-09 18:0x 调整），后续包（T114/T900）全量可直接正常执行，无需再重复本恢复步骤。
