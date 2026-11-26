# R2-RUNBOOK 的 6 条 UNVERIFIED —— 关闭情况（2026-11-17，外部开发助手）

只读核查，零执行：未运行 `plan-private`/`check-only`/`run`，未签发 GO，未访问网络，未读 holdout 明文。

| # | runbook 原 UNVERIFIED | 现状 | 依据 |
|---|---|---|---|
| U1 | `plan-private` 在本次 holdout 根上的实跑结果 | **路径已定位，实跑仍 NOT-RUN** | 保管根 = `D:\mktkb-p2-holdout\v3`（含 `manifest.json`、`questions.jsonl.fernet`、`labels.jsonl.fernet`、`annotations-v0_2.fernet`、`review-v0_2.fernet`、`source-map.json`、`targets.jsonl.fernet`、`authoring-record.jsonl.fernet`）；key = `D:\mktkb-p2-holdout\keys\v3.key`。仅列目录名与字节数，**未解密、未读明文**。实跑须在 T-R2-205 由本窗口执行并留回执。 |
| U2 | `run_recompute_cli` 所需 `cases_path`（CaseSpec JSON）生成方式 | **不在 R2 真实链路**（可关闭） | `tools/p2_h2_v3_controlled_execute.py` 全文**不调用** `run_recompute_cli`；该 CLI 仅存在于 `p2_hard_evidence.py:4039-4056`（`load_cases(cases_path)`），R2 判定链走的是本包 `work/r2_recompute_axes.py`（自带加载链）。 |
| U3 | `r2_recompute_axes.py` 是否仍引用 R1 绝对路径 | **已关闭** | 该工具取 `--work/--bindings/--runs/--out/--compat`；`_resolve_run_dir`（`:408-415`）先看 `work/rN/out/controlled/case-plan.json`，**否则把 `--work` 本身当单 run 根**（只要其下有 `out/controlled/case-plan.json`）⇒ 可直接传本次 `<ATTEMPT>` 根，无需软链/包装目录。`_binding_for` 只按 scenario 名在 `--bindings` 目录找 `run2-pre_v05_without_v07.binding.json`。 |
| U4 | 本次计划的 `worst_case_cny` | **待计划生成后回填** | 由 `plan-private` 输出派生；历史 r2 实付 0.0466439 元、同形上界约 0.29 元仅作量级参考，不得替代。 |
| U5 | 新 GO 装槽后 check-only 16/16 全绿 | **待执行** | 需要先有新计划 + 新 GO；`--plan-only` 不等于完整预检（必须 `mode=full_contract_reload`）。 |
| U6 | `contract_validate_run.authorized_delta` 具体数值 | **不是输入，是输出**（可关闭） | `tools/p2_h2_v3_controlled_execute.py:1042/1422`：`authorized_delta` 由 **check 层**产出，执行层做"授权值 == 计划值 == census 派生值"三方逐值校验（`:1036`）；不可手写，手写即 `exec_contract_invalid`（`:1058`）。 |

## 追加注意（本次核查新发现）

1. **run_id 不可唯一**：v3 入口 `TAG="P2-H2V3-20261115"` 为文件常量、CLI 无 override ⇒ 本次 run_id 必与历史同名
   `p2-h2v3-20261115-r2-pre_v05_without_v07`。区分只能靠 `plan_sha256` + `attempt_scope_sha256` + receipt 字节 sha。**不得**为了"唯一"去改入口常量。
2. **`code_version` = 脏工作树摘要**（`tools/p2_h2_controlled_execute.py:389-408` 的 `code_digest()`：`backend/src/mktkb` 递归 `*.py` + v2 入口，
   v3 入口在导入时把自身追加进 scope）。故计划一旦生成，**任何** `backend/src` 或入口字节变化都会触发 `code_changed_since_plan`。
   ⇒ 生成计划前必须冻结源码（含 202C 的 9 hunk）。
3. **两套 GO 摘要分列**：`payload_sha256`（内容规范化，`p2_contracts.py:387-399`）→ 进 `bindings.go_sha256`；另有归档文件字节 sha。二者不要求相等。
4. **GO 授权文本 ≤200 字符**（`p2_authorization.py:196-204` 的 `_text(maximum=200)`）；历史上 4 份 221–237 字符的件被 `text_invalid` 拒（现场仍留 `.oversize-text.archived.json`）。签发前在脚本内断言 ≤180。
5. **槽位归档**：固定槽位现装 R1 run2 旧件（字节 `38f3c3f5…`），同目录已存在两份同字节 `*.done.archived.json` ⇒ 新归档必须用**新 tag**、`xb` 独占创建，禁覆盖、禁删旧件。
6. **仓外产物落点**：不得落在仓库内，也不得落在 `D:/mktkb-p2-holdout` 之下。
