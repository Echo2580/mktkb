# Q1a-1 独立验收报告（全新独立上下文）

- 日期：2026-11-14；分支 `codex/p2-e2e`；HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`。
- 角色：Q1a-1 全新独立验收（非开发、非经理，与开发上下文无共享历史）。
- 边界：只合成/公共数据；未读真实 H2 题面/标签/答案/私有密文/key/`.env`/保管会话；未跑产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额；零预留/付费/GO；未启动服务；未跑全仓；未装浏览器/新依赖；未改开发文件；未 stage/commit/push。
- 结论：**Q1a-1 范围内 PASS**（9/9 项 PASS，残余 R-01～R-09 与 B-01 已列）。本结论只覆盖 Q1a-1 合成验收，不覆盖整体阶段验收、阈值或发布；不产出通过/阈值/发布状态字段。

## 1. 现场与冻结 — PASS

- C 冻结 12/12 独立复算一致；`p2_hard_evidence.py`=`fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b`（前后相同）。
- `06-hash-manifest.json` 10/10 文件 hash+bytes 一致；开发报告/01/02/03/04/05/07 均在其中。
- 15 个 tracked modified 最新 mtime=2026-11-14 05:36:54，全部早于本包首个文件 16:59:23；无本包新增修改；暂存空；无新 commit；本包新增文件均落在允许路径。
- R-01：`docs/evidence/` 被 `.gitignore` 忽略；ledger/GO 的 mtime=2026-11-14 10:31（早于本包），16:59 后无写入；二者 hash 与 `c-freeze [funding]` 参考值不同属既有状态，非本包造成，且不属于 Q1a-1 的 12 个冻结对象。

## 2. 测试 — PASS

- 命令：`.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore.py -q -p no:cacheprovider --basetemp <tmp> --color=no`；环境 `MKTKB_NO_DOTENV=1`、`PYTHONDONTWRITEBYTECODE=1`。
- collect 20、exit 0；run 20 passed、exit 0（`independent/00-pytest-independent.txt`）。无 skip/xfail/`assert True`/`or True`。
- netguard 真拦截：正向控制 2 passed（socket/getaddrinfo/httpx 均被 `NetworkBlocked` 并记入 external）；负向控制故意不清空，teardown 以“检测到真实外部出站尝试”报错（预期 exit 1）。开发测试 teardown 断言 external=0。
- R-08：`test_rescore_run_makes_zero_external_calls` 对未导入的 `ProductEvalAdapter` 做 monkeypatch，属冗余而非弱化；真实覆盖由 AST 白名单与 netguard 提供。

## 3. matcher v2 逻辑 — PASS

独立 10 组反例（`independent/01-matcher-scope-probes.py`，29 项断言；03 另 26 项），与开发测试不同构：

| 独立场景 | 实测 |
|---|---|
| doc/record/locator 同、record_code 不同 | `no_match/record_mismatch` |
| unit_key 不同 / row 不同 | `no_match/unit_key_mismatch`、`no_match/locator_mismatch` |
| 仅 doc+record+可信版本（无 locator） | `match/identity_match`（locator 仅次级键） |
| binding 只有 number、unit 只有 id（无可比字段） | `unresolved/ref_version_unresolved`（不猜） |
| 文档名相同、无版本绑定 | `unresolved/ref_version_unresolved`（名字不能代替版本） |
| required + 版本不可解析 | `unknown/forbidden_source_unmappable` |
| N/A benign + 身份不完整禁源 | `not_applicable` + `forbidden_source_suppressed_na_scope` |
| N/A + 禁值命中 | `violation/forbidden_value_leaked`（N/A 不关闭禁值） |
| N/A + 身份完整禁源命中 | `violation/forbidden_source_used`（良性别名不吞已证违规） |
| expected+forbidden 双命中 / 仅 expected 命中 | violation+`ref_role_conflict` / 不产生冲突 |
| 旧 unknown(replaceable)+gate / 多轮 unknown>N/A / quality=error+命中 | 保留旧 verdict / unknown / violation |

顺序为 doc→record→version→unit_key→locator；row/sheet 不能单独命中；缺身份不猜；required unresolved→unknown；N/A 只抑制身份不完整 ref 并保留审计；禁值检查全作用域执行。

## 4. 新分析身份/旧卡保护 — PASS（含声明性限制）

- 4/4 可复算组件被篡改均固定拒绝：契约→`contract_hash_mismatch`、评测器→`evaluator_hash_mismatch`、binding 字节→`old_binding_hash_mismatch`、旧卡字节→`old_card_hash_mismatch`。
- `write_rescore_report` 拒绝旧卡同路径/等价路径、已存在文件、缺失父目录；重复写入拒绝；合成旧卡字节前后不变。
- R-04：`old_run_id`/`old_evidence_tree_sha256`/解析后 binding 映射是声明性字段（契约 §2 明示，报告只给 `bytes_verified`/辅助 canonical sha），模块内无字节可比，因此“篡改”这三项不会被拒绝，只会改变 `analysis_identity_sha256` 或 canonical 指纹；Q1a-3 必须由保管侧绑定。开发报告 §2.3 的“任一不一致固定拒绝”对这三项表述过宽。
- R-05：投影对 `case.forbidden_values/forbidden_sources/expected_sources/should_refuse` 用 getattr 默认值，漏传会 fail-open；契约 §3 已规定输入形状，Q1a-3 适配层必须显式 required 校验。
- R-09：真实旧卡/旧 evidence 未读取（边界），其字节不变为间接证据：唯一写入 API 的拒绝规则 + 合成断言 + `docs/evidence` 16:59 后无写入。

## 5. 四轴输出与 rescored 标记 — PASS

- 6 题合成聚合：safety 新 `{planned 6, passed 2, NA 1, unknown 1, violations 2, checked 5}`；旧 `{6,3,1,0,2,6}`；cross_user 含 1 个记录型 violation；cross_entity 含 1 个记录型 unknown。
- 每轴 `planned=passed+NA+unknown+violations`、`checked=passed+NA+violations`、`checked+unknown=planned` 全部成立；`hard_failures`/`missing_evidence_cases` 为四轴题目并集。
- `axes_provenance` 精确：safety=`rescored`，其余三轴=`recorded_old`；逐题新值等于旧卡 state/reason；`changed_cases` 只列 safety 变化并带固定审计码；未变化只给计数。
- 报告无通过/阈值/发布状态字段（只在 `not_claimed` 负向列出四项）；`public_summary` 不含逐题 case_id/audit；72 项断言全过。

## 6. 旧 evidence 投影 — PASS

- `safety_view_from_old_evidence` 纯函数：同输入两次结果一致、不修改 case/audit 入参；运行期把 `open`/`Path.read_*`/`socket` 替换为抛错后仍成功且结果一致（零 I/O/零联网）。
- 只接受显式 `document_codes`/`record_codes`/`version_bindings`；缺 document 映射→`unit_doc_unresolved`，缺 record 映射→`unit_record_unresolved`，缺版本→`ref_version_unresolved`；均不猜。显式三映射齐全才 `identity_match`。
- `completeness!=complete`→gate `evidence_incomplete`→unknown；`turns` 非连续/空、非法映射值、非法 VersionBinding 均固定拒绝。26 项断言全过。

## 7. 契约一致性 — PASS（含两处轻微不精确）

- 契约 v0.1 的分析身份/matcher/scope/schema 版本与模块常量一致；safety state、13 个 unknown reason、4 个 violation reason、13 个 matcher 码、11 个 audit 码、version basis、四轴逐值一致；§7 重评矩阵 8/8；§5 N/A 表逐行核对；明确 safety-only、Q1a-2/Q1a-3 不在范围、不读真实 evidence（§10 NOT-RUN）。80 项断言全过。
- R-06：契约 §5 第 3 行写“unknown `annotation_unknown`”；实现按 §6“reason 取首个固定码”，applicability=unknown 且禁源 unresolved 时 reason=`forbidden_source_unmappable`（state 一致，码仍在固定表内）。属表格未展开优先级，非状态错误。
- R-07：`MATCH_CODES` 含 `ref_doc_missing`，契约 §4 未列；该码因 `_validate_source_ref` 已要求 doc_code 而实际不可达，但违反 §9“固定码只能随契约升版”，属轻微差集。

## 8. 零真实调用/隐私 — PASS

- 模块 AST 导入白名单：仅 `__future__/collections/collections.abc/dataclasses/hashlib/json/os/pathlib/re/types/typing`；无 network/provider/product/旧评测器/私有模块导入；`os` 仅 `fsync`；唯一 `open` 为 `"xb"` 独占新建；唯一内容读取为 `Path.read_bytes`（契约/自身源文件哈希）。
- 测试进程 external=0（netguard teardown 断言）；测试只对 `product_adapter` 做“不得调用”拦截、只导入 `p2_hard_evidence` 做词表等值，不 monkeypatch 旧评测器。
- 未读真实 H2/私有材料；`docs/evidence` 16:59 后无写入；账本/GO 未被写入。B-01：为核对 `c-freeze [funding]`，独立脚本只对 3 个资金件计算了 SHA256（未解析内容、未写入、未产生调用）；若“未触碰”按读取字节解释，属边界偏差，交 lead 判定。独立探针合计 261 项断言、0 失败。

## 9. 范围判断 — PASS（safety-only 合规，残余明确）

- Q1a-1 任务书要求的是新模块/新契约/合成测试/重评分入口与四轴输出；真实四轴重算、真实 scope 合同、11 fail 分诊属 Q1a-3。开发自报“只重评 safety，其余三轴 recorded_old；Q1a-2/Q1a-3 未执行”符合本包范围，且未把 recorded_old 冒充 rescored。
- R-02（明确残余）：Q1a-3 必须完成 cross_user/cross_entity/stale_source 的真实重算、消费 Q1a-2 合同、绑定其 hash，并完成 11 fail 分诊；本包不构成整体重评分完成。
- R-03：投影只用合成 audit 验证，未在真实解密 evidence 树上运行；Q1a-3 必须复核 document/record/version 显式映射与缺失映射。

## 残余与开发报告差异

| 码 | 内容 | 处置 |
|---|---|---|
| R-01 | c-freeze `[funding]` 的 ledger/GO hash 与当前 gitignored 文件不同，mtime 10:31 早于本包 | 非本包；交经理知悉，不计 Q1a-1 FAIL |
| R-02 | safety-only；其余三轴 recorded_old；Q1a-2/Q1a-3 未执行 | Q1a-3 必须完成 |
| R-03 | 投影未在真实 evidence 上运行 | Q1a-3 必须复核 |
| R-04 | run_id/evidence tree/解析 binding 为声明性；开发报告“任一不一致固定拒绝”过宽 | Q1a-3 保管侧绑定；建议报告措辞收窄 |
| R-05 | 投影对 case 字段用 getattr 默认，漏传 fail-open | Q1a-3 适配层显式 required |
| R-06 | 契约 §5 第 3 行 reason 未展开 §6 首码优先级 | 文档精度；不改行为 |
| R-07 | `ref_doc_missing` 未列契约 §4（不可达） | 契约升版或移除；轻微 |
| R-08 | 零调用测试的 product_adapter monkeypatch 冗余 | 保留 AST+netguard 为主证据 |
| R-09 | 真实旧卡字节未读，旧卡不变为间接验证 | 边界所致；Q1a-3 受控核对 |
| B-01 | 对账本/GO 仅做 SHA256 只读比对（未解析、未写入、未产生调用）；按最严“未触碰”口径属边界偏差 | 交 lead 判定；不影响零真实调用/零私有 H2 结论 |

关键 hash：模块 `d8260256…`、测试 `3eab7342…`、契约 `e0487f25…`、开发报告 `432a41f0…`、01 `57a15f9a…`、02 `d53b90b5…`、`p2_hard_evidence.py` `fba6e606…`。反例生成器复跑字节一致（`d53b90b5…`）。

## 结论

**Q1a-1：PASS（仅限合成/公共数据范围）**。现场/冻结、测试、matcher、身份/旧卡、四轴标记、契约、零真实调用均 PASS；safety-only 符合 Q1a-1 范围并已记为 R-02。整体验收、阈值/发布、Q1a-2/Q1a-3 均未由本报告完成。
