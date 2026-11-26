# C1-P3 全新独立验收报告（运行期身份快照采集契约 v0.3）

- 角色：C1-P3 **全新独立验收**（非开发、非经理）；不参与实现、不代签 GO、不改开发文件。
- 日期：2026-11-14；分支 `codex/p2-e2e`；HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；暂存区 **0**；commit **0**。
- 被验收对象：`docs/evaluation/p2-hard-evidence-capture-v0_3.md`、`backend/src/mktkb/evaluation/p2_evidence_snapshot_v03.py`、`backend/tests/evaluation/test_p2_evidence_snapshot_v03.py`、`docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p3/**`。
- 独立方法：**不采信开发自报数字**，全部用本目录 `independent/` 下自建探针重算（`probe_01..08b`），输出在 `independent/out/`。测试执行用 `-p no:cacheprovider`、仓外 `--basetemp`、`PYTHONDONTWRITEBYTECODE=1`，未在仓内留下缓存/字节码。

## 0. 结论

> **`PASS_WITH_DISAGREEMENTS`**
>
> 任务书 §5 的三条硬要求（版本化契约 / 合成+Mock 断言落盘读回 / 缺失 fail-closed 固定码）**成立**；
> fail-closed 在 53 个自建反例上**零偏离**，49/49 码族可达性已逐条查清；冻结/保全/零调用**全部成立**。
> 但契约层留下 **6 个可被消费侧误用的口子**，其中 **class C 空集口径（M-C1P2-01）** 与
> **entity 键空间错位（M-C1P1-01 的 P4 消化）** 是实质分歧，必须在 P4 之前处理。
> 不得据此声称：P3 质量通过、T207 通过、C1-2 授权。

## 1. 逐项结果

| # | 必测项 | 结果 | 关键实测 |
|---|---|---|---|
| 1 | 契约完整性（167 字段 / 49 码族 / 4 个防御码） | **PASS** | 机器重生成字段表 **167/167**，与文档 §4 **逐行相同**（路径/类型/必填/可空/缺失码 0 差异）；必填 167、可空 35；码表 **49/49** 与 §5 逐项相同、无重复；公开摘要 25 键；使用层 9 / 候选层 3。**4 个防御码已查清**（见 §3）。 |
| 2 | fail-closed 是否真严格（自建反例） | **PASS** | **53 个自建反例 + 6 个防御实验**，覆盖缺字段/类型/null/枚举/未知键/跨 run 读+写/跨回合/未声明运行期 id/凭证键/明文值/明文文件/摘要与来源证据/baseline 冒充/空集自相矛盾/实体可匹配性伪造/公开边界/文档级实体/索引冲突/来源版本/读回路径；**全部命中预期精确码（族+路径），0 个 ACCEPTED，0 个码族未被触及（49/49）**。 |
| 3 | Mock 全链独立重跑 | **PASS** | 自造 3 份文档（id 表头 xlsx / 无 id 表头 xlsx / docx）+ 合成租户 + MockChatBackend，3 回合；加密落盘（仓外）→ 读回；**479 个叶值逐叶相等**，59 项检查全过；`record_code=W01`（doc S01/sheet/row 2）、`as_of=2026-09-01`（`plan_observed`）、空使用集 9+3 层均在**磁盘读回对象**上断言；密文不含题面/文档名/用户标识；公开摘要 25 键且不含 id/日期/hash。 |
| 4 | 不越权采集 | **PASS（有残余）** | 契约 §1/§8 明确禁采密码 hash/session token/HTTP 认证头/运行期 DB row id；实现有拒绝路径：`password_hash`/`session_token`/`authorization`/`db_row_id`/`unit_id`/Bearer 值 **6/6 全部固定拒绝**。残余：值级检测是形态启发式（R-07）。 |
| 5 | 冻结与保全 | **PASS** | C 冻结 **12/12** 逐字节不变；15 tracked modified **路径与哈希 15/15 不变**；外来 untracked 基线 **2086 文件 0 改动 / 0 缺失**；暂存 0；HEAD/分支/commit 数(172) 不变；Q1a-1 保护件 **38/38**、repo_files **28/28**（含合同 v1、旧卡/回执、scenarios、受控执行脚本）不变；合同 v2 `b98f9f4a…` 与 P1 接收值一致；新增文件全部落在 Q1a 修复树/C1-1 交付物/本单任务书内，**0 个越界新增**。 |
| 6 | 零调用（正/负对照） | **PASS** | 自建守卫（socket/connect_ex/create_connection/getaddrinfo/http.client/httpx 传输层）：干净段 **external=0**；**正向控制 4/4 故意出站全部被拦并记账**（TCP/DNS/http.client/httpx）；**负向控制：不清账 `assert_clean()` 必须报错，已报错**；清账后通过。adapter 自测 `outbound_attempts=0`。 |
| 7 | 测试质量 | **PASS** | 独立执行 **26 passed / 26 collected**，0 skip、0 xfail、0 恒真断言、0 monkeypatch 被测模块；**132 条 assert**，19 项断言钉到“固定码:路径”；开发测试引用 **45/49** 码族（与自报一致）。残余：无任何断言强制 49 码覆盖（R-10）。 |

## 2. 两条红线在采集契约层的口子（重点）

### 2.1 `M-C1P1-01`（document 级目标不得判 violation）

**红线本身未被越过**：段落级/文本级行全部 `entity_matchable=false`；显式 document 实体得到
`entity_identity_document_level` + `entity_matchable=false`；采集层没有 verdict 字段。
**但留下两个口子：**

1. **指标覆盖不足（R-03）**：`record_identity_summary.entity_document_level` / 公开摘要
   `entity_document_level_count` 只数 `entity_type=="document"`。合成变体里 8 行中 **4 行是文档粒度**
   （`record_level=false`、`entity_type=null`、`entity_code=entity_identity_absent`，
   全部来自 docx 段落），该计数却是 **0**；`not_record_level_count=4`。P4 若把
   `entity_document_level_count` 当“文档级护栏”会得到假安全感。
2. **运行期 id 以“值”的形式越界（R-02）**：§8 声称“运行期 id 只允许出现在 5 类已声明载体”，
   但实现只检查**键名**。无 id 表头的表格行 `entity_key` 实际是
   `item|城北店|折叠凳|doc:<uuid>|unit:<uuid>`，显式文档级行的 `entity_key` 是 `document|<uuid>`，
   **均通过校验**。P4 若按 §7.2(3) 用 `entity_key` 匹配，就把运行期 document/unit uuid 带进了判定。

**附加（跨包）R-04**：合同 v2 R-ENT-1 用 `chunking._entity` 生成**名称型**键
（实测 `item|城北店|折叠桌`），运行期在有 id 表头时生成**id 型**键
（公开 D01 实测 `item|id:p01`/`item|id:p02`；我的合成表 `item|id:w01`），
无 id 表头时是含 uuid 的复合键（**随 run 变化**）。**三种键空间互不相等** → §7.2(3) 的
“(entity_type, entity_key, entity_filters) 等式匹配”**不可直接执行**：
要么系统性 no-match（cross_entity 继续大面积 unknown），要么被误判。
可用的可比字段是 `entity_filters` 的角色键（store/item），但目标侧用 `identifier`、
运行期用 `item_id`，仍需归一。这不是 P3 的采集错误，但 P3 契约的措辞会把 P4 引向错误实现。

### 2.2 `M-C1P2-01`（class C 保持 unknown）

**实证**：3 个合成回合均未出现 class C（`retrieval_observed` 都 observed）；
但我构造的 class C 载荷 —— 9 个使用层全 `observed=true`、计数全 0，
`retrieval_observed.observed=false`、`candidates=[]`、`code=empty_use_input_complete_empty`、
`empty_set_candidate=true` —— **读回校验 ACCEPTED**。
契约 §7.1 把“空集充分条件”直接写成 `all_use_layers_observed + 9 层计数全 0`，
**没有要求 retrieval marker**；这正是 M-C1P2-01 明令禁止的“class C 翻 proven”口径。
消费侧若照 §7.1 实现，会在 class C 形状上给出“空集”，与经理红线冲突。

**反向事实（R-11）**：builder 侧 `empty_set_candidate=true` 实际**不可达** ——
9 层全 observed 要求 `entity_inheritance` 事件存在，而该事件必带非空 `source_unit_id`
（否则 `malformed`），一旦存在计数就 ≥1；实测 2 种合成形状：
空串 → `empty_use_input_malformed_event`；删除事件 → 证据结构校验拒绝。
3 个真实合成回合全部 `all_use_layers_observed=false`、`empty_set_candidate=false`。
因此：**builder 产不出空集，validator 却接受手写的空集 class C 载荷**。

## 3. 四个“未构造反例”的防御码：可达性裁决

| 码 | 裁决 | 证据 |
|---|---|---|
| `snapshot_io_failed` | **可达，只是没测**（测试缺口，不是死码） | 用文件占位 `run` 目录，`mkpath` 真实抛 `OSError` → 精确命中 `snapshot_io_failed`。 |
| `snapshot_readback_mismatch` | **正常路径不可达，故障注入可触发**（真防御） | 替换读回函数返回被篡改对象 → 写后逐字节比对命中。守卫逻辑正确。 |
| `snapshot_run_binding_absent` | **被冻结前置校验遮蔽**（正常不可达；注入后可触发） | 真实调用先命中 `snapshot_source_evidence_invalid`（冻结 live 必填 run_binding）；旁路冻结校验后命中本码。 |
| `snapshot_run_binding_unexpected` | **同上** | 真实调用先命中 `snapshot_source_evidence_invalid`（`run_binding_not_allowed`）；旁路后命中本码。 |

结论：开发“4 个均为防御路径”的表述 **3 对 1 错**（`io_failed` 是可达但未测）。
文档 §5 只对后两个写了“（防御；…）”注记，`io_failed`/`readback_mismatch` 无注记 → **R-09（low）**。

## 4. 其它契约层口子（均已实测 ACCEPTED）

| 口子 | 实测 | 影响 |
|---|---|---|
| `record_code != record_key` | 把 `record_code` 改成 `W99`（`record_key=W01`）、重算摘要后**通过** | 契约 §5.1 说 `record_code := record_key`，但读回侧只查“非空”不查相等；P4 直接信任 `record_code` 有被生产端 bug 误导的风险（R-05）。 |
| `entity_filters` 嵌套运行期 id **键** | `entity_filters.document_id=…` **通过** | 与 §8“任何位置出现一律拒绝”矛盾；开放 map 的键不走 `RUNTIME_ID_KEYS` 检查（R-06）。 |
| 中性键承载凭证值 | `x-auth-header: sid=deadbeefcafe` **通过**；32-hex token 作 `user_ref` **通过** | 契约只承诺“形似 Bearer/JWT/Fernet”检测；原始会话 token/自定义认证头值不在形态表内（R-07）。 |
| `declared_baseline == as_of` 且 flag=false | **通过** | “baseline 不冒充实际值”只靠自声明布尔，读回侧无法重算（R-08）。 |

## 5. 残余 R 码

| id | 级别 | 内容 | 归属 |
|---|---|---|---|
| R-01 | **medium** | 契约 §7.1 把“9 层 observed + 计数 0”直接称为空集充分条件，未要求 retrieval marker；读回侧接受 class C 载荷的 `empty_set_candidate=true`。与 M-C1P2-01 冲突。 | 契约文本 + 校验器 |
| R-02 | **medium** | §8 的运行期 id 白名单只查键名不查值：`entity_key` 可携带 `doc:<uuid>`/`unit:<uuid>`/`document|<uuid>` 且通过。 | 实现 |
| R-03 | **medium** | `entity_document_level` 只数 `entity_type=document`；文本/段落粒度（`record_level=false` + 实体 absent）计 0（实测 4 行文档粒度、计数 0）。M-C1P1-01 的公开护栏指标失真。 | 实现 + 公开摘要 |
| R-04 | **medium** | 目标侧名称型 `entity_key`（`item|门店|物品`）与运行期 id 型（`item|id:p01`，公开 D01 实测）/含 uuid 复合键不同构；§7.2(3) 等式匹配不可执行。 | 跨包（P1/P4） |
| R-05 | **medium** | 读回侧不强制 `record_code == record_key`；篡改后仍通过。 | 实现 |
| R-06 | low | `entity_filters` 的键名不经过运行期 id 检查，与 §8 矛盾。 | 实现 |
| R-07 | low | 凭证/Session 值检测为形态启发式；中性键 + 原始 token 值可通过。 | 实现（已文档化为“形似”检测） |
| R-08 | low | `baseline_used_as_effective` 仅布尔自声明；`declared_baseline == as_of` 可通过。 | 实现 |
| R-09 | low | `snapshot_io_failed` 可达但开发未测；§5 对 4 个防御码只有 2 个注记。 | 测试/文档 |
| R-10 | low | 26 项测试无 skip/xfail/恒真且断言到字段级，但**无断言强制 49 码覆盖**（45/49 仅在 `OBSERVED_CODES` 里记录）。 | 测试 |
| R-11 | low | builder 侧 `empty_set_candidate=true` 不可达（`entity_inheritance` 必带非空 unit）；“空使用集证明输入”只能声明分层，不能产出空集结论。 | 实现 |

## 6. 给 P4 的硬约束（建议经理并入 P4 任务单）

1. **不得**把 `empty_set_candidate` / §7.1 的“充分条件”当空集证明；class C（无 retrieval marker）一律保留 `unknown`
   （落实 M-C1P2-01）。若要采用，必须改为要求 `retrieval_observed.observed=true` 且 `count=0/refs=[]`。
2. **不得**用 `entity_key` 等式匹配 v2 targets；先定义归一规则，或改用 `entity_filters` 角色键匹配（R-04）。
3. **不得**用 `entity_document_level_count` 代替“本回合是否文档粒度”；P4 必须同时看
   `record_level` / `entity_type` / `entity_code`（R-03）。
4. **不得**用 `entity_type=document` / `entity_matchable=false` 行判 violation（M-C1P1-01 原文）。
5. 若 P4 依赖 `record_code`，必须先确认 `record_code == record_key` 或自行复算（R-05）。

## 7. 保全与边界声明

- 本验收**只读**被验收文件与冻结件；未改任何开发文件/冻结件/合同/旧卡/账本/GO；未 stage/commit/push；未新建 worktree/切分支。
- 只使用**合成数据 + 公共 fixture**（`fixtures/acceptance/normal/D01…xlsx`、`D04…docx`），
  未读真实 H2 题面/标签/答案/私有密文/key/`.env`/保管会话；未打开任何仓外私有路径。
- 仓外账本/预算/GO/30 题/标签**未触碰**：我只能声明“本会话未打开”，不能声明其字节未变（不在可读范围）。
- 零真实调用：adapter `outbound_attempts=0`；自建守卫 external=0；正/负对照见 `out/05-zero-call.json`。
  环境注记：本机存在 `HTTP(S)_PROXY=127.0.0.1:7897`，守卫放行 loopback，故正对照显式 `trust_env=False`
  并在 httpx 传输层同时拦截，确保不经代理外联。

## 8. 证据索引（`c1-1/p3/independent/`）

| 文件 | 内容 |
|---|---|
| `probe_01_contract.py` / `out/01-contract.json` | 字段表/码表/文档逐行一致性 |
| `probe_02_mock_chain.py` / `out/02-mock-chain.json` / `out/02-capture-cache.json` | 合成全链、逐叶相等、三组关键字段 |
| `probe_03_failclosed.py` / `out/03-failclosed.json` | 53 反例 + 6 防御实验（精确码） |
| `probe_04_redlines.py` / `out/04-redlines.json` | 两条红线 + 6 个口子 + 采集拒绝路径 |
| `probe_05_zerocall.py` / `out/05-zero-call.json` | 零调用正/负对照 |
| `probe_06_preservation.py` / `out/06-preservation.json` | 冻结/保全（独立基线） |
| `probe_07_tests.py` / `out/07-test-quality.json` | 测试执行与静态质量 |
| `probe_08_entity_key_space.py` / `out/08-entity-key-space.json` | 目标侧 vs 运行期 entity 键空间 |
| `probe_08b_public_fixture.py` / `out/08b-public-fixture-entity-shape.json` | 公开 D01 运行期键复核 |
| `netguard_independent.py` | 自建零出站守卫 |
