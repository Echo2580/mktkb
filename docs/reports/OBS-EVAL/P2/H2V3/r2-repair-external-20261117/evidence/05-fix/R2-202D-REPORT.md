# R2-202D 联结唯一性守卫（同门店多条店家行 fail-closed）— 修复报告

- 任务：T-R2-202D（承接独立验收 D=FAIL 的 D5a 项）
- 仓库：`D:\GPT项目\市场部AI知识库`，cwd=`backend/`
- Python：`.venv\Scripts\python.exe -X utf8`（3.12.7）
- basetemp（仓库外）：`D:\mktkb-p2-h2v3-r2-20261117\basetemp-202d`
- 日期：2026-11-17

## 0. 结论

| 项 | 结果 |
| --- | --- |
| FAIL 归因 | 独立验收已更正为**行基数**（同门店 2 条店家行同属同一 active 版本），不是版本过滤 |
| 修复面 | 只改 `backend/src/mktkb/rag/retrieval.py`（4 个 hunk，+60 −14）；`answer.py` / `facts.py` 未动 |
| 主例（同店 2 行） | 改前**红**（互斥状态值并出、`sources=3`、`total=3`）→ 改后**绿**（`sources=1`、无店家级值、`store_row_ambiguous`） |
| 回归口径 | 同店 1 行**逐项不变**（`total=2/returned=2/sources=2`，两值都在） |
| 敏感性 | 唯一性检查恒真 → 同店 2 行**回到红**；恢复即绿（守卫是唯一开关） |
| 回归 | 11 个既有文件：**10 个计数逐项不变**；`test_r2_204_independent_probes.py` 的 `test_204_d5a_...` 如预期转红（该探针断言的是缺陷本身，未改其文件，交回验收方） |
| 未做 | 无 git 写操作（无 commit/stash/checkout）；未跑全量 pytest / P1 全链 / 真实语料 ingest |

## 1. 红态（改前，实跑，不改源码）

新用例：`backend/tests/integration/test_r2_202d_uniqueness.py::test_same_store_two_rows_does_not_join`
合成语料：`物品位置台账.xlsx`（3 行）+ `合作店家信息.xlsx`（**青禾店 2 行**：`合作中` / `已终止`，同一 sheet、同一 active 版本、业务日窗口内）；
问题：`折叠桌的位置在哪里，合作状态分别是什么？`（`mode=record` + `enumerate=True` + `filters=["item"]` + `field_roles={location,status}` + 唯一物品目标）。

命令：

```powershell
cd backend
..\.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_r2_202d_uniqueness.py `
  -q -p no:cacheprovider --basetemp=D:\mktkb-p2-h2v3-r2-20261117\basetemp-202d\red --no-header -k same_store_two_rows
```

`EXIT=1`。**红态断言消息原文**（`--tb=long` 摘录，未改写）：

```text
E       AssertionError: 守卫缺失（红态）：同门店两行店家行被一并并入 → 合作中=True、已终止=True；sources=['物品位置台账.xlsx', '合作店家信息.xlsx', '合作店家信息.xlsx']（店家来源 2 条，rows=[4, 5, 6]）；pagination={'page': 1, 'page_size': 10, 'total': 3, 'returned': 3, 'has_more': False, 'next_page': None}；text='共 3 条，当前第 1 页显示 3 条。\n- 青禾店的折叠桌：位置 甲区1号架（来源：物品位置台账.xlsx）（记录 adddbced）\n- 青禾店：合作状态 合作中（来源：合作店家信息.xlsx）（记录 efaeeabd）\n- 青禾店：合作状态 已终止（来源：合作店家信息.xlsx）（记录 fbeabcdc）\n已显示全部。'
E       assert (True, True) == (False, False)
```

该失败态与独立验收 §2 D5a 记录的三项事实一致：**互斥状态值同时出现** / `sources` 3 条（物品 1 + 店家 2）/ `locator.row=[4,5,6]`、`total=3`。成因是 `_store_join_chunks` 只校验"店家行非空"，未校验**行基数**。

## 2. 守卫设计（fail-closed 三态）

### 2.1 判定链（只在 `_store_join_chunks` 内新增两级唯一性检查）

| 阶段 | 条件（**未改**，逐条保持） | 命中 | `status` |
| --- | --- | --- | --- |
| 触发 | `mode=record` + `enumerate` + 跨级角色（含 store 级与 item 级）+ `filters["item"]` 非空 + `state.items/stores` 均非多目标 | 不满足 → 原样早退 | `""`（不写诊断，行为同 202C） |
| 物品目标 | 物品行按记录身份**唯一**；门店值集合**唯一** | 不唯一 → 原样早退 | `""` |
| 门店值派生 | `stores`（去空后） | 空（派生不出） | `store_row_missing` |
| 门店值派生 | `stores` | >1（同一物品行给多个门店值） | `store_row_ambiguous` |
| 店家行 | 同门店店家行经同一 `_base_stmt`（活动/当前资料 + 记录与资料有效期窗口） | 0 行 | `store_row_missing` |
| 店家行 | 同上，按记录身份计数 | **>1 行** | **`store_row_ambiguous`（本批核心）** |
| 店家行 | 同上 | 恰好 1 行 | `joined`（并入，既有行为） |

固定码常量（`retrieval.py:284-286`）：`STORE_JOIN_JOINED="joined"`、`STORE_JOIN_MISSING="store_row_missing"`、`STORE_JOIN_AMBIGUOUS="store_row_ambiguous"`。

### 2.2 诊断载荷（只写固定码，不带业务值）

- 已联结：`{"store": <门店值>, "chunk_ids": [...], "status": "joined"}` —— **前两个键与值逐字同 202C**，仅新增 `status`。
- 两个 fail-closed 态：`{"status": <固定码>}` —— **不含**门店名、行数、chunk_ids（无业务值泄露面）。
- 触发条件不成立：**不建 `store_join` 键**（C1/C2/C3/C4/C6/C7 与此前逐字相同）。

### 2.3 改动清单（`retrieval.py`，行号为改后）

| 行 | 内容 |
| --- | --- |
| 284-286 | 三个固定码常量 |
| 289-301 | `class _StoreJoin(tuple)`：`(store_value, store_rows)` **二元组** + `status` 属性 |
| 303-305 | `_store_row_is_unique(store_rows)`：按 `record_unit_id or chunk_id` 计数 == 1 |
| 315-321 | `_store_join_chunks` docstring 增一条 fail-closed 说明（行基数≠版本语义） |
| 328-344 | 7 处 `return "", []` → `return _StoreJoin("", [], "")`（触发条件不成立，语义不变） |
| 346-352 | `stores` 空 / >1 拆成两个显式 fail-closed 分支 |
| 363-368 | `store_rows` 空 → `store_row_missing`；`not _store_row_is_unique(...)` → `store_row_ambiguous`；否则 `joined` |
| 377-384 | `_exact_recall`：取 `decision.status`；两个失败码写 `{"status": code}`；其余路径逐字保留原并入/诊断逻辑 |

为什么用二元组子类而不是三元组：既有 4 处敏感性开关都按**二元组**替换/解包本函数
（`test_r2_202a_...::test_third_loss_...` 的 `store_value, rows = real(session, plan)`；
202C/204 的 `lambda session, plan: ("", [])`；204 `_foreign` 的 `return STORE, rows`），
改元数会直接打红这些**不允许修改**的既有测试。判定码作为属性随值返回，解包写法与替换语义都不变；
被替换成裸二元组时 `status == ""`，行为回到 202C。

### 2.4 未改动的东西（自检）

- 触发条件：`mode/enumerate`、跨级角色判据、`filters["item"]`、多目标判据、物品行唯一性、`_base_stmt` 上界——一行未动。
- 安全/实体判据：`answer.py` 的实体绑定、`facts.py` 的 `joined_store` 例外、`REFUSAL_CONTACT_ROLES` 拒答、`conversations/intent.py` 计划层——全部未动（三文件中 `answer.py`/`facts.py` sha256 不变）。
- 联结行的排序/分页/RRF：未动（联结行仍不进 `fused`，仍不进重排）。

## 3. 绿（同店 1 / 0 / 2 行，全部实跑）

命令：`pytest tests/integration/test_r2_202d_uniqueness.py -v`（`EXIT=0`，**14 passed**）。

| 场景 | `total/returned` | `sources` | 店家级值 | `diagnostics["store_join"]` | 精确面实体 |
| --- | --- | --- | --- | --- | --- |
| 同店 **2 行** | 1 / 1 | `["物品位置台账.xlsx"]` | 无（`合作中`、`已终止` 都不出现） | `{"status":"store_row_ambiguous"}` | `["item"]` |
| 同店 **1 行** | 2 / 2 | `["物品位置台账.xlsx","合作店家信息.xlsx"]` | `合作中`（`已终止` 不出现） | `{"store":"青禾店","chunk_ids":[...],"status":"joined"}` | `["item","store"]` |
| 店家表**无该店**（0 行） | 1 / 1 | `["物品位置台账.xlsx"]` | 无 | `{"status":"store_row_missing"}` | `["item"]` |
| 物品行**门店值缺失** | 1 / 1 | `["物品位置台账.xlsx"]` | 无 | 不建键（触发条件不成立，逐字同 202C） | `["record"]` |
| 门店值派生不出（函数级） | — | — | — | `{"status":"store_row_missing"}` | — |

**同店 1 行的"逐字节不变"证据**（`test_same_store_one_row_still_joins`）：

1. 观测值（改后；`（记录 …）` 是 doc/version/unit 派生的 8 位指纹，每次 ingest 随机，故此处占位）：
   `text="共 2 条，当前第 1 页显示 2 条。\n- 青禾店的折叠桌：位置 甲区1号架（来源：物品位置台账.xlsx）（记录 <8hex>）\n- 青禾店：合作状态 合作中（来源：合作店家信息.xlsx）（记录 <8hex>）\n已显示全部。"`、
   `sources=["物品位置台账.xlsx","合作店家信息.xlsx"]`、`rows=[4,4]`、`pagination={page:1,page_size:10,total:2,returned:2,has_more:false,next_page:null}`。
2. 等价性：把唯一性检查 monkeypatch 成**恒真**（= 加守卫前的判定）后重跑同一问，断言 `kind/text/sources/pagination` 与不 patch 时**完全相等**（assert 全过）。
3. 改前基线：同一断言集所在的 202C/202A/203C 文件改前改后计数与断言全绿（见 §6）。

## 4. 既有反例 C1–C7（全部实跑，均 PASSED）

| 例 | 场景 | 结果 |
| --- | --- | --- |
| C1 | 只问位置（**在 2 行语料上**跑，更严） | `sources=["物品位置台账.xlsx"]`；无 `合作状态`/状态值；**不建 `store_join` 键** |
| C2 | 只问店家属性（1 行语料） | `filters=["store"]`；`sources=["合作店家信息.xlsx"]`；模型证据 1 条含「合作状态」不含「位置」；不建键 |
| C3 | 物品 + 电话 | `kind=not_found`、`reason=SECURITY_RESTRICTED_CONTACT`、`sources=[]`、模型 0 调用；不建键 |
| C4 | 同名物品落两店 | 物品目标不唯一 → 不联结；`sources={"物品位置台账.xlsx"}`；不建键 |
| C5 | 店家行过期（`截至2026-11-01`） | 记录面过滤后 0 行 → 不联结；`sources=["物品位置台账.xlsx"]`；`{"status":"store_row_missing"}` |
| C6 | 多物品目标 | `reason=MULTI_TARGET_ENUMERATE`；正文/来源与"关掉联结入口"**逐字相同**；不建键 |
| C7 | `mode=document`（制度回合） | 正文/来源与"关掉联结入口"**逐字相同**；不建键 |

说明：C5 此前不写任何 `store_join` 诊断，现在写 `{"status":"store_row_missing"}` —— 这是本批**新增的固定码**，
不改变正文/来源/计数；仓库内没有任何测试断言该键"不存在"，改后实测 10 个既有文件计数不变（§6）。

## 5. 敏感性（守卫是那条红例的唯一开关）

`test_uniqueness_guard_is_the_only_switch`（同一测试内三态）：

| 步骤 | 观测 |
| --- | --- |
| 守卫在（默认） | 无 `合作中`/`已终止`；`sources=["物品位置台账.xlsx"]` |
| `monkeypatch.setattr(rag_retrieval, "_store_row_is_unique", lambda rows: True)` | **回到红**：两值都在；`sources=["物品位置台账.xlsx","合作店家信息.xlsx","合作店家信息.xlsx"]`；`total=3`；`store_join.status="joined"` 且 `chunk_ids` **2 条**；精确面 `["item","store","store"]` |
| `monkeypatch.undo()` | 恢复绿：`text`/`sources` 与第一步**完全相等** |

## 6. 回归（只跑指定节点；命令模板 + 退出码 + 通过数）

命令模板（每个文件一条，逐条执行）：

```powershell
cd backend
..\.venv\Scripts\python.exe -X utf8 -m pytest <file> -q -p no:cacheprovider `
  --basetemp=D:\mktkb-p2-h2v3-r2-20261117\basetemp-202d\<tag> --no-header
```

| 节点 | 改前（基线） | 改后 | 退出码 | 判定 |
| --- | --- | --- | --- | --- |
| `tests/integration/test_r2_202c_c29_join_rag.py` | 13 passed | **13 passed** | 0 | 不变 |
| `tests/integration/test_r2_202a_c29_mechanism_synthetic.py` | 13 passed | **13 passed** | 0 | 不变（含二元组契约依赖的两例） |
| `tests/integration/test_r2_203c_f1_http_join_witness.py` | 5 passed | **5 passed** | 0 | 不变 |
| `tests/integration/test_r2_203c_f2_identity_http.py` | 3 passed | **3 passed** | 0 | 不变 |
| `tests/integration/test_r2_203c_f3_multiturn_http.py` | 7 passed | **7 passed** | 0 | 不变 |
| `tests/integration/test_r2_203c_f4_caseplan_set.py` | 6 passed | **6 passed** | 0 | 不变 |
| `tests/integration/test_r2_204_independent_probes.py` | 15 passed | **14 passed, 1 failed** | 1 | **`test_204_d5a_same_store_two_rows_reachability` 转红（预期）** |
| `tests/rag/test_r0_c12_join_synthetic.py` | 7 passed | **7 passed** | 0 | 不变 |
| `tests/integration/test_r0_c12b_t7_boundary_e2e.py` | 7 passed | **7 passed** | 0 | 不变 |
| `tests/evaluation/test_r1_102d_turn_pagination.py` | 8 passed | **8 passed** | 0 | 不变 |
| `tests/evaluation/test_r1_102a_structural_numbers.py` | 9 passed | **9 passed** | 0 | 不变 |
| `tests/integration/test_r2_202d_uniqueness.py`（新增） | 改前 1 failed（红例） | **14 passed** | 0 | 新增 |

唯一转红的归属判定：**由本守卫直接引入、且属于"探针断言的是缺陷本身"**，不是回归。

```text
FAILED tests/integration/test_r2_204_independent_probes.py::test_204_d5a_same_store_two_rows_reachability
WITNESS204 {"both_statuses_present": false, "kind": "answer", "rows": [4], "sources": ["样例位置台账.xlsx"],
            "tag": "d5a", "text": "共 1 条，当前第 1 页显示 1 条。\n- 云杉店的样品柜：位置 北区2号架（来源：样例位置台账.xlsx）\n已显示全部。"}
E   assert False is True     # 该探针第 547 行 assert both is True
```

该用例的判据是"两条都并入 = 可达"（缺陷观测），守卫生效后必然为 `false`。按任务约束**未修改该文件**，
交回验收方把 D5a 的断言更新为守卫后的期望（`both_statuses_present=false`、`sources` 1 条、`rows=[4]`、
`store_join.status="store_row_ambiguous"`）。

## 7. 出站 / 子进程守卫

- 新用例模块级 `pytestmark = pytest.mark.usefixtures("t09_network_guard", "no_subprocess")`。
- `test_offline_chain_has_zero_external_network_and_no_subprocess` 显式断言 `t09_network_guard.snapshot()["external"] == []`，并断言子进程拦截账本 `no_subprocess == []`（`subprocess.Popen`/`run` 调用即 `AssertionError` 并计数）。
- 本批所有回归运行均为离线合成链路（`settings` 无 provider 配置、`isolate_dotenv_in_test_process` 关掉 `.env`），无真实出站。

## 8. 交付物与校验

| 交付物 | 路径 | 校验 |
| --- | --- | --- |
| 源码 diff（整文件） | `evidence/05-fix/R2-202D-src-diff.patch.txt` | `git diff -- backend/src/mktkb/rag/retrieval.py`；**16 个 hunk 含 R0/R1 他批**，本批 4 个 hunk 全落在 `@@ -224,12 +265,135 @@` 内 |
| 本批 hunk（反向可应用） | `evidence/05-fix/R2-202D-MINE-rollback.patch.txt` | 4 hunk，+60 −14；`git apply --check -R` → **EXIT=0**；在一次性 scratch 仓库里 `git apply -R` 后文件 sha256 = `aee14c82…`（与 `snapshot-at-pause/retrieval.py.parked.txt` **字节相同**） |
| 报告 | `evidence/05-fix/R2-202D-REPORT.md` | 本文件 |
| 新测试 | `backend/tests/integration/test_r2_202d_uniqueness.py` | 14 passed |

头文件标注说明：`R2-202D-src-diff.patch.txt` **不能**整体反向应用（会打掉 R0/R1 未提交成果）；
回滚只用 `R2-202D-MINE-rollback.patch.txt`（`git apply -R`）。

三文件 sha256：

| 文件 | 改前 | 改后 |
| --- | --- | --- |
| `backend/src/mktkb/rag/retrieval.py` | `aee14c827578fa7918ac8c2cc06672bff9959077aee7e931d5f2a59611765f4e` | `d43530922355206746e40316d6dd5a875da6a3081c68db866cffa2d61b2abdaa` |
| `backend/src/mktkb/rag/answer.py` | `b89622beb20f0d73849f2af9dab91a54835a24006059b3ff38a8d67b40e20288` | **同改前（未动）** |
| `backend/src/mktkb/rag/facts.py` | `cf795cfd16fe15fdfa73f9bc12311cf9bcf55b2fafdb67a9a8f6719192dc7001` | **同改前（未动）** |

## 9. NOT-RUN / 风险 / 需交回验收方

### 9.1 NOT-RUN

1. **真实 H2V3 语料上的 D5a**：未跑 ingest（独立验收 §4 已按 manifest/D02 的"每店 ≤1 行 + V06 是 D02 v2"判定真实语料下不可达；且真实语料 ingest 属 T-R2-205 范围）。
2. **全量 `pytest`**、P1 全链评分（`runner.score_case`）、真实 provider / live H2 / OCR：均未跑（按任务约束只跑指定节点）。
3. **`total` 1→2 / 2→1 的评测口径影响**：本批不涉及 `total` 语义变更，但"同店 2 行"从 3 条变 1 条会改变该形态的计分输入；未跑 P1/P2 评分重算。
4. **多页联结（`total > page_size`）**下的 2 行形态：未构造（与 203A-D2 的既有已知面重叠）。

### 9.2 风险与已知边界

1. **`test_204_d5a_...` 现为红**（见 §6）。它不是回归，但会污染"全绿"口径；须由验收方更新断言或登记为已知红项。**本批未改该文件**。
2. **"门店值派生不出"在语料层不可达**：`rag/chunking.py::_entity_of` 的 `entity_type` 判据要求 store 与 item **同时存在**，门店值为空的行会落到 `entity_type="record"`，因此 `item_rows` 为空 → 触发条件不成立 → **不写 `store_join`**（与 202C 逐字相同）。任务里"门店值派生不出 → `store_row_missing`"这一态只能落在守卫函数内部（`stores` 去空后为空），本报告用函数级用例 `test_underivable_store_value_maps_to_missing` 钉住该映射，未放宽触发条件。
3. **同店 2 行时"只问店家属性"的问题会在计划层被判多候选**（`kind=clarification`，"存在多个可能对象"）：与守卫无关（`conversations/intent.py` 实体解析，未改、改前亦如此），但同店重复行会让这家店的**所有**店家级问题变成不可作答。若真实语料出现同店重复行，这是比 D5a 更早暴露的问题面，建议纳入后续任务。
4. **`store_row_ambiguous` 的语义覆盖**：既表示"同门店命中 >1 条店家行"（本批核心），也表示"同一物品行给出多个门店值"（防御分支）。两态在诊断里不细分，如需区分要另立固定码（会改动诊断契约，本批不做）。
5. **`_StoreJoin` 是二元组子类**：对按二元组解包/替换的既有用法完全兼容（已实测 202A/202C/204 三处替换），但它确实是一个"值上挂属性"的运输方式；若后续要改三元组，需同步 4 处既有 monkeypatch 测试。
6. **诊断键的可见面**：`store_join` 不进 HTTP 响应体（`answer._finish_diagnostics` 只挑固定键），也不进评测四轴；本批新增 `status` 只影响进程内诊断读取方。
7. **C5 语义微变**（诊断层面）：过期行从"无 `store_join` 键"变为 `{"status":"store_row_missing"}`；正文/来源/计数不变，仓库内无测试断言其缺失。
