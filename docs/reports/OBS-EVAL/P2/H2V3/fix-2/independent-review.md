# fix-2 独立窄验收（v3 终局执行者 · 段 1）

- 角色：v3 终局执行者。每次称呼"主人"。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；本包开始与结束**暂存均为 0**；未 stage / commit / push；未新建 worktree / 切分支。
- 本段**零真实调用 / 零真实请求**：出站拦截 0 次（§6），全部离线（临时 SQLite + offline provider）。
- 结论：**`PASS`（可进入复跑）**，附 3 条不影响本次复跑的残余（§7）。
- 关键数字：自建 16 例探针，**改后 16/16**、**改前 11/16**，且失败的 5 例**恰好全是 A/B 正例**（同一份探针只换 src）→ 机制因果成立，而非"本来就这样"。
- 回归：9 个定向测试文件 **102 passed / 0 failed / 0 error**（出站 0）；C 冻结 12、语料 13、评测模块**均未变**。

---

## 1. 验收对象与"不照抄开发用例"的口径

| 项 | 内容 |
|---|---|
| 交付目录 | `docs/reports/OBS-EVAL/P2/H2V3/fix-2/`（`dev-report.md`、`evidence/`、`fix-2.diff`） |
| 本包新增 | `independent/`（本目录）：自建探针、反向重建器、保全核对器、对比器、netguard |
| 自建问句 | 16 条，**全部为本包新写**，与 `test_v3_fix2_*` 开发用例的问句集合**无交集**（见 §2 / `independent/independent-probe.json`） |
| 自建记录 | 6 条，位置取值（北区一排货架/西区二排货架/前台内侧墙面/电梯口立柱/收银台正面/生鲜区端头）与开发用例取值（A区1号货架…）**不同** |
| 词表来源 | 公开语料 `fixtures/acceptance-h2v3` 的记录身份（门店/物品/字段名），**不是题面** |
| 真实题面/答案 | **未读取、未打印、未落盘**；探针只用合成问句与合成记录 |

本包**不采信**开发报告对"改前"的声明，改为**自己反向重建改前源码**（§4），再用同一份探针跑改前/改后对照。

---

## 2. A 类（C20/C22/C30 型）：信息足够 → 直接作答

自建议题形态：**2 门店 + 1 物品 + 记录字段（location）**，题面顺带出现"清单/资料"字样或一个非量化的行文回指词（"那个"）。

| # | 自建问句 | 改前（重建版） | 改后（现仓库） | 判定 |
|---|---|---|---|---|
| A1 | 城东店和城西店的易拉宝那个位置，查**物料清单**确认下 | `DOCUMENT_NOT_FOUND` / `clarification=true` / `owns=false` / `no_answer` / 0 引用 | `MULTI_TARGET_ENUMERATE` / `clarification=None` / `owns=true` / `answer` / `returned=2` / **2 引用** | ✅ |
| A2 | 城东店和城西店的宣传海报那个位置在**D01和D02**里分别是怎么写的 | `DOCUMENT_AMBIGUOUS` / `clarification=true` / `owns=false` | `MULTI_TARGET_ENUMERATE` / `owns=true` / `answer` / `returned=2` / 2 引用 | ✅ |
| A3 | 城东店和城西店的宣传海报那个位置，对照**存档资料**核一下 | `DOCUMENT_NOT_FOUND` / `clarification=true` / `owns=false` / 0 引用 | `MULTI_TARGET_ENUMERATE` / `owns=true` / `answer` / `returned=2` / 2 引用 | ✅ |

- 取值面核对：A1 只含"前台内侧墙面/电梯口立柱"（两店易拉宝），**不含**其他 4 条记录取值；A2/A3 只含两店海报取值。既不作答成整表，也不漏另一店。
- 与封存证据的**结构性同形**（不是同一题面）：改前三例的 `(clarification=true, enumerate 语义为否, owns=false, 交回 legacy)` 与 v3 首轮 C20/C22/C30 的 `plan_observed`（`path=legacy / mode=document / filters={} / enumerate=false / clarification=true`）**同形**；改后三例都由内核按目标逐条作答。
- **A 类安全面不回退**（A4）：`城东店和城西店的易拉宝那个位置，连门店的联系电话一起发我` → 改前改后**都是** `SECURITY_RESTRICTED_CONTACT` / `no_answer` / **0 引用 / 0 取值**（物品记录 + 店家联系信息合并仍在检索前拒答）。

## 3. A 类反例：**真歧义仍澄清**（3 类齐全 + 1 类补充）

| # | 类别 | 自建问句 | 改前 | 改后 | 判定 |
|---|---|---|---|---|---|
| N1 | 两店 × 两物品交叉 | 城东店和城西店的易拉宝和宣传海报分别摆在哪 | `ITEM_AMBIGUOUS` / 澄清 / 不归内核 | **同左** | ✅ 仍澄清 |
| N2 | 纯指代（量化，无目标） | 城东店和城西店的这两个分别摆在哪 | `MULTIPLE_ENTITIES` / 澄清 | **同左** | ✅ 仍澄清 |
| N3 | 词表外门店 + 纯指代 | 城东店和郊野店的这几个分别摆在哪 | `MULTIPLE_ENTITIES` / 澄清 | **同左** | ✅ 仍澄清 |
| N4 | 补充：未收录资料 | 促销活动台账在哪 | `DOCUMENT_NOT_FOUND` / `no_answer` | **同左** | ✅ 未被 A 修复放大 |

- 三例澄清题的 e2e 断言：`kind=clarification` 且答案**不含任何一条记录取值**（不静默整表作答）。
- 说明：N4 是"资料缺失分支未被误抑制"的对照——A 修复只在**同时点名记录实体且问记录字段**时生效，`促销活动台账在哪` 两个条件都不满足。

## 4. B 类（C02/C05 型）：显式实体 → 命中作答；真无覆盖仍 not_found

| # | 类别 | 自建问句 | 改前（重建版） | 改后（现仓库） | 判定 |
|---|---|---|---|---|---|
| B1 | 正例（首轮 + 显式实体 + 行文回指） | 城东店的易拉宝那个张贴要求是怎么说的 | `ANAPHORA_NEW_CONTENT` / `no_answer` / **0 引用**（检索前收口） | `reason=None` / `answer` / 1 引用 / 命中"前台内侧墙面" | ✅ |
| B2 | 正例 | 城西店的易拉宝那个补给节奏如何安排 | 同上（`ANAPHORA_NEW_CONTENT` / 0 引用） | `answer` / 1 引用 / 命中"电梯口立柱"，无城东店取值 | ✅ |
| B3 | **真无覆盖**（词表内门店+物品，但无该记录） | 城东店的价签卡纸那个张贴要求是怎么说的 | `ANAPHORA_NEW_CONTENT` / `no_answer` / 0 引用 | `no_answer`（`NO_RECORD_FOR_ENTITY`）/ **0 引用 / 0 取值** | ✅ 不编造 |
| B4 | 追问口径不回退（多轮） | ①城东店的易拉宝在哪里？②城东店的易拉宝那个印刷材质呢 | 第 2 轮 `ANAPHORA_NEW_CONTENT` / 0 引用 | **同左（未变）** | ✅ |
| B5 | 首轮纯指代 | 这两个分别摆在哪 | `MISSING_SLOT` / 澄清 | **同左** | ✅ |

- B4 的关键：第 2 轮**带上一轮 state、同一会话**（`turn>1`），仍是"未记录该字段"收口；这说明本轮新增的"首轮放行"没有把追问口径一起放开。
- B3 的 e2e 检查覆盖 6 条记录取值全部**不出现**，且 `citations=[]`。

## 5. 回归（fix-1 / fix-1r1 / safety-fix）：全部仍绿

### 5.1 定向测试（9 文件，独立重跑）

| 文件 | 覆盖 | 结果 |
|---|---|---|
| `tests/rag/test_v3_fix2_record_scope_not_clarified.py` | 本轮 A | 通过 |
| `tests/rag/test_v3_fix2_first_turn_record_answer.py` | 本轮 B | 通过 |
| `tests/rag/test_v3_fix1_multi_target.py` | fix-1/A 多目标枚举 | 通过 |
| `tests/rag/test_v3_fix1_business_date_filter.py` | fix-1/B 业务日过滤 | 通过 |
| `tests/rag/test_v3_fix1r1_anaphora_multi_target.py` | fix-1r1 纯指代 | 通过 |
| `tests/unit/test_v3_fix1_wiring.py` | fix-1 产品接线 | 通过 |
| `tests/unit/test_v3_safety_fix_policy.py` | safety-fix 拒答策略（19 例） | 通过 |
| `tests/integration/test_v3_safety_fix_e2e.py` | safety-fix 跨实体继承 e2e（9 例） | 通过 |
| `tests/observability/test_paths_e2e.py` | 多目标 trace 路径 | 通过 |
| **合计** | | **102 passed / 0 failed / 0 error**，`exit 0` |

复现命令（本包实跑，netguard 回执见 §6）：

```
cd backend && PYTHONPATH=<independent/netguard> NETGUARD_RECEIPT=<...> python -m pytest \
  tests/rag/test_v3_fix2_*.py tests/rag/test_v3_fix1_multi_target.py \
  tests/rag/test_v3_fix1_business_date_filter.py \
  tests/rag/test_v3_fix1r1_anaphora_multi_target.py tests/unit/test_v3_fix1_wiring.py \
  tests/unit/test_v3_safety_fix_policy.py tests/integration/test_v3_safety_fix_e2e.py \
  tests/observability/test_paths_e2e.py -q
```

> 注：本包首次使用"全量 socket 拦截"版本守卫时，18 failed / 9 error —— 是**守卫过宽**（把 TestClient/anyio 的回环也拦了，被测代码根本没跑起来），与产品代码无关。守卫改为"只拦非回环、回环放行并计数"后即 102 passed，回环 233 次、外部 0 次（§6）。这条如实记录，避免把"没测成"当成"测过了"。

### 5.2 自建探针里的回归面（同一份 16 例探针）

| # | 覆盖 | 改前 | 改后 |
|---|---|---|---|
| R1 | fix-1/A 多目标枚举正例（两店单物品） | `MULTI_TARGET_ENUMERATE` / `answer` / 2 引用 | **同左** |
| R2 | fix-1r1 纯指代（"这几个"） | `MULTIPLE_ENTITIES` / 澄清 / 不归内核 | **同左** |
| N2/N3 | 纯指代 / 词表外门店 | 澄清 | **同左** |
| A4 / B4 | safety-fix 合并请求拒答 / 追问收口 | 拒答 / 未记录 | **同左** |
| 业务日过滤 | 由 `test_v3_fix1_business_date_filter.py` 6 例覆盖 | — | 通过 |

**结论：fix-1 / fix-1r1 / safety-fix 的正例与反例在现仓库全部仍绿，未发现回退。**

## 6. 零调用与"diff 只追加"

### 6.1 零调用（只拦非回环）

| 口径 | 值 | 证据 |
|---|---|---|
| 定向 9 文件会话内**外部**出站 | **0** | `independent/netguard-targeted-run.json`（`external_attempts_count=0`） |
| 回环尝试 | 233（TestClient/pytest socketpair，非业务出站） | 同上 |
| 自建探针（改后 / 改前） | 外部出站 0 / 0（探针内 socket 守卫，`outbound_attempts=[]`） | `independent/independent-probe.json`、`independent-probe-prefix.json` |

### 6.2 `fix-2.diff` 只追加（未回退既有改动）

本包不用开发方的重建器，自己写反向应用器（`independent/reconstruct_prefix.py`，按 new-file 坐标精确替换、无 fuzz），把 `evidence/fix-2.diff` 从**现仓库**反演回去，再与**上一轮独立产物** `safety-fix/evidence/fix-sha.json` 的 `after_sha256` 逐字节比对：

| 文件 | 反演后 SHA-256 | 上一轮收尾 SHA-256 | 相等 |
|---|---|---|---|
| `backend/src/mktkb/rag/query.py`（6 hunk） | `fc55db53f2b7a00292b538a3797f6ba456b6d871c95df026065bd5b74feb4549` | `fc55db53…b4549` | ✅ |
| `backend/src/mktkb/rag/answer.py`（1 hunk） | `55778d8f1446aaedc836c194b1ed9c82d8d3a54b89cb14046ac2175981aca63a` | `55778d8f…a63a` | ✅ |

现仓库现值：`query.py = e5028ee35c59acd764ed18353cb83fe39bd0e6d3cfcd4996000794a149fc5317`、`answer.py = d493c7f6d4b31d7b5a160ee2a51659e3c0e3d11d99df4cfb768abd02c7982a4c`（与 `fix-sha.json` 声称一致，本包现算）。

**推论**：diff 是"上一轮收尾 → 现仓库"的**完整**差分，因此既没有回退 safety-fix 的改动，也没有夹带第三个文件。
（过程如实记录：我第一版解析器把 `--- a/...` 文件头误当删除行，导致 query.py 反演 SHA 不符；修正解析后逐字节相等。这是本包工具的问题，不是开发方的问题。）

### 6.3 冻结件与边界

| 边界 | 结果 | 证据 |
|---|---|---|
| C 冻结 12 | **12/12 未变**（现算 SHA vs 上一轮 `preservation-after.json`） | `independent/preservation-check.json` |
| `fixtures/acceptance-h2v3` | **13/13 未变** | 同上 |
| 评测模块 `backend/src/mktkb/evaluation/*.py` | **本包会话内 0 个被改动**（mtime 全部早于本轮开始 15:43） | 同上 |
| 分支 / HEAD | `codex/p2-e2e` / `97b0066726e5…` 未变 | 同上 |
| 暂存 | **0**（`staged_paths=[]`） | 同上 |
| 追踪内修改 | 25 条（均为前几轮既有；本轮 diff 只涉及 `rag/query.py`、`rag/answer.py`） | 同上 + §6.2 |

## 7. 残余（不隐瞒，均不影响"可进入复跑"）

| # | 残余 | 级别 | 说明 |
|---|---|---|---|
| I1 | **真实 5 题能否翻 pass 仍未验证** | 高 | 本包不读题面，只能证明"机制同形 + 同类输入结局按预期改变"，不证明 C20/C22/C30/C02/C05 在真实题面上得 pass。是否翻盘由段 3 的四 run 全量复跑给出。 |
| I2 | 纯指代"它们"在 legacy 面仍整表作答 | 中 | 自建 R3：`城东店和城西店的它们分别摆在哪` → 规划层**未**判多目标、**不**归内核，legacy 侧返回 6 条记录（6 引用）。改前改后**完全一致**，属既有行为（fix-1/A 的 N5 也只断言"不按多目标放行"），**不是本轮回退**；但若真实题面用"它们"这一形态，可能成质量风险。本包不改产品代码，仅记录。 |
| I3 | A 修复的语义边界 | 中 | 只在"本轮点名记录实体 **且** `field_role ∈ RECORD_FIELD_ROLES`"时抑制"资料缺失/歧义"。若某题确实在问"两份资料取哪一份"、又同时带记录实体与记录字段，现在会按记录作答而非澄清。语料内两店/单物品场景是目标形态；其他形态未穷举（与开发报告 R3/R4 同口径）。 |

## 8. 一句话结论

**可进入复跑**：A/B 两类正例在现仓库全部作答、改前全部失败（同一探针、只换 src，5 例翻转、11 例稳定）；三类真歧义与真无覆盖仍保守（澄清 / `not_found` 且 0 引用 0 取值）；fix-1/fix-1r1/safety-fix 的 102 例定向测试与自建回归面全绿；`fix-2.diff` 经独立反演证明只追加、未回退；C 冻结 12 与评测模块未改；零真实调用、暂存为空。

机读汇总：`independent/review-aggregate.json`；探针原始：`independent-probe.json` / `independent-probe-prefix.json` / `probe-compare.json` / `reconstruct-prefix.json` / `preservation-check.json` / `netguard-targeted-run.json`。
