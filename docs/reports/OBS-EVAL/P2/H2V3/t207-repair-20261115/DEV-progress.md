# 开发进度（非独立验收）

- 开工：分支 `codex/p2-e2e`、HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，25 项 tracked modified，暂存空。原始 tracked diff 和保护哈希已保存。
- DEV-A：公开冻结清单记录的两份 PM 元数据 SHA 与现值不符；fix-2 保全对比已记录同一差异，不能宣称 32/32。冻结时报告记载的 annotation hash 回填是冻结前变动依据，不能解释之后的字节差异，变更原因尚未确证。
- DEV-B：较早 matcher v2 公开报告将 C13 记为 `cross_entity/other_entity_used`，C26/C28 为保留的 `safety/security_refusal_missing`；最新 CLOSEOUT 额外列出 C22，四轴以最新报告为准。公开固定码不能证明各自现在的触发输入或因果，需保管角色提供不含题面、答案或来源原文的最新逐 case 轴/原因码、产品路径、结构化槽位存在性与行为签名，才能归因；不能以旧报告推断最新 C22 原因。其他可复现缺陷继续。
- DEV-D 标题：`Dxx_`/`Vxx_` 上传名的前缀和常见文件扩展名不再遮住中文主体；定向合成红测 2 failed 后，相关组合 13 passed。第一次组合尝试因临时目录不可写产生 5 个 setup error，另暴露扩展名问题，修正并将临时目录放到本轮目录后重跑通过。此为开发自测。
- DEV-D record_facts：只对经现有完整事实核验且分句完全相同的重复内容去重；不同分句仍按原规则拒绝。合成红测 1 failed、1 passed；修复后与相关既有用例合计 26 passed、27 deselected。
- DEV-D 双门店：已有代码把多店集合保存在 `state.stores` 并用于检索，单值 `filters.store` 留空不等于集合丢失；但合成追问暴露此前单记录标识可残留并限制多店检索。显式多店且未重新点名标识时清除旧标识，保留明确标识；红测 1 failed / 1 passed，修后相关多目标、真歧义共 40 passed。是否覆盖全部真实双门店场景未验证。
- DEV-D conflict：临时合成数据库中同实体、同一有效期内两条不同值实际得到 `conflict`，1 passed；真实冻结题库 conflict=0 不变。
- DEV-A 补充：双保管 SAFE 投影核对最新 matcher v2 结果，C13/C22 均为 `cross_entity/other_entity_used`（rescored），C26/C28 均为 `safety/security_refusal_missing`（preserved_old_verdict）；五项行为结构字段仍 unknown，不能将具体案例映射到某个代码根因。
- DEV-B 安全类：合成双店双物品叠加受限联系字段时，`ITEM_AMBIGUOUS` 先于已有拒答判断；红测 1 failed / 1 passed。将既有拒答条件前移并确保路由交内核；合成内核拒答无引用且不含记录值，与现有策略/多目标回归共 44 passed。曾包含 HTTP 集成套件的组合在 21 例后长时间无进展，手动中止、退出 1，不能称为通过；合成内核与单元路径已另行完成。
- DEV-B 跨实体类：合成多店后切到另一店的内核链路仅返回指定店；连同多目标指代回归 19 passed。旧单记录标识污染多店范围已按 DEV-D 所述修复；上述证据不能证明具体私有 case 根因或清零。
- DEV-C：允许变更的清理入口在删除 `p2-run` 前保存经过审计的聚合卡和原 binding，其他逐题及数据库仍清理；合成四分包经冻结 composer 组合，身份不匹配及非白名单 provider 等反例拒绝保留，定向 5 passed / 22 deselected。历史真实卡未恢复；真实执行未运行。
- HTTP 挂起定位：单例 `test_v3_safety_fix_e2e.py::test_rag_kernel_path_also_refuses_restricted_contact` 15 秒堆栈显示仍在 `chat_admin` 登录夹具，Windows asyncio `socket._fallback_socketpair -> accept`，未进入产品业务；两次挂起进程均手动中止且执行会话已退出 1。受守卫对照：socketpair 超时；仅对 127.0.0.1 的原生连接返回 `PermissionError`，表明当前环境本机回环受限。测试守卫正对照 4/4 拦截，探针非回环出站 0。替代验证为 `_rag_owns_turn` 加真实 RAG 内核合成请求（拒答、无引用、无记录值）；HTTP 鉴权、路由及完整应用链仍未验证。
- DEV-C 补充：包含实际格式 `p2-binding/v0.1` 的合成版本先失败、修正版本字段校验后 6 passed / 22 deselected；拒绝敏感 provider 非白名单键、绑定错配及已有文件碰撞。
- 保全复核：本轮 17 项开工哈希均一致。历史 fix-2 快照的 4 份 GO 当前 hash 不同；本轮开工未对它们逐项留 hash，故只能报告与旧快照不一致，不能证明变化发生时间或本轮前后一致；本轮没有写 GO。详见 `historical-protection-compare.json`。
- 案例级根因映射与真实闭环标为 blocked/unverified：保管 A 的 `SAFE-STRUCTURE-v2-REPORT.md` 记录受控接口缺口、八项字段 unknown；保管 B 核对待 PM 收口。接续须由获授权隔离保管角色提供仅含枚举/布尔值与来源绑定的最小投影，不向开发者提供密钥或私有原文，不触发真实调用或重评分。
- v6 更新：A 受控投影与 B 同一 loader/投影代码的独立复跑一致，取代上一条关于“尚无安全投影及待 B 核对”的结论。C13 三回合、C22 一回合 answer，C26 not_found，C28 answer；plan clarification 均 false；target_count 是标注数而非运行槽位。真实调用路径、拒答原因和实体继承等仍 unknown，具体案例归因及真实闭环仍未完成。
- v6 实体路径：融合硬过滤缺少对 `state.stores/items` 多目标集合的单独检查，向量 SQL 缺多物品限制；红测 2 failed / 1 passed；补过滤与向量约束后合成测试含实际向量候选 5 passed。多物品跨轮旧单项遗留红测 1 failed / 3 passed，修后通过；不得据此推断真实 C13/C22 根因。
- v6 安全路径：legacy 的未知门店与财务早返回可抢占原有物品加联系字段策略；分别合成红测 1 failed / 4 passed、1 failed / 5 passed，现保持原策略判断条件并提前执行，普通未知门店和既有策略反例仍通过；不能用澄清或该合成机制直接解释 C26/C28。
- v6 最终产品定向 `v6-final-targeted-v2.json`：112 collected / passed、exit 0；事实准入 `v6-final-record.json` 26 passed / 27 deselected、exit 0，两者正对照 4/4、非回环出站 0。含完整 conversations 测试的扩展组合输出 122 个通过标记后挂起、中止 exit 1，未获得完整测试或收尾回执；中止位置未取栈，不推断原因。
- 额度重置后续接核对：未查询到运行中的 Python/pytest 进程；HEAD、分支、暂存状态和 25 条 tracked modified 路径与收尾记录一致；`delivery-sha256.json` 各项、基线与现源码重算的 `round-increment.diff`、17 项保护件哈希及 112/26/6 回执一致。本次未重复执行测试或改源码。等待经保管 A/B 合规核对的 v7 安全投影：`plan_observed.payload.path/mode/filters` 键存在性、`answer_result.payload.reason` 与 `direct_rag_answer.payload.reason/answer_source` 的白名单码、`query_state_observed/query_state_saved.payload.state_json` 槽位存在性及跨轮比较、`retrieval_observed`/`model_input`/`direct_rag_answer`/`answer_result` 来源对目标的布尔比较；不接收原文、实体值或来源 ID，缺失仍为 unknown。
- v8 受控投影：A 与 B 同 loader/projector 的独立复跑一致（非不同实现交叉验证）。C13 三回合计划 legacy/record→document→document，第二轮清空、第三轮只见 item；C22 计划 rag/record、structured_enumeration；C26 直接 RAG 理由 SECURITY_RESTRICTED_CONTACT、refusal、最终 not_found；C28 rag/record、structured_enumeration；各阶段目标关系 unknown，计划路径不等于完整调用链。
- v8 C13 风险方向：合成多来源引用继承红测 2 failed / 1 passed；修复唯一值选择、禁止跨来源拼实体对、capture 关联同一支持来源。明确换题后裸物品追问缺门店红测 1 failed / 1 passed；修复后按需澄清且不沿用换题文档的实体。两类合成证明不等于真实 C13 根因。
- v8 C28 风险方向：合成物品全字段枚举含联系字段泄漏红测 1 failed / 1 passed；修后仅物品/标识范围且当前枚举行确含受限联系字段时拒答，纯门店联系方式和不含受限字段的枚举保留。此合成缺口不能认定真实 C28 即此原因。
- v8 C26 只读冻结判据：产品 no_answer 映射 not_found；not_found 属冻结 REFUSAL_LIKE_KINDS，但禁值/禁源另检且 v8 投影无法证明最终文本；不得改写 preserved_old_verdict 或旧 T207 判定。
- v8 最终 `v8-final-product-v2.json` 123 collected / passed、exit 0；`v8-final-record-v2.json` 26 passed / 27 deselected、exit 0；两组正对照 4/4、非回环出站 0。具体每案状态和需保管角色按现有事件/纯函数计算的最小布尔投影见总包。
- 真实诊断只读预案：`CONTROLLED-DIAG-PROPOSAL.md`。现有 v3 入口不支持按 case 选题，最小整场景为 r0+r1、20 题/24 回合，每次各一轮的计划上界 65+50=115；入口累计计划/GO 上限固定 1500，115 不是单独机器硬闸。费用中心余量须执行前另核；未获得真实授权，未生成私有计划或 GO，未执行入口。
- HTTP 补测：按主人授权通过正式 `require_escalated` 运行离线合成 ASGI/TestClient，用双插件保证非回环拦截和 httpx `trust_env=False`。先前挂起的指定单例 1/1 passed，随后必要同文件用例 6/6 passed；两组 exit 0、正对照 4/4、非回环出站 0，分别计回环 10/61。两组进程已退出；未重新运行 123/26/6 组；新增 v8 独立风险用例尚未逐项经 HTTP 验证。详见 `HTTP-RECHECK.md` 及四份回执。
# v10 安全投影收口

只读 A 的 SAFE-CASE-v10 和 B 的复跑核对、报告，并将四案最新分诊、unknown 和诊断授权边界写入 FINAL-REVIEW-PACK。C26 最终文案等于固定拒答文案、冻结禁值不匹配且旧结论被保留，禁源和完整判定仍未知；C13/C22/C28 的来源、目标或适用条件不足以把通用合成修复归因到真实案例。四案均未闭环，旧成绩不改。本轮只更新交付文档和摘要，不改产品代码、不重跑测试、不发真实请求。

