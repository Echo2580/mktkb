# T-R2-OBS revision2 开发交付

## 状态

已加入受控观测接线与新版 SAFE 投影；独立验收尚未执行，真实 C29 原因仍 unknown。旧材料没有被补写，未读真实私有捕获。本报告只包含固定码、计数、布尔和哈希，不含题面、答案或原始身份。

## 旧诊断纠偏

`work/r2_case_boundary.py` 在计划事件循环只读取路径、模式、日期、词和过滤器；它没有读取角色，之后无条件追加 `field_role_not_captured`，异常回退也固定此码。当前 `conversations/service.py` 和事件 schema 已有 `field_role`、`field_roles`。因此历史 SAFE 缺口码不能证明原始角色缺失；历史原始事件是否含角色仍 unknown，需合法保管方核对。旧脚本、旧报告和封存未修改。

## 实现

- prepared 计划的现有 `plan_observed` 增加角色白名单投影、非法数量、角色可用性及 stores 可用性/数量；不存在或 None 为 unknown，空列表为 available/0。历史可选字段缺失时不合成。
- `rag/retrieval.py` 在实际早退、取行、去重并入点生成 `store_join_observed` sidecar，不改变旧 `store_join` 业务载荷及二元组解包。固定码区分各前置条件、派生值与店家行 missing/ambiguous、实际 joined、already_present 以及替身 unknown。非记录路径由直答事件记 not_applicable；无事件不是空候选。
- `rag/answer.py` 在实际 search 成功返回一次后发一条 `retrieval_observed`；其角色及状态属于 effective 计划，与 prepared 不混同。前置拒答和 search 异常不发成功事件。候选来自同次 exact/lexical/vector/fused 的并集，按既有 QA 身份规则去重：record 优先 record_unit_id，缺失时回退 chunk_id，并合并 unit_ids。身份只进入受控 capture，SAFE 投影不输出。`candidate_count` 是该次返回集合而非全库潜在候选；`truncated` 指事件列表超过 512 的截断，`candidate_scope_limit=unknown` 保留召回内部限制未知，`page_has_more` 单独表示分页。
- capture schema 为新字段做固定码、非负整数和安全角色逐项校验；原 payload 未带新键保持原样。新投影 `work/safe_plan_projection.py` 区分 missing、empty、invalid、not_processed、failed 和 unknown，且不输出原始 ID 或非法字符串。

## 验证和保护

详见 `VALIDATION.md` 和 `PROTECTION.md`。最终定向组合 34 passed，SAFE 投影后续修订 2 passed。离线索引测试含零外发账本和两项拦截正对照；捕获开/关及开工源码快照对照仅覆盖一组合成输入。加密 IO 用新生成合成 key。`SOURCE.patch` 是本批产品源码相对开工脏树的差异，`ROLLBACK.patch` 只撤本批源码 hunk，已做不写入的 `git apply --check --ignore-space-change`，未应用。新测试和报告为独立新增文件，不包括在源码回滚补丁中。开工文件字节快照位于工作区 `.tmp-r2-obs-baseline/`，真实索引的改前对照依赖该快照；不要误当 Git HEAD。

## 余项及停止点

- 条件分支是合成、部分通过 `_load`/渲染替身构造；真实离线索引链只覆盖一组正常记录枚举，尚未在真实索引覆盖所有联结成功、missing、ambiguous 及全部状态对照。捕获故障的输出一致性是替身测试，未覆盖真实索引。角色/状态与旧事件兼容虽有类型清洗及加密 IO 定向验证，完整 SAFE 消费者/所有历史 envelope 未遍历。
- Windows 有界集成诊断在 TestClient 的 asyncio socketpair 初始化阶段挂起；未装守卫独立 socketpair 同样挂起。未能完成原 HTTP 集成，不能据此归因于守卫或证明 HTTP 端到端通过。临时测试目录留存，未清理既有工作。
- 运行前拒答、检索异常、空候选、512 上限、非记录路径等由合成替身测试；未验证真实 C29，也不声称 R2/T207 已完成。locator.cells 接受登记、混合请求的 phone/address 忠实度与 s2b 均未更改。
- 本轮无真实 provider/付费模型/OCR/judge/业务 API 运行；settled 与保守费用增量均按未发生真实付费调用记录为 0，账本未改、未重对账。历史两轮 settled 合计 0.0864940 元，保守口径 0.0930815 元，引用旧报告。

交付后停止，等待独立验收；不进入 R3 或全题运行。
