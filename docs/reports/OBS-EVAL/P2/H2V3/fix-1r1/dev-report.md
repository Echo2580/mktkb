# H2 v3 fix-1/R1 纯指代假放行窄修复 · 开发报告

- 角色：v3-fix-1/R1（普通开发；只修 A 的“纯指代假放行”回归，不做验收/经理/保管）。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；暂存 0 项；未 commit / 未 push / 未新建 worktree / 未切分支。
- 本包零真实调用/请求：探针与单测全部进程内离线；netguard 正对照先删代理环境变量，`urllib` 用 `ProxyHandler({})`、`httpx` 用 `trust_env=False`，4/4 被拦；会话内外站尝试 **0**（§5）。
- 结论：**COMPLETE**（N2/N2b 回归已关；fix-1/A 四个正例仍绿；独立验收自带探针 13/13 复跑全绿）。

---

## 1. 现象与根因

独立验收 `fix-1/independent-review.md` N2/N2b：用户已点名门店、但目标用**纯指代**（“这两个/这几个”）时，planner 放行为 `MULTI_TARGET_ENUMERATE`、`_rag_owns_turn=true`，内核按“两店全部物品”作答 4 行；改前（fix-1/A 之前）由 legacy 判“多个门店”澄清。

根因（`backend/src/mktkb/rag/query.py`）：

- fix-1/A 的多目标守卫只复用 `ANAPHORA_WORDS`（“它/这个/那个/该/…”）；
- “这两个/这几个”是“这 + 两/几 + 个”，不是“这个/那个”的子串，守卫未触发；
- `multi_stores=true`、`items=[]`、`field_role=location`、`not anaphora` → 多目标成立 → `enumerate=true` + `reason=MULTI_TARGET_ENUMERATE` → 产品层交给内核 → 整表枚举。
- fix-1 的自测只覆盖了**不带门店**的 bare 形式（`这两个分别放在哪里？` → `MISSING_SLOT`），没覆盖“已点名门店 + 指代目标”。

## 2. 修复点（只追加，未回退任何既有未提交改动）

| 位置 | 改动 |
|---|---|
| `backend/src/mktkb/rag/query.py:90` | 新增量化指代识别：`_QUANTIFIED_ANAPHORA = (这\|那)(两\|几\|俩)(个\|家)`；目标名词/词表实体表 `_QUANTIFIED_ANAPHORA_HEADS`。不含“哪两个”（疑问枚举，不是指代）。 |
| `backend/src/mktkb/rag/query.py:409` | 新增 `_bare_quantified_anaphora()`：只有**未点名目标**的量化指代才为真。两类复指不算：①后置名词（`这两个店/这几个物品`、或紧跟词表实体）；②前置枚举（`海报和易拉宝这两个`、`城东店、城西店这两家`，量化词前只隔标点/空白就是已点名目标）。`…和这两个` 这种用连接词**另起一个目标**的仍算纯指代。 |
| `backend/src/mktkb/rag/query.py:1452` | planner 的 `anaphora` 改为 `quantified_anaphora or ANAPHORA_WORDS`；多目标守卫随之为假。 |
| `backend/src/mktkb/rag/query.py:1813` | 新增窄澄清分支：纯指代 + 已点名门店（或含词表外门店）+ 无显式物品 + 记录字段角色 → `reason=MULTIPLE_ENTITIES`、`clarification`（既有文案 `multiple_entities_text`），不再归内核；既不整表枚举，也不静默只答显式一维。 |
| `backend/src/mktkb/rag/query.py:1152` | 指代残词计算先去掉量化指代短语，避免“两个”被当成新内容。 |
| `backend/src/mktkb/conversations/service.py` | **未改**：`_rag_owns_turn` 既有 `clarification → false` / `reason=MULTI_TARGET_ENUMERATE → true` 口径已足够。 |

**为什么不是“多目标一概拒绝”**：判定仍要求同维度 ≥2、另一维度 ≤1、词表内实体、可回答字段、非政策正文、无资料/产品歧义；2×2 交叉、未知门店/区域、无字段等既有拒绝/澄清面不变。复指限定语（“海报和易拉宝这两个物品”）仍按显式多目标作答（单测锁定）。

修复 diff：`evidence/fix-r1.diff`。`evidence/reconstruct_pre_r1.py` 按行块反向删除本轮追加内容重建改前文件，重建哈希与改动前实测逐字节相同（`query.py` `f73fc735…`、`test_paths_e2e.py` `d357fdc3…`），即本轮**只**改了该 diff 中的块。

## 3. 改前/改后同输入对照（证据 `evidence/planner-before.json` / `planner-after.json` / `before-after-summary.json`）

探针 `evidence/probe_planner_r1.py`：同一批合成问句、同一离线索引；`baseline` 两臂 = fix-1/A 之前的 `query.py`（独立验收反向还原，SHA `5a7ed26b…`）；`before` = 本树 fix-1/A（SHA `f73fc735…`）；`after` = 本次 R1（SHA `82776def…`）。

| 类 | 输入（合成） | baseline（fix-1 之前） | before（fix-1/A） | after（R1） |
|---|---|---|---|---|
| 1 纯指代+已点名门店 | `城东店和城西店的这两个分别放在哪里？` | planner 无原因、不归内核；legacy 澄清 | `MULTI_TARGET_ENUMERATE`、归内核、内核 **4 行** | `MULTIPLE_ENTITIES`、不归内核、内核 **clarification** |
| 1 同上（这几个） | `城东店和城西店的这几个分别放在哪里？` | 同上 | 同上、4 行 | 同上、clarification |
| 1 对照（它们） | `城东店和城西店的它们分别放在哪里？` | 不归内核、legacy 澄清 | 同 baseline | 同 baseline（未变） |
| 2 纯指代+未点名 | `这两个分别放在哪里？` | `MISSING_SLOT` 澄清 | 同 baseline | 同 baseline |
| 3 混合·物品维 | `城东店的宣传海报、易拉宝和这两个分别放在哪里？` | `ITEM_AMBIGUOUS` 澄清 | `MULTI_TARGET_ENUMERATE`、2 行 | `ITEM_AMBIGUOUS` 澄清（= baseline） |
| 3 混合·门店维 | `城东店和城西店的宣传海报和这两个分别放在哪里？` | 不归多目标、归内核、2 行（只答显式物品） | `MULTI_TARGET_ENUMERATE`、2 行 | 不归多目标、归内核、2 行（= baseline；见 §6.2） |
| 4 跨轮指代 | 上轮 `城东店和城西店的宣传海报在哪里？` → 本轮 `这两个分别放在哪里？` | 不归多目标、2 行（延续上轮目标） | 同 baseline | 同 baseline（不重开整表） |
| 5 指代+词表外门店 | `城东店和城南店的这两个分别放在哪里？` | 不归多目标、2 行（只答城东店） | 同 baseline | `MULTIPLE_ENTITIES` 澄清 |
| 5 对照（无指代） | `城东店和城南店的宣传海报在哪里？` | 1 行、不含城南店 | 同 baseline | 同 baseline（既有口径未改） |
| A 正例 | 两店一物品 / 一店两物品 / 两店电话 / 两店一物品+分别 | 澄清或旧路由 | `MULTI_TARGET_ENUMERATE`、2 行 | **同 before**（`MULTI_TARGET_ENUMERATE`、2 行） |

独立验收自带探针 `fix-1/independent/probe_A_multi_target.py` 复用（只改输出文件名，附 `evidence/probe_A_multi_target_reuse.py` / `independent-probe-reuse-after.json`）：**failures=[]，13/13 全绿**；其中 N2/N2b 由 FAIL 变为 `MULTIPLE_ENTITIES` + `clarification` + `owns=false`，P1–P4 仍为 `MULTI_TARGET_ENUMERATE` + `answer`（2 行）。`N3/N5` 口径未变。

## 4. 新增/补充测试

| 文件 | 覆盖 |
|---|---|
| `backend/tests/rag/test_v3_fix1r1_anaphora_multi_target.py`（新增，16 条） | 纯指代+已点名门店（这两个/这几个）→ 澄清；bare → 既有 `MISSING_SLOT`；`它们` 不进多目标；混合物品维 → `ITEM_AMBIGUOUS`；混合门店维 → 不冒充多目标、不扩成整表；跨轮 → 不重枚举整表；指代+词表外门店 → 澄清；3 类复指限定语 → 仍 `MULTI_TARGET_ENUMERATE`；fix-1/A 三正例 → 仍放行。 |
| `backend/tests/observability/test_paths_e2e.py:390`（追加 1 条） | 产品 HTTP 全链路：`滨江店和城东店的这两个分别放在哪里？` → `kind=clarification`，`trace.path=legacy`，`outcome=clarification`，Span 恰为 `intent_parse/commit`（不检索、不调模型）。既有 A 正例 `test_multi_target_single_turn_answers_instead_of_clarifying` 未改。 |

## 5. 验证与零调用

| 运行 | collect | passed | failed | exit |
|---|---:|---:|---:|---:|
| 定向验收（新文件 + fix-1 多目标 + wiring + observability 相关），netguard 下 | 34 | 34 | 0 | 0 |
| `tests/unit tests/rag` 全量，netguard 下 | 756 | 754 | 2（既有漂移） | 1 |
| `tests/integration/test_p1_t105_anaphora_field.py` + `tests/observability/test_paths_e2e.py` | 48 | 48 | 0 | 0 |
| `tests/integration/test_p1_t102_state_inheritance.py` + `test_s2b_intent_semantics.py` + `test_p1_t101_vocab_context.py` | 14 | 14 | 0 | 0 |
| `tests/integration/test_p2_product_e2e.py` | 8 | 8 | 0 | 0 |

- 2 条既有漂移与 fix-1 基线/独立验收一致：`test_s2h_r3_official_profile…`（profile 期望值）与 `test_s4_stage_limit…`（预算 40 vs 20），与本包改动无关；日志 `evidence/pytest-r1-netguard-unit-rag.log`。
- 零调用（`evidence/netguard-targeted-run.json`、`netguard-unit-rag-run.json`、`planner-before/after.json`）：代理环境变量 `ALL_PROXY/HTTP_PROXY/HTTPS_PROXY/NO_PROXY/NODE_USE_ENV_PROXY` 已删；正对照 DNS/直连/`urllib`（`ProxyHandler({})`）/`httpx`（`trust_env=False`）**4/4 blocked**；`external_attempts_during_session=0`（两次 pytest + 两次探针均为 0）；回环仅 anyio/pytest 本机 socketpair，已计数放行。

## 6. 残余（不隐瞒）

1. **“它们”的 planner 不澄清**：`城东店和城西店的它们分别放在哪里？` 仍是无原因、不归内核，由 legacy 产出“多个门店”澄清（与 fix-1 之前一致，独立验收当时判 PASS）。本包只关闭“这两个/这几个”这一类回归，没有扩大 `ANAPHORA_WORDS` 以改 `它们` 的既有路径。
2. **混合·门店维仍只答显式那一维**：`城东店和城西店的宣传海报和这两个分别放在哪里？` 改后与 baseline 相同——planner 不再冒充多目标，但仍走既有 `enumerate && item_filter` 路由，只答显式“宣传海报”2 行，“这两个”不被扩展也不被追问。这是 fix-1 之前就存在的路由，不是 A 引入；若要一并改为澄清，需要另开任务定口径。
3. **跨轮指代按上下文延续**：本轮“这两个”不重新枚举整表，而是延续上一轮已点名的“宣传海报”2 行（与 baseline 相同）。若要求“跨轮纯指代也必须先澄清”，属更严的产品口径变更，未在本包擅自扩大。
4. **复指识别是有限形态**：覆盖 `这两个/这几个/这两家/那几家 + 目标名词或前枚举`；`这两个海报`（“宣传海报”只说了“海报”）、`这些/那些` 等其它量化形式不在本包正则内，仍按既有路径处理。
5. **指代+词表外门店改为澄清**（`城东店和城南店的这两个…`）：会先澄清“多个对象”，不再静默只答城东店；纯显式枚举的 `城东店和城南店的宣传海报在哪里？`（无指代）口径未改（仍只答已知门店，独立验收当时判 PASS）。
6. **未跑真实 H2**：本包不读真实题面/答案、不解密、不跑 run；结论只覆盖合成问句与产品全链路离线测试。

## 7. 保全与 Git 状态

- `evidence/preservation-after.json`（快照，只哈希不读内容）与 `preservation-compare.json`（对照独立验收 `00-snapshot-end.json`）：
  - HEAD/branch 相同，`staged=[]`；
  - 22 条 tracked modified 中**只有** `backend/src/mktkb/rag/query.py` 与 `backend/tests/observability/test_paths_e2e.py` 变化（前者 R1、后者追加 1 条 e2e）；
  - C 冻结 12、`p2_holdout_scenarios.py`/`p2_holdout_scenarios_v3.py`、预算/账本/GO、v3 冻结 32（仍 30/32，缺件与改前同一组 `freeze_a_manager_acceptance`/`freeze_a_review_aggregate`）、外部 v2/v3 密文与语料、`fixtures/acceptance-h2v3` 全树：**哈希全部一致**；
  - 未 stage/commit/push；新增文件均为未跟踪的测试与证据。
- 未修改：`conversations/service.py`、`p2_holdout_scenarios.py`、两份 scenarios、账本/GO/预算、v2/v3 密文与语料、C 冻结 12。

## 8. 复现命令（离线）

```bash
cd backend
# 定向验收（零调用守卫 + 正对照）
NETGUARD_OUT=<evidence>/netguard-targeted-run.json \
PYTHONPATH=<evidence> \
../.venv/Scripts/python -m pytest -q -p netguard_plugin \
  tests/rag/test_v3_fix1r1_anaphora_multi_target.py \
  tests/rag/test_v3_fix1_multi_target.py \
  tests/unit/test_v3_fix1_wiring.py tests/observability/test_paths_e2e.py \
  -k "anaphora or multi_target or multi_entity or resumptive or fix1 or bare or cross_turn or unknown_store"

# 改前/改后探针（同一脚本，输出不同文件）
../.venv/Scripts/python <evidence>/probe_planner_r1.py <evidence>/planner-after.json
```

`before` 文件在本次改动前用同一脚本生成；`after` 文件在改动后生成。两者只差当前代码哈希。
