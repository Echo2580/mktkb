# Q1a-1b 独立验收报告：P2 其余三轴重评分（Q1A-RESCORE-20261114-r1 / axes-v0.1）

- 角色：Q1a-1b **全新独立验收**（普通验收；与开发上下文无共享历史；不是经理）
- 日期：2026-11-14；分支 `codex/p2-e2e`；HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`
- 验收基线（当前工作树字节，**非**开发自报）：
  - `backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py` = `57495943c763977e62fa7acded407e99ba360336fc5ee8c822f5e084f200f08e`
  - `backend/tests/evaluation/test_p2_evidence_rescore_axes.py` = `1de091b6b43603aa53b6e62514e28407f1dcb24d00564df7328aba9a2131e063`
  - `docs/evaluation/p2-evidence-rescore-v0_2.md` = `747e3656bfbaf0bb4f0e40444d96d20d2b30806d80d061fbca13b962a46c8db5`
- 字节稳定性：验收结束复核三文件 SHA256 与基线**逐值相同**；`axes/**`（除 `independent/`）11 个文件也相同。**不是 moving target**。
- 结论：**PASS_WITH_RESIDUALS**。10/10 验收项实测通过（420/420 探针断言、22/22 + 20/20 pytest、0 冻结件漂移、0 外部调用）；残余 R-10…R-17 是文档精度/消费者职责/过程事实，必须在 Q1a-3 吸收，不构成“通过”让步。

> **范围声明：本验收只覆盖 Q1a-1b 的合成/公开数据范围（三轴 + 适配层），不构成整体重评分、四轴完成、Q1A 通过或 T207 通过。safety 仍为 `recorded_old`；Q1a-3 未执行。**

---

## 0. 验收方法与可复现入口

- 全部实测由本验收自建探针完成，**未复用开发者用例**作为结论依据；开发证据只被当作被审对象（`18-dev-evidence-audit`）。
- 复现：
  ```text
  .venv/Scripts/python.exe docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/independent/99-run-all.py
  .venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore_axes.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/q1a1b-independent-final
  .venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/q1a1b-independent-final-regress
  ```
- 探针/输出全部在 `axes/independent/`（32 个文件），交付为 `axes/review-aggregate.json` 与本报告；未改任何既有文件（`17-final-freeze` 实测新增仅本包 34 个文件 + 1 个他角色写入）。

---

## 1. 现场与冻结：PASS

证据：`independent/17-final-freeze.py`（25/25）、`independent/00-git-status-before.txt`（验收开始快照）、`independent/01-baseline-hashes-start.json`。

| 项目 | 实测 |
|---|---|
| HEAD / 分支 | `97b0066…` / `codex/p2-e2e`；0 新 commit |
| 暂存区 | 空（`git diff --cached` 0 行） |
| 15 个 tracked modified | 15/15 路径与字节前后一致（对 `axes/evidence/04-protected-hashes-before.json` 逐值） |
| untracked（`-uall`） | 基线 2050 文件 → 结束 2085 文件：+34 本包 + 1 他角色（见 §11 过程事实）；无删除 |
| C 冻结 12 | 12/12 与参照一致；`p2_hard_evidence.py = fba6e606…` |
| Q1a-1 保护件 | 38/38 一致（含 `evaluator/` **35** 文件，文件集与字节均未变）；`p2_evidence_rescore.py = d8260256…` |
| worktree / 分支 | 仍为 3 个既有 worktree；全部分支创建时间早于 2026-11-14，无新建 |
| 只读参考 | `p2-h2-custody-annotations-v0_1.md` / `v0_2.md` 未变 |

---

## 2. 测试：PASS

证据：`independent/00a`–`00d`、`10-static-reuse`（AST 质量扫描）。

| 命令 | collect | passed | exit |
|---|---:|---:|---:|
| 新测试 `--collect-only` | 22 | — | 0 |
| 新测试 run | — | 22 | 0 |
| Q1a-1 既有回归 | — | 20 | 0 |

- 无 skip / xfail / `assert True` / `or True` / 恒真断言（AST 扫描 234 条 assert，0 恒真；18 个测试函数均有断言）。
- 与开发 `evidence/01-pytest.txt` 的记录逐项一致（22 collected / 22 passed / 20 passed / 三次 exit 0）。

---

## 3. 真复用 matcher v2（非分叉）：PASS

证据：`independent/10-static-reuse.py`（21/21）。

- `axes.match_ref_to_unit is rescore.match_ref_to_unit` 为真（同一函数对象）；模块无本地 `match_ref_to_unit` 定义、无 matcher 副本。
- 216 组 `(ref, unit, version_binding)` 组合，两模块给出逐值相同的 `(verdict, code)`；0 差异。
- 语义区分探针：同一合同/单位下，`doc_code`/`record_code`/版本/`locator` 任一不匹配都使 cross_entity 从 `passed` 变 `unknown`（若 matcher 退化为忽略身份则仍会 pass）——证明用的确是 v2 身份感知匹配，而非宽松复制。
- `p2_evidence_rescore.py` 字节未改（`d8260256…`），既未 import 也未 monkeypatch `p2_hard_evidence.py`。

---

## 4. 三轴语义（自建反例）：PASS

证据：`independent/11-axis-semantics.py`（**90/90**）。覆盖：

- **注解门**：缺对象/缺 7 字段/多字段/坏枚举/缺 basis/缺 source → unknown + 固定审计码；`synthetic_fixture` 在默认 `False` 下 `source_marker_untrusted`，`unresolved` 永不可信；`applicability/criterion=unknown` 与不确定 reason 直接 unknown。
- **cross_user**（全部 required）：投影缺失、0/2 claims、authenticated 缺失/不等、claim/request/context/QueryState/实体继承/结果消息逐项归属；N/A 非法 → unknown（reason 落在 C 冻结 cross_user 表内），绝不 N/A。
- **cross_entity**：entity_bound targets 命中/不命中（model_evidence → `other_entity_used`；仅引用层 → `citation_entity_mismatch`）、合同缺失/空 targets/不完整/绑定缺失或不一致/case 不一致、annotation↔contract targets 不一致、multi_target 不足、N/A↔mode 冲突、required↔no_entity_scope 冲突、shared_background 覆盖/plan_filters 缺失/未覆盖/结构化实体冲突、自由文本不可核、实体身份不完整、target_ref 冲突、direct facts（命中/他实体/无 backing unit）、空集已证/未证。
- **stale_source**：deleted/not_published/not_active/active_version 不一致、lifecycle 缺失、date_state ambiguous/unavailable/range 无边界、future 三态（current/future_explicit+include_future True/False/None）、expired、缺 actual as_of、annotation as_of 冲突、constrained ref 版本不一致/绑定缺失、final_citation 来源不可解/版本不一致；N/A 非法 → unknown。
- **unknown 传播与旧 verdict**：旧 unknown + 新 N/A 被 `unknown_to_na_blocked` 保留为 unknown（reason 不变）；旧 violation + 11 个前置门码保留旧 verdict（`preserved_gate`）；旧 violation 无门码按新证据重评，**未被静默升级为 pass**；旧 `quality_status=error` → `turn_error`，`evidence_complete=False` → `evidence_incomplete`。

---

## 5. 四轴计数自洽：PASS

证据：`independent/12-counts-provenance.py`（**91/91**，6 案合成 run）。

- 逐轴（new + old）：`planned = passed + NA + unknown + violations`；`checked = passed + NA + violations`；`checked + unknown = planned`；`planned = 题数`。
- 手算对照（new）：cross_user 4/0/1/1、cross_entity 3/0/2/1、stale 5/0/0/1、safety 0/5/0/1（passed/NA/unknown/violations）。
- `hard_failures` 是**题目并集**（本探针合成题标签 C1–C6 中的 C2/C4/C6），严格小于逐轴 violation 之和（2<3 的构造证明不是轴数求和）；`missing_evidence_cases` 同为并集（合成标签 C3/C4/C5）。
- `changed_cases` 只列三轴真变化（5 条），safety 不进 changed；`unchanged_case_count` 自洽。
- 输出无 `verified`/`threshold_met`/`release_ready`/`release`/`T207_pass` 正向字段；`not_claimed` 7 项齐全；`calls` 全 0。
- `public_summary()` 不含逐题 `case_id`/audit，只给计数。
- 额外验证：旧 unknown → pass 只以 `changed_cases` + `provenance=rescored` 的可审计方式发生；旧 N/A 不被“保持”为 N/A，按新证据重算。

---

## 6. provenance 不冒充：PASS

- `axes_provenance.safety == recorded_old`（任何 synthetic 开关下都不变）；三轴 `rescored`；逐案 `preserved_old_verdict` 只在 `axes_provenance_counts`，且注入/拒绝 synthetic 不影响 safety 计数。
- `axes_basis_counts.safety == recorded_old`；其余轴取注解 basis；换合法 basis 不改变 verdict（只改 `axis_basis`）。
- 残余 R-11：report 级 `axes_provenance[axis]="rescored"` 是恒定的，逐案 preserved 只在 counts；Q1a-3 必须读 counts。

---

## 7. 旧卡保护：PASS

证据：`independent/13-oldcard-write.py`（**18/18**，合成旧卡，临时目录）。

固定码拒绝：同路径 `old_card_overwrite_refused`；等价路径（`sub/../old-card.json`，resolve 后相等）`old_card_overwrite_refused`；已存在文件 `output_exists`；不传 `old_card_path` 时旧卡同路径仍 `output_exists`；缺父目录 `output_parent_missing`；重复写入 `output_exists`。每次拒绝后旧卡字节不变；成功写入为 canonical JSON + `\n`，`old_card_untouched=true`，首写字节在重复拒绝后不变。

---

## 8. Q1a-2 v1 适配层（重点）：PASS_WITH_RESIDUALS

证据：`independent/14-q1a2-adapter.py`（**93/93**，自建 30 题 payload，5/17/4/30/4/7 全形状；只用合成数据）。

- 正例：5 键顶层 / 17 键 bindings / 4 runs / case_count=30 / 30 cases / 4 轴 / 7 字段全部接受；`for_case`、`run_for_scenario` 正确；轴对象保持恰 7 字段；`expected_axes` 深度相等接受。
- **固定码拒绝 73 项**：`contract_schema_invalid` 16、`contract_binding_mismatch` 7、`contract_coverage_invalid` 6、`contract_axis_invalid` 26、`contract_basis_invalid` 6、`contract_semantics_changed` 6、`contract_unknown_downgraded` 6。逐项覆盖任务要求：schema_version 错、bindings 缺/多键与坏 hash、dataset/label 版本、runs 非 4/顺序/下标/空 run_id/坏 plan_sha、case_count≠30、cases≠30、case_index 错位、case_id 重复/空、axes 缺/多轴、轴对象缺/多字段、applicability/criterion/reason/temporal_intent 越界、target_refs 非列表/负值/bool/坏 collection/多键/重复、targets 非列表/缺键/空 entity_type/filters 非映射/值类型非法、as_of 非 ISO 与不可能日期、cross_user/stale 非 required、cross_entity N/A criterion 错、N/A + 5 个不确定 reason、basis 缺/多/越界/`no_provable` 与 required 组合。
- **`expected_axes` 专章（本次改动）**：一致 → 接受；改任一 7 字段值 / 缺字段 / 多字段 → `contract_semantics_changed`；case 集不一致 → `contract_coverage_invalid`；case 缺轴 → `contract_semantics_changed`；非 mapping → `contract_semantics_changed`；传 `expected_axes` 时结构/绑定/轴/basis/unknown 降级仍按各自固定码拒绝（不被语义检查吞掉）；**缺省 `None` 不弱化既有结构校验**（全部 73 项反例均在缺省下跑通）。
- 映射正确性：`scenario_id → run` 三键 bindings 注入；basis 按题注入且只进 provenance；来源标记默认 `frozen_contract`，`synthetic_fixture` 默认被拒；`cross_entity` mode 由注解映射；未知 case → `contract_coverage_invalid`；越界 target_ref 评分时 `unknown targets_unresolved`（不 pass）。
- 残余：R-12（ref 边界由消费者复核）、R-13（basis §4.1 复算由消费者）、R-14（targets 比较宽松）、R-17（语义深比较 opt-in）。

---

## 9. 零真实调用：PASS

证据：`independent/15-run-netguard-controls.py`、`15-positive-control.json`、`15-netguard-controls.out.json`、`10-static-reuse`、`18-dev-evidence-audit`。

- 模块 AST 导入白名单：仅标准库 + `.p2_evidence_rescore`；无 network/provider/product/`mktkb.rag`/旧评测器/`cryptography`/`base64`/`subprocess`/`os.environ`；无 monkeypatch。
- 测试文件的 `product_adapter` import 只在“零调用负向控制”函数内（patch `ProductEvalAdapter` 使其抛错），实现源码从不引用；模块唯一写入是 `write_axes_report` 的独占新建，唯一读取是契约/自身源文件 SHA256（源码扫描证实）。
- **正向控制**：在 netguard 下真实尝试 `socket.create_connection` / `socket.connect` / `getaddrinfo` / `httpx` 全部被 `NetworkBlocked` 拦截并记账（4 条 external 记录），随后清空记账使 teardown 通过 → 证明闸门不是空跑。
- **负向控制**：故意不清空 external 记账的测试在 teardown 报错（exit 1，命中“检测到真实外部出站尝试”断言）→ 证明记账断言真的会失败。
- 三轴重评 + 适配层在闸门下运行，external attempts=0；`calls` 全 0。

---

## 10. 契约 v0.2 逐值一致：PASS

证据：`independent/16-contract-consistency.py`（**42/42**，C 冻结文件只按 AST 读常量，不 import/不执行）+ `18-dev-evidence-audit`（38/38）。

- C 冻结词表逐值一致：`REASONS` 18 码 = 实现 `ANNOTATION_REASONS`；`AXIS_KEYS`(7)+basis/source = `ANNOTATION_KEYS`；三轴 `UNKNOWN_REASONS`/`VIOLATION_REASONS`/`PASS`/`NA`/`AXIS_CRITERIA` 与 C 逐轴集合相等；`TEMPORAL_INTENTS`、`TARGET_REF_COLLECTIONS`、`SCOPE_MODES`、`SHARED_BACKGROUND_BASES`、`BINDING_KEYS`、`QUALITY_STATUSES`、`AXIS_STATES`、`AXES` 顺序均一致。
- 契约 §7.2/§7.3/§7.4 的码表与实现集合逐值相等；§4.2 basis（7）与来源标记（7）枚举一致；`TRUSTED_SOURCES` 排除 synthetic/unresolved；Q1a-2 basis 5 码是子集。
- 判定优先级（§6.1）与实现一致：注解门 → scope → 合同/绑定 → 证据；unknown 折叠取首个固定 reason；`violation > unknown > N/A > passed`。
- **R-06** 已在 v0.2 消化：文档显式写出“首个 unknown reason”优先级，且不改变 state；**R-07** 已消化：`ref_doc_missing` 保留为防御码，公开 API 以 `ref_invalid` 先拒（实测不可达），未从冻结实现移除。
- **19/18 码笔误**：公开 schema §3.2 写“19 码”，实际列出 **18** 个，与 C `REASONS` 和实现一致；适配层按 18 码判，未新增第 19 码。
- 声明如实：v0.2 明示“不在本契约范围/不构成 Q1A 通过/Q1a-3 仍须”，§9 要求合并后才能称四轴完成；开发报告标注“待全新独立验收”，无正向 pass/release 句。
- 开发证据自洽：13 文件 manifest 13/13 命中实际字节；01-pytest 计数与退出码一致且无 skip/xfail；07 zero-call 的 calls/real_inputs/静态扫描/网络记账自洽；05-after 的 C12、15 modified、35 evaluator 与 38 Q1a-1 保护件全部命中实际；dev-report 哈希表 11 行全部命中实际字节。

---

## 11. 与开发报告的差异 / 补充

1. 开发报告 §4（22/20、exit 0）与 §6 哈希清单经实测**一致**；manifest 13/13、报告表 11/11 均命中当前字节。
2. 开发报告已声明 ref 边界、basis §4.1、语义深比较属消费者；本次把三条升级为**显式 carry-forward**（R-12/R-13/R-17，medium），因为不传 `expected_axes` 时“unknown→N/A + 良性 reason”会被结构校验接受（实测），Q1a-3 必须传 `expected_axes` 或执行合同 §5.7 深比较。
3. 开发报告未列的两处实现特性：annotation↔contract targets 用 set+`str()` 比较（R-14，类型/顺序/重复不敏感）；report 级 `axes_provenance` 三轴恒 `rescored`（R-11，preserved 只在 counts）。
4. 开发证据使用 `git status --porcelain` 的 untracked **条目**（201/205），任务单用 `-uall` **文件数**（2050）；两者自洽但口径不同（R-16）。
5. 过程事实（R-15）：验收开始（18:40:31）后，dev 证据文件在 18:40:32–18:41:33 仍被重生成（`dev-report.md`、`01-pytest.txt`、`06-hash-manifest.json`、`07-zero-call…` 等）；另有一个**非本包**文件 `scope-contract/manager-acceptance.json`（sha256 `2f570ae2…`）在验收期间由其他角色写入。被验收源码字节自 18:40:51 起稳定；本报告所有实测均对最终字节重跑，结束复核逐值相同。**未据此判 FAIL，但记为过程事实。**

---

## 12. 残余 R 码（必须由 Q1a-3/经理吸收）

| 码 | 级别 | 摘要 | 处理 |
|---|---|---|---|
| R-10 | low | v0.2 §5.1 称 cross_user N/A → `annotation_unknown`，但 §7.2 表无该码；实现用冻结表内 `evidence_incomplete`（state 一致、fail-closed） | 下一版修文档；不改实现 |
| R-11 | low | report 级 provenance 三轴恒 `rescored`，preserved 只在 counts | Q1a-3 读 counts，不得把 preserved 当 rescored |
| R-12 | medium | 适配层不校验 `target_refs` 冻结集合边界；越界评分时 unknown（不 pass） | Q1a-3/消费者按合同 §5.7 复核边界 |
| R-13 | medium | 适配层不复算 basis §4.1 映射 | Q1a-3 按 §5.8 复算（含 v0.3 gap 例外） |
| R-14 | low | targets 比较 set+str（类型/顺序/重复不敏感） | Q1a-3 传 `expected_axes` 或 §5.7 深比较 |
| R-15 | low | 验收期间 dev 证据重生成 + 他角色写入 scope-contract 文件；源码字节稳定 | 经理记录过程事实；以最终字节为准 |
| R-16 | low | dev 证据 untracked 计数口径（porcelain 条目 vs `-uall` 文件） | 统一用 `-uall` 文件数 |
| R-17 | medium | 语义相等强制为 opt-in；不传 `expected_axes` 时 unknown→N/A（良性 reason）不被结构校验捕获 | Q1a-3 必须传 `expected_axes`/执行 §5.7 深比较 |

---

## 13. 边界声明

- 只使用合成/公开数据；**未读**真实 H2 题面/标签/答案/逐题输出/私有密文/key/保管会话/`.env`/仓外合同密文。
- 零真实调用/预留/付费/GO；未启动服务；未跑全仓；未装依赖/浏览器。
- **未改**开发文件、`p2_evidence_rescore.py`、C 冻结 12、旧卡/账本/GO/阈值/标签/E0/E1/E2 冻结件；未 stage/commit/push；未新建 worktree/切换分支。
- 只新增本包文件（`axes/independent/**` 32 个 + `axes/independent-review.md` + `axes/review-aggregate.json`）。
- **本报告只覆盖 Q1a-1b 合成范围；不构成整体重评分，不构成 T207 通过、release、P2 完成或 Q1a-3 完成。**


