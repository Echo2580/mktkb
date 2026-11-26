# 请求保管角色生成新私有计划（r0/r1 诊断）——2026-11-16

> 本文件是**给保管角色的最小请求单**，可整段转交。它不包含题面、答案、实体值、key 或私有路径内容。
> 目的：让新 GO 有可绑定的 `plan_id` / `plan_sha256`。**只生成计划，不执行 run、不发真实请求。**

## 1. 背景

- 主人已于 2026-11-16 批准：仅 r0 `base_b0` 与 r1 `base_b0_plus_v01` 各至多一次的受控诊断（见 `OWNER-APPROVAL-20261116.md`）。
- 本轮源码已有未提交修改，**旧计划绑定的是旧代码摘要**，直接复用会被入口以 `code_changed_since_plan` 拒绝，且不构成新授权。
- 因此需要按当前工作树重新生成一份完整四场景计划集（r0–r3），但**只有 r0/r1 会被签发 GO**；生成四份 ≠ 授权四次运行。

## 2. 请保管角色执行的命令（参数结构，非由我方执行）

```text
tools/p2_h2_v3_controlled_execute.py plan-private
  --root        <仓外受控根：v3 holdout 目录，含 manifest/密文>
  --key-file    <保管侧 Fernet key，仓外>
  --out-dir     <仓外新目录，必须不存在，避免覆盖旧计划>
  --created-utc <有效 ISO8601 时刻，带时区>
  --max-requests 1500
```

硬性要求（来自当前代码，不可改）：

- `--max-requests` **必须等于 1500**；传其他值会被 `max_requests_mismatch` 拒绝。
- `--out-dir` 必须是**仓外新目录**；不得覆盖或复用 `run/plan` 旧目录。
- `--root`/`--key-file` 只在保管侧使用；**不要**把内容、路径清单或 key 回传。
- 本步骤只生成计划与 binding；**不得**顺带执行 `run`。

## 3. 计划必须绑定的内容（请在回执里确认，不需要回传原文）

| 绑定项 | 期望 |
|---|---|
| 代码 | **当前未提交工作树**的代码摘要（不是仅 HEAD `97b0066`） |
| 数据/场景 | 当前 v3 场景契约与冻结清单（`p2-h2-scenarios-H2v3.json` 哈希未变） |
| run/date | r0 business_date `2026-10-15`；r1 `2026-07-15` |
| index | `index_revision = pending_post_ingest`；index 批次 9/10/13/15 |
| ingest | 现有 ingest plan（`p2-ingest-plan-H2-v3.json`，哈希未变） |
| 预算画像 | 项目总上限 40；阶段 `P2-LIVE` 20；单请求峰值预留 0.018688 |
| 操作集 | 仅 index_embedding / query_embedding / rerank / query_expansion / answer |

## 4. 请回传的最小安全元数据（只回传这些）

| 字段 | 说明 |
|---|---|
| `plan_id`（r0、r1） | 形如 `P2-H2V3-<日期>-r0-base_b0` |
| `plan_sha256`（r0、r1） | 64 hex |
| `total_requests`（r0、r1） | 计划请求数（预期 r0 ≤65、r1 ≤50） |
| `max_requests`（每计划） | 应为 1500 |
| `stage_limit_cny`、`cost_centers_cny`（每计划） | 用于校核 GO 下限 |
| `project_total_limit_cny` | 应为 40 |
| `code_version`（代码摘要）+ 生成时刻 | 证明绑定当前工作树 |
| `ingest_plan_sha256`、index 批数 | 证明 9/10/13/15 |
| run_id / business_date（r0、r1） | 证明 run/date |
| 计划生成时的账本**历史前缀** SHA | 应为 `f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014` |

**不要回传**：题面、答案、实体值、密文、key、私有文件内容、逐题 ID、响应文本。

## 5. 回执后由谁做什么

1. 我方（代签人，按 `OWNER-APPROVAL-20261116.md` §3）把 `plan_id`/`plan_sha256` 等填入 `GO-DRAFT-r0.template.json`，生成 r0 GO；r1 同形生成 pending GO。
2. 按既有归档命名归档当前槽位 GO（现为 r3 计划件），再放入 r0 GO；**不得直接覆盖**。
3. 逐 run `check-only`：r0 `--run-index 0`；r1 `--run-index 1`（先检查 pending）。
4. 预检全部通过且授权窗口有效，才可 `run`；任何一项不符 → 首错停，不执行。

## 6. 若出现以下任一情况，请停并回报，不要自行放宽

- `code_changed_since_plan`、`scenario_plan_mismatch`、`plan_identity_invalid`、`max_requests_mismatch`；
- 计划 `total_requests` 超过 65/50 或成本中心高于 8.5/6.5/3/2；
- 账本历史前缀与上表不一致（说明账本被换/被重置）；
- 无法确认计划绑定的是当前工作树而非旧快照。

## 7. 边界再确认

- 本请求**不**授权真实请求；执行仍需新 GO + 预检。
- 本请求**不**修改预算、账本、冻结件、题目、标签、门槛或旧证据。
- 生成四份计划后，只有 r0/r1 会被签发；r2/r3 的 GO 不存在，也不会被执行。
