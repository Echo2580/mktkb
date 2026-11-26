# v3 实跑入口 + 预算对齐（H2V3/v3-entry）

- 角色：v3 实跑入口 + 预算对齐开发（普通开发；非验收/经理）。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0 项。
- 本包**零真实请求**：未发 HTTP、未 reserve、未写共享账本/预算；账本 `ca9dceb9…`（1,932,692 B，952 次预留）与预算 `5fcb4be5…`（1,738 B，limit 50）首尾逐字节相同。
- 本报告不使用“通过/PASS”一类结论词；只给逐值事实、固定码与可复算的 SHA-256。

---

## 1. R1 修复（唯一 tracked modified）

| 项 | 值 |
|---|---|
| 文件 | `backend/src/mktkb/evaluation/p2_holdout_plan.py` |
| 改前 SHA-256 | `d0cb23de2cff80a743c086a8723edd80654d64b22f4e18f97973dd83b153cd25`（15,634 B，`git show HEAD:…`） |
| 改后 SHA-256 | `2366945b61209ba46bb1ef7525c52952a58f8b750e9bb07ccdfeafc396586f3d`（15,914 B，工作树） |
| diff | `4+ / 1-`：`import os`、2 行注释、常量赋值替换 |
| 唯一语义变化 | `H2_PROJECT_TOTAL_LIMIT_CNY` 的取值来源由字面量 `40.0` 改为 `MKTKB_PROJECT_TOTAL_LIMIT_CNY`（缺省仍 `40.0`，导入期读取） |

改后关键行：

```python
H2_PROJECT_TOTAL_LIMIT_CNY = float(os.environ.get("MKTKB_PROJECT_TOTAL_LIMIT_CNY", "40.0"))
```

`build_holdout_plan` 的默认参数与 `ValidatedScenarioContract.build_plan`（不显式传该值）在同一进程内看到同一个常量，因此 `build_plan` 与 `validate_run` 的复算值一致。

证据件：`docs/reports/OBS-EVAL/P2/H2V3/v3-entry/limit-alignment.json`（1,693 B，SHA-256 `bdadb94fdce3e434a995d81892bdb8fc6024d0a319bbb5ac205e5e0a4e8541f9`）。同一份旧计划 `run0-base_b0.plan.json`（`plan.project_total_limit_cny=50.0`）在两个子进程里：

| 环境 | 常量 | `contract.validate_run` | 差异键 / 值 |
|---|---:|---|---|
| `MKTKB_PROJECT_TOTAL_LIMIT_CNY` 未设 | 40.0 | `ok=false`，`code=scenario_plan_mismatch` | `["project_total_limit_cny"]`；计划 50.0 vs 期望 40.0 |
| `MKTKB_PROJECT_TOTAL_LIMIT_CNY=50` | 50.0 | `ok=true`，`code=null` | `[]` |

即：缺省行为逐值不变（40.0，仍 fail-closed）；只有显式把环境总上限设为 50 时，契约复算才与预算 50 对齐。

---

## 2. v3 live 入口（新文件，不改既有）

| 项 | 值 |
|---|---|
| 路径 | `tools/p2_h2_v3_controlled_execute.py` |
| 大小 / SHA-256 | 75,440 B / `aa8e8cb44c16adc57dc00d6db8a9769662bee88700280b270d021e85cd7e97cb` |
| 子命令 | `plan-private` / `check-only` / `run` |
| 复用 | v2 入口的 `_execute_loaded`、`check_target_paths`、`read_authorized_env`、`applied_env`、`_write_case_plan`、封存/清理/回执骨架（v2 文件未改） |
| v3 差异 | ① `load_v3_scenario_contract`；② `dispatched_scoring_map`（`p2-holdout-source-map/v0.2`）；③ 每 run 自己的 L1 `business_date`（`rag==manifest==run_date`）；④ 预算 50（导入前显式设环境，冲突即拒绝） |
| 运行前置 | 必须在仓库根运行（v3 ingest 源是相对路径）；`plan-private` 只写仓外 |

`check-only` 两种口径：

- 默认 `--reload-contract`：用 v3 loader 在内存复核 dataset/契约/custody/axis 计数，执行原失败码位 `contract.validate_run`；
- `--plan-only`：不加载私有数据集，用计划自身的 `(case_id, turns)` 调 `build_holdout_plan` 重算，再走 `preflight_p2` / `authorize_p2`。

`run --run-index i`：单 run、串行、首错停、不重试；`_execute_loaded` 外层包 `dispatched_scoring_map`。离线接线冒烟（`run-wiring-smoke.json`，3,075 B，SHA-256 `22f59fe13ca9aeefa036d98a977613db068a3f76312a69d4498ea3964d5c15ad`）把 `read_authorized_env` / `check_target_paths` / `_execute_loaded` 换成离线替身，实际走到 `_execute_loaded` 的参数为：run0 `business_date=2026-10-15`，subset 内 case 日期全为 `2026-10-15`，`plan_id=P2-H2V3-20261115-r0-base_b0`；未构造 provider、未发请求、未写账本。

---

## 3. 四份计划 / binding / GO（重生成，仓外）

计划与 binding 落点：`D:\mktkb-p2-h2v3-20261115\entry\plans\`、`…\entry\bindings\`。GO 落点：`…\entry\go\`。

| run | scenario | business_date | 题/回合 | 请求 | plan 文件 SHA-256 | `plan_sha256` | binding SHA-256 |
|---:|---|---|---:|---:|---|---|---|
| 0 | `base_b0` | 2026-10-15 | 12 / 14 | 64 | `3c1ce5fbb26f11a7ce86506a6e157fca8d24aee07468cc766d54c622a457e0eb` | `349d424434bcd9742f76f05feb29b0fab56fb74f8a686ad56b3522626a960884` | `defcdb87dbd0701b965c537098a666f0bbd81d20991710ead6d8943eba9f80a7` |
| 1 | `base_b0_plus_v01` | 2026-07-15 | 8 / 10 | 49 | `c65600790ff77e70b6055c74f3def7ab2021bb3319dce033e57abbcc72d17f03` | `cd1dcdecb26a6b4dfcf23d7ef513a180785fd5e6265b17ae7b8187a89a962d39` | `09057702702d1d91fb0428338461ae7ef282fec8b0d47e3bd5e8b6e7acf21f82` |
| 2 | `pre_v05_without_v07` | 2026-11-20 | 5 / 6 | 35 | `e2bfd84b2702db4fe89e7b05fc0c64db8f41c3d6488994998dc8d23edc16ddc7` | `6da15e8ad7650b598b1e63b302050e51bed3bd4a4981b03faeec60d176b38110` | `4a4843472f17a4cf0d7c01b247980b7419c44ecf56864354e3d0d72ce507fdfb` |
| 3 | `post_v05_without_v01` | 2026-12-15 | 5 / 6 | 37 | `9cee939ea955356a681cf3bf182bae7d110b41e210d5f94c081f63e1d19fb85c` | `e2cff4ee0f064417c5eb8db8909a036f91fffdbf7dc737675667e14e9897634a` | `240418a62092d4954ce0a9c61af8745523b42f84c082ab99190f5b636a2b8333` |

**计划 SHA 未变**：四份新计划与 v3-go 旧计划 `as_dict()` 逐值相同（旧计划本来就显式声明 `project_total_limit_cny=50`）。本包改的是**复算器**，不是计划内容；`build_holdout_plan` 现在也产出 50，`validate_run` 因此对齐。四份 binding 是新件（每 run 一份、带自己的 `business_date`、新 `code_version=10cfb35e…`）。

| run | GO 文件 | 字节 / 文件 SHA-256 | 槽位 |
|---:|---|---|---|
| 0 | `…\entry\go\P2-LIVE-GO.v3-r0.json` | 1,181 B / `8effb4b1545afcfd939892803bd93b9303be6cd155a8236563f2f374785ffdbf` | 固定槽位（同字节重装） |
| 1 | `…\entry\go\P2-LIVE-GO.v3-r1.json` | 1,199 B / `5cdde637baf0e6a9319bb0245196d1407d51f80408b9d244b507ddd6b8d4c578` | `PM/P2-LIVE-GO.v3-r1.pending.json`（同字节） |
| 2 | `…\entry\go\P2-LIVE-GO.v3-r2.json` | 1,205 B / `cbce4ba4ceff02794e94eb76361763f157262154840245380824edbe80274af8` | `PM/P2-LIVE-GO.v3-r2.pending.json`（同字节） |
| 3 | `…\entry\go\P2-LIVE-GO.v3-r3.json` | 1,207 B / `8a4c94fb5df1a1bd76c70dd26651624ec3696b14979de0367f2c22f6b5d78bc0` | `PM/P2-LIVE-GO.v3-r3.pending.json`（同字节） |

- GO 由新计划重新生成（`nonce = sha256("P2-H2V3-20261115:go:r<idx>:<plan_sha256>")[:32]`），四份均与旧 GO **逐字节相同**（`byte_identical_to_old=true`），因此文件 SHA 与 v3-go 报告一致。
- 旧 `plans/`（8 文件，tree SHA-256 `d4988f7a7b467b8438aa338c6b9eafb63363ab7a7911064faaea82f4fbb8a7f5`）与旧 `go/`（4 文件，tree SHA-256 `0819310c490463f4a1f16aed085cafca6c997e9a61c3d56148ada8fa16e8006e`）复制归档到 `D:\mktkb-p2-h2v3-20261115\archive-v3-go\`；未删除、未覆盖。
- 固定槽位原 GO 先复制归档为 `PM/P2-LIVE-GO.v3-go-r0.previous.archived.json`（1,181 B，同 SHA），再以同字节原子重装；`before_sha256 == after_sha256`。
- 生成证据：`entry\evidence\go-regeneration.json`（7,559 B，SHA-256 `cef0ccba11bb2e469113470da556db237afa3a1278dd2698cf49bc475ddc9cb6`），`all_ok=true`。

---

## 4. 零发送预检（check-only）

### 4.1 完整契约复核（每 run 一份）

证据：`docs/reports/OBS-EVAL/P2/H2V3/v3-entry/preflight-run0..3.json`。

| run | 文件 SHA-256 | `ok` | `production_ready` | `preflight.ok` | `plan_recompute.ok` | `contract_validate_run.ok` | 外部尝试 |
|---:|---|---|---|---|---|---|---:|
| 0 | `8657013373a44753b189d6ba37e45da215416ab69ea9391f96d0207a3cb9ff04` | true | true | true（`reasons=[]`） | true | true | 0 |
| 1 | `b18d243c431863a28c30737e05b9249f407a7713fcdbea9771a3899b3e71447d` | true | true | true（`reasons=[]`） | true | true | 0 |
| 2 | `f29b303983cd716fa72039dafaac74bd9fa3b603fbcbf9464fe2ef278c2198b6` | true | true | true（`reasons=[]`） | true | true | 0 |
| 3 | `d09f6645389bc05d7be74c9455a90fbc83f300e6f04da521984cc8ebf2b6f0be` | true | true | true（`reasons=[]`） | true | true | 0 |

- `plan_recompute` 用 `build_holdout_plan`（与 `contract.build_plan` 同一调用）重算，`differing_keys=[]`、`code=null`；原 `scenario_plan_mismatch` 不再出现。
- `contract_validate_run` 走真实 v3 loader + `validate_run`：`ok=true`、`differing_keys=[]`。
- run0 `go.slot=fixed`；run1..3 `go.slot=simulated_pending`（见 §7）。
- 四份 `zero_write.ledger_unchanged=true`、`budget_unchanged=true`、`reservation_count=952`。

### 4.2 计划口径（不加载私有数据集）

证据：`…\v3-entry\preflight-plan-only-run0..3.json`。

| run | 文件 SHA-256 | `ok` | `production_ready` | `preflight.ok` | `plan_recompute.ok` | `contract_validate_run` |
|---:|---|---|---|---|---|---|
| 0 | `c3da3b6da307541b7591460254066676218f697c29045b3ac07fda4f8a40ded2` | true | true | true | true | skipped |
| 1 | `4f9df0a3f176033b510957007207ec432c73d806f92a5c5057c590de6b5cfe5e` | true | true | true | true | skipped |
| 2 | `937332fbb1ccd52d35866494ef1ad332c875a6407ba131c3d4f51d22fca6b12f` | true | true | true | true | skipped |
| 3 | `52ba0cb24464c6f4f076888237352c710f7b136bcdd4b5b1d7c9b9e942709a97` | true | true | true | true | skipped |

这一支不读 `questions.jsonl.fernet` / `labels.jsonl.fernet`；它用计划自身 `(case_id, turns)` 重算。两支都给出 `differing_keys=[]`。

---

## 5. 请求闸门（四 run 合计 vs 548）

| 项 | 值 |
|---|---:|
| 四 run 计划请求 | 64 + 49 + 35 + 37 = **185** |
| 预检时账本已用 | 952 |
| 治理额度 / 余量 | 1500 / **548** |
| 判定 | 185 ≤ 548，`exceeds_gate=false`，不需停机 |
| 四 run 后累计 | 952 + 185 = **1137**（治理余量 363；代码硬顶 `HARD_MAX_REQUESTS=1600` 未触） |

---

## 6. 保全（前后逐值）

| 项 | 前 | 后 |
|---|---|---|
| 分支 / HEAD | `codex/p2-e2e` / `97b00667…` | 同 |
| 暂存区 | 0 项 | 0 项 |
| tracked modified | 15 条 | **16 条**（原 15 条路径逐条相同 + `p2_holdout_plan.py`） |
| 新增 untracked 文件 | — | `tools/p2_h2_v3_controlled_execute.py` 1 条 |
| 共享账本 | `ca9dceb9…` / 1,932,692 B / 952 | 同 |
| 共享预算 | `5fcb4be5…` / 1,738 B / limit 50 | 同 |
| v2/v3 语料与密文、C 冻结 12、`p2_holdout_scenarios.py` | — | 未改 |
| 旧 GO / 旧归档 | `8effb4b1…` + 既有 `*.archived.json` | 固定槽位同字节重装；另存 `P2-LIVE-GO.v3-go-r0.previous.archived.json`；既有归档未动 |

- 未 commit、未 push、未 stage、未新建 worktree、未切分支。
- 本包仓内新增：`tools/p2_h2_v3_controlled_execute.py`、`docs/reports/OBS-EVAL/P2/H2V3/v3-entry/`（报告 + 10 份证据）。计划/binding/GO/归档均在仓外；固定 GO 与 pending GO 在 `.gitignore` 覆盖的 `docs/evidence/` 下。
- `p2_holdout_plan.py` 之外的 15 条 tracked modified 未被本包编辑；其路径与 v3-go 报告 §9 的 15 条逐条相同。

---

## 7. 残余与操作注意（本包未关闭）

| # | 项 | 级别 | 说明 |
|---:|---|---|---|
| R1' | 缺省 40.0 仍 fail-closed | 中 | 环境未设时 `H2_PROJECT_TOTAL_LIMIT_CNY=40.0`，`validate_run` 仍报 `scenario_plan_mismatch`。这是刻意的默认；直接走 `cli.py p2-run --mode live` 必须显式设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=50`（R5 仍在）。v3 入口内部固定设 50，并对冲突值拒绝。 |
| R2' | GO 单槽位 | 中 | run1..3 的 `production_ready=true` 是“该 run 的 GO 在固定槽位”的口径：check-only 只在进程内把 `P2_GO_PATH` 指向 pending GO（不写文件），退出还原。真跑 runN 前必须先按 v2 动作把固定槽位换到该 run 的 GO；否则 `open_live_gate` 会以 `go_plan_id_mismatch` 拒绝。 |
| R3' | 计划/GO SHA 未变 | — | 旧计划本来就声明 50，重生成逐字节相同；这不是“没重生成”，而是“复算器对齐后计划无需改动”。若要求新 SHA，只能改计划内容（如 plan_version/created_utc），属另一决策。 |
| R4' | 完整复核会加载私有数据集 | 低 | 默认 `check-only` 用 v3 loader 在内存解密 dataset/annotation 以执行 `contract.validate_run`；题面/答案未输出、未落盘、未用于判定之外用途。`--plan-only` 完全不加载这两个密文。 |
| R5' | run3 余量恰为 37 | 中 | 四 run 跑完后累计正好 1137；任何重跑需新 GO（新 nonce + 新 plan）。 |
| R6' | `run` 未真跑 | — | 本包硬边界只做 check-only；`run` 仅做离线接线冒烟（替身 `_execute_loaded`），未构造 provider、未发请求。 |
| R7' | 固定槽位重装 | — | 固定 GO 以同字节原子重装，`before_sha256 == after_sha256`；旧件已复制归档，未覆盖既有归档。 |

---

## 8. 零真实调用

| 项 | 值 |
|---|---|
| HTTP / 发送 | 0（四份 check-only 证据 `zero_send.external_attempts=0`；socket 守卫正对照 1/1 在 connect 前被拦） |
| 预留 / 扣费 | 0（`reservation_count` 952 → 952；账本 SHA 前后相同） |
| 产品/模型调用 | 0（`run` 仅离线替身冒烟） |
| 题面/答案输出/落盘 | 0（默认完整复核只在内存；plan-only 不加载） |
| commit / push | 0 |
