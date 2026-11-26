# R0/C12 安全边界收窄（item + contact 放行；item + phone/address 仍拒答）

日期 2026-11-16 · 全离线（0 真实请求、0 费用）· 未改冻结件 / fixtures / 账本 / 预算 / 题集 / 旧证据
结论：两个拒答判定点只认 `{phone, address}`；**item+contact 放行，item+phone/address、跨实体 phone 仍整体拒答；安全套件全绿、零非预期放行**。

## 1. 两处改动（两个判定点 + 1 个拒答专用常量）
| # | 文件:行 | 改动 |
|---|---|---|
| 1 | `backend/src/mktkb/rag/query.py:34-44` | 新增拒答专用 `REFUSAL_CONTACT_ROLES = frozenset({"phone","address"})`；`RESTRICTED_CONTACT_ROLES={contact,phone,address}` **值不变**（只更正注释口径） |
| 2 | `backend/src/mktkb/rag/query.py:1646-1647` | 规划层拒答条件 `set(field_roles) & RESTRICTED_CONTACT_ROLES` → `& REFUSAL_CONTACT_ROLES` |
| 3 | `backend/src/mktkb/rag/answer.py:22-26, 658-662` | 枚举兜底拒答 `for role in RESTRICTED_CONTACT_ROLES` → `for role in REFUSAL_CONTACT_ROLES`（两处同改，否则一处放行、一处仍拒） |

## 2. 红 / 绿（合成件，逐值可验）
内核层：`backend/tests/rag/test_r0_c12b_boundary_synthetic.py`（**12 passed**）。红证据来自临时探针：运行时把 `REFUSAL_CONTACT_ROLES` monkeypatch 还原成旧全集（等价改前代码、不改源文件、探针未入库）；绿为已入库断言：

| 问句（合成行：标识/门店/物品/位置/联系人…） | 旧口径 | 新口径 |
|---|---|---|
| 甲店立牌由谁对接？（行内只有 contact） | `no_answer` / SECURITY | `answer`，facts 含 `(contact, 阿甲经理)`，有引用 |
| 甲店立牌的联系人是谁？ | `no_answer` / SECURITY | `answer`，含 `阿甲经理` |
| 列出甲店立牌的全部信息（行内只有 contact） | `no_answer` / SECURITY | `answer`，含 `阿甲经理` |
| 电话 / 地址 / 位置+电话 / 找谁对接+电话和地址 | `no_answer` / SECURITY | 同左（不变，零引用、零泄漏） |
| 列出…全部信息（行内有 phone） | `no_answer` / SECURITY | 同左（不变） |

产品链路：`backend/tests/integration/test_r0_c12b_t7_boundary_e2e.py`（**3 passed**，离线 ASGI + 模型替身，数据集同 `test_v3_safety_fix_e2e.py`）：
- 改前（`R0-C12-TRUTH.md` + 本机改前探针）：t7 → `kind=not_found`、固定拒答文案、`sources=[]`、模型 0 调用；
- 改后：t7 → **`kind=answer`、`sources` 非空、`chat_model.calls` 非 0、正文无拒答骨架**；`item+只问对接人` 同样 answer；`item+电话` 仍 `not_found` + 模型 0 调用。

## 3. 安全套件逐件结果（全部实跑）
| 文件 | 结果 |
|---|---|
| `integration/test_v3_safety_fix_e2e.py` | 9 passed |
| `rag/test_t207_security_precedence_synthetic.py` | 6 passed |
| `unit/test_t207_v8_safety_contract_synthetic.py` | 1 passed |
| `unit/test_v3_safety_fix_policy.py` | 19 passed |
| `rag/test_t207_v8_enumeration_synthetic.py` | 3 passed |
| `rag/test_r0_11_contact_family.py` | 13 passed |
| `rag/test_r0_4 / r0_5 / r0_6_synthetic_repairs.py` | 10 / 12 / 13 passed |
| `rag/test_v3_fix2_record_scope_not_clarified.py` | 11 passed |
| `unit/test_t207_v8_followup_synthetic.py` | 3 passed |
| `evaluation/test_r0_repair_refusal_compat.py` / `test_r0_repair_c16_empty_scope.py` / `test_p1_refusal_controls.py` | 62 / 29 / 23 passed |
| 新增 `rag/test_r0_c12b_boundary_synthetic.py` / `integration/test_r0_c12b_t7_boundary_e2e.py` | 12 / 3 passed |

## 4. 回归统计
`tests/rag` + 上述 unit/integration/evaluation 文件：**771 passed / 1 failed**；唯一失败 = 既有失效 `rag/test_s4_stage_limit.py`（budget 40 vs 20，按令不管）。另跑 `unit/test_conversations.py` 51 passed、`integration/test_visible_index.py` 29 passed。无新增失败。

## 5. 既有安全断言更新披露（唯一一处，已获 lead 批准）
- 文件：`backend/tests/unit/test_v3_safety_fix_policy.py`（工作树内 **untracked** 文件）；仅第 2 条参数化换题，其余安全断言一字未动。
- 原文：参数 `"城东店展架的联系人是谁？"`，`test_rag_planner_marks_item_plus_contact_as_security_refusal` 断言 `parse_query` 必须返回 SECURITY —— 语义是 **item+只问 contact 的旧规划层口径**，与本轮 role 级收窄直接冲突（同形状改后必为 None）。
- 现文：改为 `"城东店展架的地址是多少？"`，测试名 `..._item_plus_phone_or_address_...`，注释指向本文件。
- 覆盖保留：planner 层 `item+phone` 2 条、`item+address` 1 条仍有断言（address 覆盖为本轮新增，未降级）；回答层 phone/address、跨实体、跨用户由 e2e / t207 / r0_11 继续覆盖。**不是放宽安全测试**：拒答角色集合不变、phone/address 边界不变，删去的只是“旧启发式自己的正例”；intent 层对 item+联系人 仍拒答（§6）。

## 6. 真实链路会不会重新触发拒答（lead 问句②）
- **t7 不会**：`intent.py:34-40` 的 `FIELD_SYNONYMS` 只登记「联系人」，t7 的「对接人」不在其中；`intent.py:507-527` 的受限字段交集为空 → `security_refusal=None`（本机 `parse_question` 实测），legacy 分支不二次拒答。规划层放行后该轮走 legacy 检索并作答；新增 e2e 合成件已实测 `kind=answer` 且调用模型。
- **item+联系人 产品行为不变**：legacy 仍由 intent 层拒答（未改）；只有 RAG 内核接手的轮次（多目标枚举 / 标识定位）按批准规则放行 contact。

## 7. 预期 C12 转 pass 把握与残余风险
- 拒答消除：**≈确定**（离线确定性，改前/改后同问句逐值对照）。
- C12 整案转 pass：**约 35–45%**。卡点不在安全层而在取数：期望值「王平 / 合作中」只在店家行，而 t7 的 `item` 实体过滤会把店家行排除；同款两表合成件实测答案只有「位置 C区2号货架」，并输出「资料中未记录：合作状态」。
- 若真实 envelope 的 t7 实体过滤只有 store（或已知 6→1 的角色裁剪 / 业务日窗口问题已修），把握升至 ~60%；**建议第十轮前先用已有 envelope 核 t7 的 legacy 单元数与 `requested_fields`，再决定付费**。
- 残余风险：① 多目标枚举 + contact 现在会作答（批准口径，但属新增可答面，需主人知情）；② 枚举兜底仍按“行内含 phone/address”拒答，含 phone 的整行枚举不降级；③ 未改 intent 层，导致「联系人」问法在 legacy 与 RAG 内核两条路径判定不一致（需在产品文档说明）。
