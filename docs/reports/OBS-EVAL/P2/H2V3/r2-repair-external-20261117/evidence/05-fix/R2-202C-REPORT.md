# R2-202C / C29 跨实体取数最小修复 —— 暂停收尾报告

- 收尾选项：**A（收敛到绿）**。本批 hunk 已落地并通过自建红/绿用例、202A 同形复现、R0 保护面与安全面共 9 个节点 91 例。
- 暂停时刻：2026-11-17T17:32+08:00。源码 3 个文件、新增/改写的 2 个测试文件、本报告与补丁均已落盘。

## 1. 现场固定（sha256 / mtime）

| 文件 | sha256 | mtime |
|---|---|---|
| `backend/src/mktkb/rag/retrieval.py` | `aee14c827578fa7918ac8c2cc06672bff9959077aee7e931d5f2a59611765f4e` | 2026-11-17T17:27:32+08:00 |
| `backend/src/mktkb/rag/answer.py` | `b89622beb20f0d73849f2af9dab91a54835a24006059b3ff38a8d67b40e20288` | 2026-11-17T17:27:55+08:00 |
| `backend/src/mktkb/rag/facts.py` | `cf795cfd16fe15fdfa73f9bc12311cf9bcf55b2fafdb67a9a8f6719192dc7001` | 2026-11-17T17:28:04+08:00 |

当前字节副本：`evidence/05-fix/snapshot-at-pause/{retrieval,answer,facts}.py.parked.txt`（原样，仅加后缀）。

## 2. 改点（9 个 hunk，逐个一句理由）

`rag/retrieval.py`
1. `:13` `from dataclasses import replace` —— 取店家行时用 `replace(plan, filters={"store": 值})` 换过滤键。
2. `:269/:274/:282` 新增 `_STORE_LEVEL_ROLES`/`_ITEM_LEVEL_ROLES`、`_requested_roles`、`_store_join_chunks` —— 全部触发条件成立才反推门店并取店家行（fail-closed，复用 `_base_stmt` 的活资料/版本/业务日窗口）。
3. `:340` `_exact_recall` 并入联结店家行并写 `diagnostics["store_join"]` —— 候选层补回店家行，且只进记录面候选、不进 RRF/重排。

`rag/answer.py`
4. `:287/:297/:301/:306` 新增 `_store_join`/`_store_join_ids`/`_store_join_value`/`_record_marker` —— 只读检索层写入的联结载荷，并用既有记录指纹做逐行归属（不新建反推逻辑）。
5. `:354` 答案侧单角色裁剪保留联结行 —— 否则店家行（无 location 角色）在第二层被丢掉。
6. `:861` 枚举渲染加 `joined` 标记 —— 联结轮次才按记录身份逐行渲染。
7. `:883` + 两处行文本追加 `{marker}` —— 分实体分行渲染，避免「青禾店的折叠桌」与「青禾店」标签互污。
8. `:937` `FactValidator(..., joined_store=...)` —— 显式绑定只在触发成立时传入。

`rag/facts.py`
9. `:54/:63/:114` 新增 keyword-only `joined_store` 与 `_joined_store_row`，实体过滤比对仅在「该行门店值 == 联结门店」时放行联结店家行 —— 不是"忽略过滤"，`cross_entity` 判据与 `_assert_entity_value_binding` 一行未改。

## 3. 红 → 绿实测（合成，虚构实体；`POST /conversations/{id}/messages` 真实链路）

| 形态 | 修前（本次会话实测红） | 修后（绿） |
|---|---|---|
| A（只点名物品 + "分别"，`filters=[item]`） | `共 1 条…显示 1 条`；正文只有位置值；`sources=[物品位置台账.xlsx]`；模型 0 调用 | `共 2 条…显示 2 条`；两行分别含 `甲区1号架` 与 `合作中`，各带 `（记录 xxxxxxxx）`；`sources=[物品位置台账.xlsx, 合作店家信息.xlsx]`；模型 0 调用 |
| B（点名门店 + 物品 + "分别"，`filters=[item,store]`） | 与 A 逐字相同（证明 R0 补丁不在此路径） | 与 A 逐字相同（两类值/两条来源） |

证据面（RAG 直答不调模型）：`facts` 覆盖 `("location","甲区1号架")` 与 `("status","合作中")` 两组，`entity_label` 为 `{青禾店的折叠桌, 青禾店}`，`citations` 的 `doc_id` 2 个不同。

## 4. 反例（逐条，全部绿）

| 用例 | 结果 |
|---|---|
| C1/R3 只问位置 | 1 条/1 来源，无 `合作中`、无「合作状态」；模型 0 调用 |
| C2/R4 只问店家属性 | legacy 路径不变：`filters=[store]`、1 次模型调用、`sources=[合作店家信息.xlsx]`、无位置值、模型证据仅 1 行（有「合作状态」无「位置」） |
| C3 物品 + 电话 | `not_found` + `SECURITY_RESTRICTED_CONTACT`，`sources=[]`，检索/模型前整体拒答，模型 0 调用 |
| C4 同名物品落两店 | 目标不唯一 → 不联结：`sources={物品位置台账.xlsx}`，无 `合作中` |
| C5 店家行过期（业务日 2026-11-01 / 失效 2026-10-31） | 不联结：1 来源，无 `合作中` |
| C6 多物品目标枚举 | `MULTI_TARGET_ENUMERATE`；正文/来源与「关掉联结入口」逐字相同 |
| C7 政策/正文回合（`mode=document`） | 正文/来源与「关掉联结入口」逐字相同，不含位置值/合作状态值 |

## 5. 敏感性（互不吞并）

1. `monkeypatch rag.retrieval._store_join_chunks → ("", [])`：A/B 回到修前形态（1 值 / 1 来源），即入口确实是唯一开关。
2. `monkeypatch retrieval.service._store_join_ids → set()`：legacy 形态（无枚举词）从 `answer`（两类值/两来源）转 `service_error`，模型证据仅 1 行、无「合作状态」。
3. 同一 R0 开关下 A 形态仍绿（两类值/两来源）：本批联结不经过 R0 入口。

## 6. 回归（命令 / 退出码 / 通过数）

| # | 命令（cwd=`backend/`，`..\.venv\Scripts\python.exe -X utf8`） | 退出码 | 结果 |
|---|---|---|---|
| 1 | `-m py_compile src/mktkb/rag/{retrieval,answer,facts}.py` | 0 | 3 文件编译通过 |
| 2 | `-m pytest tests/integration/test_r2_202c_c29_join_rag.py -q` | 0 | 13 passed |
| 3 | `-m pytest tests/integration/test_r2_202a_c29_mechanism_synthetic.py -q` | 0 | 13 passed（改造后） |
| 4 | `-m pytest tests/rag/test_r0_c12_join_synthetic.py tests/integration/test_r0_c12b_t7_boundary_e2e.py -q` | 0 | 14 passed |
| 5 | 上述 4 文件 + `tests/rag/test_r0_c12b_boundary_synthetic.py`、`tests/rag/test_r0_c12_legacy_trim_identifiability_synthetic.py`、`tests/unit/test_v3_safety_fix_policy.py`、`tests/unit/test_t207_v8_safety_contract_synthetic.py`、`tests/integration/test_v3_safety_fix_e2e.py` | 0 | **91 passed / 40.58s** |

既有失败：本批未出现（上述节点全部通过；无"既有失败"需要判定）。

202A 的改动说明（断言强度不降）：6 例原为"修前红态"断言，按新行为翻面并加严（A/B 改为两类值+两条来源；候选层增加 `store_join` 诊断断言；答案侧由"共2条/显示1条"改为"显示2条"；事实绑定、行归属各自新增 fail-closed 反例：联结门店被改成异店 → `not_found`「事实来源不满足问题实体条件」；两行记录指纹互不相同）。文件例数 13 → 13，无净删除。

## 7. 守卫（出站 / 子进程）

- 新文件模块级 `pytestmark = usefixtures("t09_network_guard", "no_subprocess")`，13 例全部在守卫下；
- 专测 `test_offline_chain_has_zero_external_network_and_no_subprocess` 显式断言 `snapshot()["external"] == []` 与子进程计数 `== []`；
- `no_subprocess` 同时封 `subprocess.Popen`/`run`（调用即 fail 且计数）；无其它子进程来源。

## 8. 回滚（只回本批，不动 R0/R1）

```bash
cd "D:/GPT项目/市场部AI知识库"
git apply --check -R docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/05-fix/R2-202C-MINE-rollback.patch.txt   # 预检（已实测 exit 0）
git apply -R       docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/05-fix/R2-202C-MINE-rollback.patch.txt   # 回滚 9 个本批 hunk
```

- `R2-202C-src-diff.patch.txt` = 完整 `git diff` 记录（**含他批 hunk**，文件头有逐 hunk 归属表），**不要**用它整体回滚。
- `R2-202C-MINE-rollback.patch.txt` 由 `R2-202C-rollback-reconstruct.py` 反向重建生成，只含本批 9 个 hunk；已通过 `git apply --check -R`，回滚结果 `py_compile` 通过。
- 回滚后三个文件应有 sha256：`retrieval.py=3ee0511be4106724bac7f8761c6a604a7fab81bc2ca0109ff9b450d19eebab71`、`answer.py=b4a3ad88147a2d4a08174617a45420d83be2b8ec16ce237e53f39d3acf91ac99`、`facts.py=42cdfeb28abc6fbb11ce9c10162b1628a74dea665ae7257823f2953eba832f49`。
- 测试侧回滚：删除 `backend/tests/integration/test_r2_202c_c29_join_rag.py`；202A 的 6 例改写无文件备份，红态原文见 `evidence/04-mechanism/R2-202A-REPORT.md`（本批未删除任何用例）。

## 9. 未完成（NOT-RUN）与已知风险

1. **NOT-RUN**：任务书 S4 剩余节点未跑 —— R1 保护面（`test_r1_102a/102b*/102c*/102d/106a*/106b*`、`tests/integration/test_r1_103_*`、`test_r1_107_*`）、日期/版本（`test_v3_fix1_business_date_filter.py`、`test_p2_stale_version_state.py`）、实体（`test_r2_202b_entity_identity_e2e.py`、`test_unit_entity_key_parity.py`）、判定链（`test_r0_repair_same_round_inputs.py`、`test_p2_evidence_rescore*.py`、`test_p2_cross_entity_scope_v02.py`、`test_r1_108_compat_v06.py`）。全量回归、真实 H2、真实 provider 均未跑。
2. **未触碰**：`cross_entity` 判据、`_assert_entity_value_binding`（行内实体归属）、`value_no_fabricated`/`value_forbidden`/`source_forbidden`/`refusal_*`、评分器/合同/题集/阈值/fixtures/docs/evaluation 全部未改。
3. **风险：`total`/分页变化**。C29 形态的 `total` 由 1 变 2（预期内），但队列里若有对「共 N 条 / 显示 N 条」的硬编码断言（尤其 102d 分页）未复核 —— 建议接手窗口优先跑 102d。
4. **风险：联结行的候选口径**。联结店家行进 `result.exact`、不进 `fused`（`_passes_filters` 仍按原过滤排除），因此 `diag["filter"]` 在这些轮次会记录 `filter_miss`；产品路径不传 `diag`，暂无可见影响，但其它读 `diag` 的调用方需知晓。
5. **风险：多条同门店店家行会全部并入**（`_base_stmt` 内所有 `entity_type=="store"` 行），未做"取最新一行"的收敛；多页场景下联结行可能落在第 2 页，未专门测试。
6. **风险：`enumerate` 是本批触发条件之一**（未列入任务书原文）。理由：非枚举的 record 轮次走 legacy（R0 已覆盖），把 gate 收紧可保证"其余形态逐字不变"；若后续要覆盖非枚举 RAG 轮次需另行评估 `_multi_field_answer`/`ambiguous` 分支。
7. **风险：202A 为未提交文件**（`??`），本批原地改写了 6 例断言；若需保留红态原文，应在新窗口从 `evidence/04-mechanism/R2-202A-REPORT.md` 复核。
