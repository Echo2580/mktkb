# R0-3B / C16 空用集兼容增量 v0.4 —— 实施报告

日期：2026-11-16（Asia/Shanghai）。范围：`C16-EMPTY-SCOPE-PROPOSAL.md` §2/§4/§5-1（主人已批准）。
只读合成件；未读任何私有材料（`D:\mktkb-p2-h2v3-*`、`.env`、`*.key`、`P1-HOLDOUT`），未发真实请求。

## 1. 结论

已按提案实现 `p2-refusal-compat/v0.4`：在 v0.3 之上**只**跳过"检索观察层（`retrieval_observed.unit_ids`）
必须为空"这一项，且要求事实使用容器全显式空、无 `direct_rag_answer`、固定无事实模板恒等。
C16 形状在 v0.1/v0.3 仍 `empty_set_not_proven`，在 v0.4 为 `empty_use_scope_ok`，两轴由 unknown 变 passed
并带审计码 `retrieval_observed_unused`；其余 16 个反例在 v0.4 下与 v0.1 **逐值相同**。
旧版（v0.1/v0.3）行为经字节级还原 + 212 次证明差分 + 212 次分类差分确认为 0 差异。

## 2. 改动清单（净增）

| 文件 | 性质 | 行数 |
|---|---|---|
| `backend/src/mktkb/evaluation/p2_hard_evidence.py` | 改 | 3904 → 3989（**净 +85**）；172238 → 176496 字节（+4258） |
| `backend/tests/evaluation/test_r0_repair_c16_empty_scope.py` | 新增 | 518 行 / 28 个用例 |
| `docs/evaluation/p2-refusal-compat-v0_4.md` | 新增 | 109 行（契约：允许条件/反例/继承/旧版承诺） |
| `backend/tests/evaluation/test_p2_empty_scope_proof.py` | 只改 pin 注释与 `FROZEN_SHA` | +8 行 |

`p2_hard_evidence.py` 内容（全部追加，无删改既有判据）：
`REFUSAL_COMPAT_V0_4`、`REFUSAL_COMPAT_INHERITS`、`_compat_table_version`、
`_retrieval_observed_unused_relaxable`、`_ref_empty_use_scope`；两处查表改走 `_compat_table_version`
（v0.1/v0.3 原样返回，等价）；判定循环一行加 `relax_retrieval` 窄条件；5 处空集通过点改为
`_ref_empty_use_scope(...)`（即 `empty_use_scope` + `retrieval_observed_unused`）。

## 3. 哈希

| 对象 | 前 | 后 |
|---|---|---|
| `p2_hard_evidence.py` | `84f53a517e4c2e5eeb50cd4319462ef7d966f2d946083794c406cd2605bd485b` | `8f206ee9f016b9fbf5d9d0c0568117f05692849c540fe232c3ec50b5c42c5bec` |
| `test_r0_repair_c16_empty_scope.py` | — | `9837de77cac7…`（sha256 前 12 位） |
| `p2-refusal-compat-v0_4.md` | — | `e3c79101e0a3…` |

`test_p2_empty_scope_proof.py` 的 `FROZEN_SHA` 已同步为新字节（旧值 `84f53a51…` 保留在注释里，授权来源写在
pin 上方；这是内容 pin，不是行为断言）。

## 4. 红 → 绿

命令（两条相同）：`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"` +
`.\.venv\Scripts\python.exe -B -m pytest <路径> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\c16`

- **红**（实现前）：`test_r0_repair_c16_empty_scope.py` → `22 failed, 6 passed`
  （`test_c16_shape_flips_only_under_v0_4[v0_4]`：`assert (False,'empty_set_not_proven') == (True,'empty_use_scope_ok')`）。
- **绿**（实现后）：同一文件 → `28 passed`。
- `test_r0_repair_refusal_compat.py` → **62 passed**（两张旧登记表字面量未被改写）。
- `test_p2_empty_scope_proof.py` → **88 passed**（含冻结原语差分语料与 pin）。
- `test_p2_hard_evidence.py` 定向子集（`-k "empty_scope or retrieval or r3..r7 or template or branch or
  stale_source or cross_entity or duplicate or required_key"`）→ **192 passed**
  （另有 3 个 `test_composition_v02_*` 为 fixture 报错 `scenario_private_path_inside_workspace`：
  私料路径门槛，与本改动无关；`-k "... and not composition_v02"` 时 216 passed，含
  `test_p2_evidence_rescore.py` 与 `test_t207_v8_safety_contract_synthetic.py`）。

## 5. 旧版不变自证（字节级 + 逐值）

1. 用最小逆补丁把工作树新模块还原为改动前字节，SHA-256 == `84f53a51…485b`（改动前 pin 值）→ 还原是 bitexact 的。
2. 以该旧模块与新模块对比 **106 个合成 envelope**（`test_p2_empty_scope_proof` 差分语料 + 新测试 battery +
   全部反例 + 分支/查询态/未解析单元变体）× {v0.1, v0.3}：
   - `_empty_use_scope_proof`：**212/212 逐值相同**（∅ diff）；
   - `classify_case_evidence(...).as_dict()`：**212/212 逐值相同**（∅ diff）。
3. v0.4 与 v0.3 在**不含检索观察非空**的样本上逐值相同（10 例 battery，proof + 分类整体；唯一翻转点是 C16 形状）。
4. 无全局可变状态：判据是纯函数，审计码由调用方在同一 `compat` 下重算，未引入线程不安全的模块级缓存。

## 6. 折中与偏差（如实）

1. **继承表代替直接加键**：提案 §2 字面要求把 v0.4 加入 `REFUSAL_KIND_CROSS_LAYER_MAP` /
   `REFUSAL_TEMPLATE_KEYS_EXTRA`，但 `test_r0_repair_refusal_compat.py::test_compat_constants_and_defaults_are_v0_1`
   逐字 pin 了这两张表（该文件本次禁改且要求仍 62 passed）。改为单列 `REFUSAL_COMPAT_INHERITS` +
   `_compat_table_version` 解析，**取值与 v0.3 逐条相同**、旧表字面量零改动；行为等价，
   测试 `test_v0_4_constant_and_tables_stay_inherited` 与 C26 形状共同钉住。
2. **"检索观察非空"读作"至少一条非空且全部为 list"**（不是"每条都非空"）：空观察不构成放行需求，
   避免对真实 C16 产生假阴性；坏类型/缺键仍 `branch_evidence_missing`。
3. **两层分工**：`unresolved_unit_ids` / 投影 `units` / `message_sources` / 查询态候选非空时，
   窄放行判据本身可能返回 True，但 `_empty_use_scope_proof` 随后照旧拒绝；测试分别钉住两层，
   避免把"放行条件"与"其余空集前提"混成一条断言。

## 7. 未验证项

- 未在真实 C16 envelope 上复核（禁读私有材料），只验证合成形状；真实复核需验证侧显式传
  `compat="p2-refusal-compat/v0.4"`（本次范围不允许改 CLI/runner，**默认路径仍是 v0.1**）。
- 未跑全量 backend 测试，只跑派单指定文件与定向子集；`test_p2_hard_evidence.py` 全量未跑。
- 再评分/诊断层（`p2_evidence_rescore*.py`、`p2_diagnostics`）未接 v0.4，属范围外。
- 未做并发/性能验证：判据为纯函数，但未压测。
