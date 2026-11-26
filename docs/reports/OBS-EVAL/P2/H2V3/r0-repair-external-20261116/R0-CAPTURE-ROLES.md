# R0-CAPTURE-ROLES：`plan_observed` 补采枚举级字段角色（结论 = 已完成；冻结件 0 改动）

日期：2026-11-16（Asia/Shanghai）。执行者：外部 AI 修复助手（capture-field）。授权：主人已**明确批准**本采集增量（含最多两轮后续真实 r0）。
> 边界：未读私有材料（`D:\mktkb-p2-h2v3-*`、`.env`、`*.key`、P1-HOLDOUT）；未发真实请求（未运行 `tools/p2_h2_v3_controlled_execute.py`
> 任何子命令）；未改冻结件/账本/预算/旧证据/case-plan；未 `git add/commit/stash/reset/checkout/clean`。

## 1. 结论
1. `plan_observed` 新增两个**可选**键：`field_role`（`str | None`）、`field_roles`（`list[str]`，原序、不去重）；只含枚举级角色码，不含正文/字段中文名/实体/值。
2. 旧 envelope 无这两个键时：清洗结果与加键前**逐键逐值相同**（可选键缺省不合成任何键），所有校验路径行为不变。
3. 所有消费方经共享 `EVENT_FIELDS` 自动生效，**无第二份白名单**；冻结件 0 改动（`p2_hard_evidence.py` sha256 未变）。
4. **不升** `mktkb.eval-capture` 版本（理由见 §3.3）。
5. 运行前置：`code_digest()` 覆盖 `backend/src/mktkb/**.py` ⇒ 本次两文件改动改变 `code_version`，下一轮真实 r0 必须**重出 SAFE plan/GO**（旧 plan 会被 `code_version`/`run_binding` 拒）；本单未做计划/GO 操作。

## 2. 改动清单（行号为改动后实测）
| 文件 | 位置 | 改动 |
|---|---|---|
| `backend/src/mktkb/observability/evaluation_capture.py` | :59 | 新增 `_OPT_LIST_STR` 类型码 |
| 同上 | :154-157 | `plan_observed` 加 `field_role`(`_OPT_STR`, `required=False`)、`field_roles`(`_OPT_LIST_STR`, `required=False`) |
| 同上 | :287-294 | 新增 `_clean_optional_list_text`（显式 None → `[]`；缺键不进入本函数） |
| 同上 | :447-450 | `_clean_value` 分派 `opt_list_str` |
| 同上 | :476-481 | `clean_event_payload`：可选键缺省**不合成键**（旧 payload 清洗结果不变） |
| `backend/src/mktkb/conversations/service.py` | :2394-2397, :2413-2414 | 发射点 `getattr` 取 `field_role`/`field_roles`（缺失 → `None`/`[]`，不 AttributeError），只传角色码 |
| `backend/tests/evaluation/test_r0_9_plan_observed_roles.py` | 新增 354 行 / 20 tests | 红→绿、可选键、独立闭包、旧 envelope 抽样 |

`service.py` 的 `plan_observed` 发射块本身是工作树既有未提交改动（r0 前几轮），本单增量仅上述 2 行取值 + 2 行传参，该块其余字段一字未动。
采集层只做**字符串/列表类型**校验、不复制 `rag` 角色枚举（`observability` 不反向依赖产品词表）；值域闭合由产品计划器保证（`QueryPlan.field_role(s)` 直接来自 `_match_fields` 的枚举码）。

## 3. 兼容性论证
### 3.1 旧 envelope 逐字不变
- 新键 `required=False`：缺键走新增分支 `continue`，**不合成** `None`/`[]`；加键前没有任何可选字段，该分支弹片半径 = 0。`test_plan_observed_without_role_keys_is_valid_and_cleaned_identically` 断言 `clean(payload) == payload`。
- 旧证据事件不含新键 ⇒ `set(payload) - set(spec)` 结果与改前一字不差；旧 envelope 未被重写、未被重新封存。
### 3.2 新证据在所有消费方被接受（逐一核对）
- 共享白名单（import 而非抄写）：`p2_hard_evidence.py:36,1467-1473,2691-2695,2769-2772`；`p2_empty_scope_proof.py:37,765-775`；`p2_evidence_io.py:24,772-777`（`:757` 是 capture schema 字面量）。
- 无 payload 白名单：`p2_evidence_capture.py`（只读 `plan.path`，:778-789/:1025-1036）；`p2_evidence_snapshot_v03.py`（:1882-1980 只取 path/mode/as_of/include_future/enumerate/clarification 构 `plan` 块）；`p2_evidence_axes_adapter_v2.py`（只校验 snapshot，:954 仅比较 `as_of_source` 枚举）；`p2_evidence_rescore*.py`（只读 `as_of`）。
- 结论：本树内不存在“旧版本校验器”的独立实现；上一修订版只会读旧证据（envelope 绑定 `code_version`），新证据由新代码读 ⇒ 不存在“新证据在旧校验器下失败”的跨版本读取场景。
### 3.3 为什么**不**升 capture schema 版本
- `p2_evidence_io.py:757` 与 docs 下多处探针把 `"mktkb.eval-capture/v0.1"` 当**字面量精确校验**；升版会让**新**证据在冻结 IO 处报 `capture_schema_version_invalid`，需改 IO + 全部旧读端，收益为零、风险更大。
- 加键是可选键的**加法扩展**：未知键仍 fail-closed（`unknown_event_fields`，见类型反例与精确键集断言），即便存在旧读端也只会拒收、不会误读。未改 `MATCHER_VERSION`、阈值、题集、标签。

## 4. 冻结件
- `p2_hard_evidence.py`：**不需要改**（白名单/清洗函数均为 import），实测 sha256 = `7956b2b7159d6bc740a7ecff156605c85ad75c00ef57c45f99f282f19e14ba19` = `FROZEN_SHA`，`test_frozen_module_sha_is_expected` 通过。
- `p2_evidence_capture.py`、`p2_evidence_rescore*.py`：无事件字段白名单 ⇒ **不需要改**。
- `docs/evaluation/*`：**未改**。`p2-hard-evidence-capture-v0_1.md` 只列事件种类与 R1 增补、不逐字段列表 ⇒ 无文档-代码冲突；若主人要把两键写入契约，需批准后加 1-2 行（本单“未改、需要批准”）。
- 若将来出现**冻结副本**（另一份硬编码 `plan_observed` 字段表），必须同步 + 版本开关；本树 grep `EVENT_FIELDS` / `state_last_kind` 未发现第二份。

## 5. 测试证据
命令：`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；`.\.venv\Scripts\python.exe -B -m pytest … -q -p no:cacheprovider --basetemp backend\.pytest-tmp\capfield*`。
- **红**：以本次 5 处编辑的**反向替换**重建“加键前”源码（自检正向还原 == 当前文件，字节等价）后进程内注入 ⇒ 新文件 **7 failed / 13 passed**（schema 缺键、清洗拒收、两处发射点、两处闭包 `(False,'unknown_usage_field')`）。
- **绿**：新文件 **20 passed**。
- **回归**：`observability` + `test_p2_empty_scope_proof` + `test_r0_repair_refusal_compat` + `test_r0_repair_c16_empty_scope` + `test_r0_repair_v05_projection_mirror` + `unit/test_conversations` ⇒ **651 passed / 1 failed**。
  唯一失败 = 基线**改前即存在**的 `test_paths_e2e.py::test_legacy_parse_early_not_found_is_reason_aware[滨江店宣传海报的负责人是谁？]`（`trace.path` 期望 `legacy` 实得 `rag`，属工作树其它在途改动）；改前基线 631 passed / 1 failed，改后 +20 全绿，零回归。
- 旧 envelope 抽样（默认 compat 与 v0.5）：`empty_use_scope_ok` 逐值不变；拒绝样本仍 `model_events_missing` / `empty_set_not_proven`（`test_old_envelope_without_role_keys_is_value_identical`）。

## 6. 未做 / 留给下一轮
- `targets`（`R0-ROLE-MAP.md` §7 提到的第三项）**未采**：本单只批准 `field_role` / `field_roles`。
- 未重出 plan/GO、未发真实请求、未运行受控执行器；红证据用的反向补丁 shim 为临时进程内插件（已删除，不入库）。
