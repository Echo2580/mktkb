# R0/C12 — legacy 记录检索「6 候选 → 1 条」定位（离线，0 元，未发真实请求）

日期 2026-11-16　范围：只读 `backend/src/mktkb/retrieval/service.py` + 新增合成件
结论：**不改产品代码**——在不读正文、不读私有材料的前提下，这一刀**无法唯一指认**；缺 1 个固定码级数据。

## 1. 结论（先给主人）
- 第九轮的「候选 6、期望来源 2/2 在候选、legacy 只剩 1」三条**可以同时成立**，但**不足以指认**
  `service.py` 的哪一处；同一组观测在我的合成件上由**两个不同修点**逐值复现：
  ① 角色覆盖裁剪（`_units_with_roles`/`_units_with_field_labels`）；② 业务日窗口裁剪（`_drop_out_of_window`，v3-fix-1/B）。
- **`entity_filter_equality` 已排除**（§3，可机械检验）。
- 另有一件必须先核：C12 是 **t6/t7 两回合**（FINAL-REPORT §10.1），评分取**末轮**（`p2_scoring.py:823-836`），
  而第九轮投影行写的是 `C12/t6`。**若该投影取自首轮，`legacy=1` 就是正确行为**（只问位置时，只有位置的行才是证据；
  店家行只带合作状态）。这一点不需要新请求，只需在同一 envelope 里换 `turns[-1]` 复算。

## 2. 命中机制枚举（record 型把候选裁到 1 的全部固定落点）
| # | 机制 | 文件:行 | 触发条件 | 能否 6→1 |
|---|---|---|---|---|
| M1 | 实体等值（store/item） | `service.py:162-180`，调用 360-362 | 同一行必须同时具备每个筛选键的角色 | **否**（§3 证明） |
| M2 | 角色覆盖裁剪 | `service.py:311-326 / 329-345`，应用 416-432 | `requested_fields` 能解析出 `HEADER_ROLES` 角色；被裁行既无该角色、表头也未逐字命中请求标签 | **是**（唯一可达的“按字段”裁点） |
| M3 | 同记录分组 / 正文-表格合并 | `service.py:399-410`、`276-308` | 同 `entity_key` 合并；只**增**成员，不丢单元 | 否 |
| M4 | store-only 收敛 / 同门店并组 | `service.py:439-468`（449 收敛、463 并组） | 有 store 键无 item 键；全部请求角色 ⊆ `_STORE_RECORD_ROLES` 才收敛；否则按 `entity_filters["store"]` 并组，值不匹配的行被丢 | 否（候选都带同一 store 值，并组不丢） |
| M5 | 冲突切片（`total==1`） | `service.py:487-493` | 单组且某请求角色有 ≥2 个不同值 | 否（一个冲突角色至少要 2 个单元） |
| M6 | limit / 截断 | `service.py:471-497` | `limit=20`，本轮 `truncated=false` | 否 |
| M7 | 业务日窗口（不在 lead 清单里） | `service.py:80-84`，应用 382（记录）/528（正文） | `as_of` 非空且行自带生效/失效窗口不覆盖业务日 | **是**（上界生成用 `include_future=True`、无业务日，`qa/service.py:626/649`） |

## 3. 为什么 M1 不可能（可机械检验）
候选上界由**同一份** `intent.entity_filters` 生成：`conversations/service.py:2524-2531` → `qa/service.py:591-631`
（`filters` 直接进 `QueryPlan.filters`）→ `rag/retrieval.py:192-252`（每个键对 `filters_norm` 等值 AND）。
- 单键：上界里每一行都带该值 ⇒ `_filter_ids` 裁不动；
- 双键（store+item）：同一行必须同时具备两个角色 ⇒ 跨文档的另一条期望来源**进不了上界** ⇒ 与「2/2 在上界里」矛盾。
合成件 `test_entity_filter_equality_needs_an_inconsistent_bound` 把这两条都钉住了。

## 4. 合成红/绿（新增 `backend/tests/rag/test_r0_c12_legacy_trim_identifiability_synthetic.py`，10 passed）
假门店「甲店」/假物品/假表头/假值；6 候选取 1 条含“位置”的物品行 + 4 条只含“数量”的同门店行 + 1 条含“合作状态”的店家行。
- 绿（形状复现）：只问「位置」→ `kind=matches`、`units=1`、只剩物品行；被裁的正是跨文档的期望来源 #2。
- 绿（反例）：同一份候选问「位置+合作状态」→ **2 条**（各自带一项角色）⇒ 该问法下 M2 不是断点。
- 绿（歧义）：`as_of=2026-11-01` 时同形状由 M7 产生（物品行窗口 10-31 过期、店家行 11-15 在窗内）⇒ 观测不可辨识。
- 红（候选修点被证伪）：直接去掉 M2（monkeypatch `_units_with_roles` 保留全部）→ 6 条全进证据面，多带 4 条无关行 + 店家行，
  违反「不因修复多出无关记录」⇒ 不能作为 C12 的修点。
- 绿：M5（2 条冲突单元仍 2 条）、M6（25 条 -> 20 条）、单实体单记录（1 条不变）、空候选不回退。

## 5. 缺什么（固定码级）与修点真值表
缺的只有一个**身份级**数据（不是正文）：**被 legacy 保留那 1 个单元的 `unit_key` + `entity_type`**，加该轮 `requested_fields`（已知 t6 `[location]`、t7 `[location,status]`）。
被引用单元的身份已在同一 envelope：`db_projection.units[].unit_key/entity_type`（`p2_evidence_capture.py:1218-1239`；本轮 cited=1 且 legacy=1，两者若同一即已具备）。**0 元、无正文。**
取数配方：`gold={f"sheet:{loc['sheet']}:row:{loc['row']}" for loc in case.expected_sources}` vs `got=db_projection.units[0].unit_key`，t6/t7 各做一次，`gold-got` 就是那一刀（骨架 `work/r6_c12_sources.py:64-101`：`turns[-1]` 改逐轮、计数改集合差）。

| 同 envelope 读到 | 断点 | 唯一最小修点 |
|---|---|---|
| 保留 = 物品行，且该轮请求含店家级角色（`status` 等） | M2 角色覆盖裁剪 | `service.py:416-432`：把“本轮请求字段的覆盖判定”扩展到同一门店下被点名的另一实体行（只做并集补充） |
| 保留 = 任一条期望行，而另一条 `date_fields` 不覆盖业务日 | M7 业务日窗口 | `service.py:382`：候选上界与 legacy 证据面的业务日口径对齐 |
| 保留 = 二者之外的第三行 | M1/可见性（两套实体派生不一致） | `service.py:360-362`：有 `candidate_ids` 时不再用第二套派生做等值收窄 |
| legacy 单元=2、最终引用=1 | 检索之后（引用/渲染） | 不在 `service.py` |

## 6. 测试统计（本轮实际执行）
| 批次 | 结果 |
|---|---|
| 新增合成件（10 条） | **10 passed** |
| `tests/rag` + `unit/test_retrieval.py` + `unit/test_conversations.py` + `integration/test_visible_index.py` | **622 passed / 1 failed**（`test_s4_stage_limit.py` 40 vs 20，既有失效，按令不管） |
| 安全三件 `rag/test_t207_security_precedence_synthetic.py`、`unit/test_t207_v8_safety_contract_synthetic.py`、`integration/test_v3_safety_fix_e2e.py` | **16 passed**（与基线逐值相同） |
| 产品代码 / 冻结件 / fixtures / 账本 / 预算 / 题集 / 阈值 | **零改动**（本轮只新增 1 个测试文件 + 本报告） |

## 7. 预期 C12 转 pass 的把握与风险
- **现在不能承诺**：任一单点修复都只是 1/2 概率的猜测，且前两轮已证“改 legacy 不改检查码”；
  按「只改证实命中的那一处」本轮不做猜测性改动。
- 给出 §5 的 1 个身份数据后：对应分支的单点修改把握 **≥80%**（分支内因果是合成的、逐值可验）。
- 风险：① `unit_key` 只有 `sheet:row`、不含 doc 身份，跨文档同名表会撞键（实例中 D01/D02 表名不同，暂不撞）；
  ② 若断点在 M7，修的是业务日/上界口径而不是过滤，需重跑真实 r0 才能确认；
  ③ 若 t7 的 `legacy` 单元其实是 2 而引用是 1，则整个 C12 应转“引用/渲染层”，本报告的排除结论仍成立。
