角色：开发助手（T112 R1 接续，复用 R0 已完成的上下文事实，读文件即可）。任务 **T112 R1：按主人书面批准落盘 gate_v0_2 审批与 P1 release baseline 审批**。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（report 首行/R1 段注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；**R0 交付 commit = `7f46121`**；当前 HEAD 可能含其后 PM 簿记 commit（只改 `.claude/handoffs/**`）；开工前 `git status --short` 应 clean。
第一步：读 `.claude\handoffs\prompts\T112-dev-R1.md`（本文件）、`.claude\handoffs\T112-gate-baseline\handoff.md`（§0/§2/§3）、同目录 `report.md`（R0）、`docs/evaluation/gate_v0_2.json`、`backend/src/mktkb/evaluation/{gate,baseline,cli}.py`、证据 `docs/reports/OBS-EVAL/P1/evidence/T112/02-gate-proposal.md` 与 `03-gate-config-and-baseline.md`。

## 主人书面批准（2026-11-09 19:54 +08:00，审批人=主人；以此为准，不得改值）

1. **gate_v0_2 单值阈值**（所有指标共用一个阈值，跨层取最宽松 + 余量；仅检索层）：
   - `min_sample = 8`
   - `Recall@10` / `MRR@10` / `nDCG@10`：`absolute_min = 0.855`；`absolute_max = null`；`max_regression_pp = 2.0`
   - `hard_filter_violation_rate`：`absolute_max = 0.02`；`absolute_min = null`；`max_regression_pp = 2.0`
   - `empty_recall_rate`：`absolute_max = 0.145`；`absolute_min = null`；`max_regression_pp = 2.0`
   - 其余指标（answer/refusal/runtime）阈值保持 null、不批准（P1 仅检索层；b0/badcase 门禁仍 exit 3）。
2. **`gate_v0_2.json.status = "approved"`**，并按 `gate.py` 的 loader 校验补审批元数据（approved_by/approved_at/reason，字段名以代码实际读取为准；reason 建议：「P1 首次 release baseline；绝对阈值按 T112 校准提案批准；首次建立不做回退检测」）。
3. **授权建立 P1 release baseline**：`run_id=b0-live-20261109T111828086143Z-0efd058b`、suite b0、mode live、scope retrieval_only、dataset_version `b0:b0-2026-11-04:bd4f0f7ccc6e`、corpus_sha256 `68899152…`、pipeline `08166b113481`、gate_version `mktkb.gate.v0.2`、gate_config_hash `5362de3c…`；
   `baseline approve --approver "主人" --reason "P1 首次 release baseline（b0 live 40 题）；绝对阈值按 T112 校准提案批准；首次建立不做回退检测"`。

## 任务

1. 落盘 `docs/evaluation/gate_v0_2.json`：`status=approved` + 上述阈值 + 审批元数据；其余字段（8 硬门禁、suites、15 metrics 骨架、notes）保持/更新一致；**不得改 R0 校准证据里的 proposal**。
2. 用 approved 配置对 R0 的 b0 live run 跑一次 gate：**必须 exit 0**（质量 pass）；保存命令与输出摘要到证据。若 exit != 0：**停手，如实报告，不得改阈值/放宽**。
3. 执行 `baseline approve`（现场重算门禁）并核对：approval.json 存在、`baseline_id` 六要素绑定、`baseline list` 显示 approved、P0 baseline 未被影响/未 copy。
4. 更新证据 `docs/reports/OBS-EVAL/P1/evidence/T112/03-gate-config-and-baseline.md` 追加「R1 审批落盘」节（命令/输出/gate exit 0/baseline_id/approval 文件路径与 sha；**证据仍 ≤4 份，不新增第 5 份**）；更新 `report.md` 加 R1 段（可精简，≤80 行预算，超出需在偏离披露）。
5. **1 个新 commit**（不 amend `7f46121`）：`p1/T112 R1 approved gate_v0_2 thresholds + P1 release baseline approval`；不 push。
6. 硬约束：零真实模型/embedding/rerank/OCR 调用；不写账本/GO；不动 `var/eval/runs` 的 live 产物；不改业务代码/API/fixtures/P0 gate/baseline；不读 `.env`/Holdout；无 skip/xfail/删断言/新依赖。
7. 回复 ≤10 行：commit sha、gate exit code、baseline_id、approval 文件路径、report/证据变化、任何偏离。
