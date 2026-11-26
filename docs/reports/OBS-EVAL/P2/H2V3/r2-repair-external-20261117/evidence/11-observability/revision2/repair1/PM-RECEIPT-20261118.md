# T-R2-OBS revision2 + repair1 经理接收记录

日期：2026-11-18（Asia/Shanghai）。模式：单步；本步接收后停止。

## 经理决定

有条件接收本批**离线观测工程、SAFE 认证消费工具及停止状态**。三个独立席位对各自范围均给出 PASS；HTTP 保持 INCOMPLETE。原 revision2 总体 FAIL 及原失败证据保留，修后接收对象明确为 revision2 + repair1，不能覆盖历史结论。

这不是 HTTP 全链路通过、质量修复完成、release 或 T207 通过。真实 R2 仍为 4/5，硬失败 0、必要轴 unknown 0；C29 根因仍 unknown。本步未安排第三次真实运行、R3、全 30 题或任何真实付费调用。

## 独立验收依据

| 席位 | 实际证据与结论 | 保留边界 |
|---|---|---|
| A：真实离线索引 | `independent-acceptance/index/INDEX-RECHECK.md`；pytest exit 0，1 个编排节点、19 场景 × 4 变体、57 组业务等价比较全部 true；5 子进程 exit 0 并回收。正常产品守卫计数 0，205 次拦截正对照。 | 直接 RagIndex 边界的 citations/state，不替代 HTTP 序列化和事务。already_present、store_value_missing、store_value_ambiguous 三项只证明人工不一致元数据下的实际索引分支可达，未宣称正常摄入可达。 |
| B：契约与 SAFE | `independent-acceptance/contracts/CONTRACT-RECHECK.md`；F01–F04 的 14 项原失败断言通过。新认证完整入口最终 exit 0，42 pass / 0 fail，36 个新合成加密 case；覆盖真实 writer/Fernet/磁盘/读回、绑定、sink 和完整性门禁、隐私哨兵。 | 原 70 项独立探针仍 exit 1、67 pass / 3 unmet，不能说全绿。两项人为双故障加固 H01/H02 未修；payload-only 函数仍无 sink 上下文权限，完整消费必须使用新认证入口。 |
| C：范围、保护与包装 | `independent-acceptance/scope/SCOPE-RECHECK.md`；独立探针 exit 0。increment 仅 capture 1 hunk，累计仍为授权四文件。8 次 CLI 检查/应用均 exit 0，正反向逐字节一致；8 项篡改/错误输入均 exit 1、写前拒绝且无部分改写。 | 接收经验证的 EOL-aware 工具步骤。原裸 patch 默认 Git 失败事实保留；工具逐文件 replace，不是跨文件事务。HTTP 不重跑、不算通过。 |

三席均与开发独立，使用新合成输入及独占临时路径。经理核阅了独立报告、机器证据和当前源码身份；经理未亲自开发、修补源码或代替独立席位下结论。原开发自测 34/2、repair1 自测 19 与独立执行分别记录，未混作同一验证。

## 接收版本及保护

经理及独立席位复核：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，39 个 tracked 修改、0 staged。这些是本次收口快照。

最终 capture SHA-256：`24a66783fb622164cf5c22ab79cffb211f7b44f7d97e4a9c6590e1cc7bd4b675`。其余六个受查源码摘要与 revision2 的 after/保护记录一致；完整七文件身份见 `independent-acceptance/index/FINAL-SOURCE-IDENTITY.json`。repair1 产品增量仅为 capture 中的新事件候选组合校验，其他修正位于新 SAFE 工具和包装产物；既有业务逻辑保持。

主工作树未应用回滚；所有补丁应用验证在独立临时树。原六件交付加原 SAFE 脚本共七件，经理以最初实测摘要重新比对 mismatch=0。各席另保留原探针与结果的前后摘要。没有覆盖全部旧证据的完整开工哈希，因此保护结论仅限上述明确可证范围；不扩大成全旧证据逐字节验真。

本轮未执行 Git 写操作，也未修改旧封存、预算、账本、GO、评分器、分类器、标签、阈值或 `_index`。本记录是新建经理收口记录；未登记 G6，未作基线提交、push、merge 或 release。费用账本未重新对账。

## 剩余问题与后续保管评估

1. HTTP 在原生 Windows socketpair/asyncio/TestClient 的 accept/self-pipe 阶段独立超时，状态 INCOMPLETE；不能归因于守卫，也不能从超时推出更深环境根因。证据保留在 revision2 原 `independent-acceptance/scope-http/SCOPE-HTTP-VERDICT.md`。后续任何 HTTP 或真实运行完成声明均需补齐相应环境验证。
2. H01/H02 为已记录的非强制人为故障加固；payload-only 接口不得单独充当已认证、完整捕获的消费入口。
3. 新受控入口为 `repair1/work/safe_plan_projection.py::project_authenticated_turn`。合成验收说明该入口具备认证、完整预期 binding、sealed/failed/errors/completeness/replay/timeout 门禁；它不代替历史证据树、manifest、receipt、回合与源码身份的保管核验。
4. 保管侧下一步可先做**原封存是否实际含角色字段**的受控零调用核对。必须先确认执行者具有相应现行授权，并经既有受控路径提供输入；本次普通经理、开发和验收角色未因此获得私有读取权限，本步未执行该读取。
5. 旧 SAFE 工具无条件追加 `field_role_not_captured`，不能据此认定原始事件缺字段。即使之后获准派生诊断，也必须另行标记输入版本及派生性质；不得补写旧封存、伪称原始捕获或无证据定位真实 C29。缺失检索事件不能由新代码凭空恢复。

不扩展 locator.cells、phone/address 忠实度或 s2b 的历史待办；不开展质量修复。本步到此停止，后续工作需另行决定范围与角色。
