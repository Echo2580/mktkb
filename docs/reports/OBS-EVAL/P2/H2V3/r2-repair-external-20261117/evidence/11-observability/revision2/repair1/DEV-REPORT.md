# T-R2-OBS revision2 repair1 开发报告

## 结论

已按独立验收阻塞项完成限定返工，等待独立复验；原 revision2 总体 FAIL 的验收结论仍有效，本报告不是独立验收。真实 C29 根因仍 unknown，没有进行真实运行或质量修复。

- F01：新 SAFE 计划投影同时合并 `field_role`、`field_roles`、`safe_roles` 的合法角色；角色集合不完整时保留已知角色并标 unknown。无需修改 prepared 接线或检索角色逻辑。
- F02/F03：非法 `role_unknown_count`、候选/门店计数和分页/截断布尔不再当作合法空值或未知；缺字段与明确 unknown 分别输出固定状态。无原始非法字符串输出。
- F04：仅当 `scope=direct_rag_retrieval` 且存在本批 `candidate_count` 时，capture 校验候选身份数、去重、empty、512 截断与 count 一致。旧事件缺新增字段时逐键兼容；分页和候选范围不合并。
- G01：新增 `work/safe_plan_projection.py` 的 `project_authenticated_turn`：受控密文经既有 Fernet 认证与完整绑定检查读取后，再由 `project_validated_turn` 运行既有 envelope validator、检查 sealed sink、errors、completeness 与 timeout；缺事件为 not_captured，不能推断执行情况。对于且仅对于源码中明确位于 search 前的三个直接答复 reason，可标 not_executed；其他情况保持 unknown。返回只含固定状态、白名单角色、计数和布尔。payload-only 函数是低层函数，无权判断 sink；旧 revision2 工具已被独立验收否定，应使用 repair1 新入口。

产品只改 `backend/src/mktkb/observability/evaluation_capture.py`；未改 conversations、answer、retrieval、query、facts 或质量/评分行为。用户授权之外的旧材料未修改；新文件全部在 repair1 下。

## 验证与包装

指定独立探针的运行副本仅调整自身输出目录与加载路径：本次改前首次复现 53 pass / 17 unmet；修后以新工具与当前源码运行得到 67 pass / 3 unmet，进程 exit 1。剩余两项 H01/H02 是独立报告列明的不强制双故障加固；G01 原探针继续只调用 payload-only 函数，因此按原断言仍 unmet，不能把这次探针称为全绿。新完整上下文入口的真实 failed sink、缺事件、坏事件计数、认证与合成密文往返另有定向测试通过，等待独立复验。

最终定向测试 19 passed；包括原始旧/新 IO 保护节点、SAFE 上下文、正反例与原生行尾包装。真实离线索引 19 场景和 HTTP 旧问题按指令未重复；引用原独立结果的范围及限制，不把它扩展为本次复验。执行细节、失败与守卫范围见 VALIDATION.md。

`patches/` 提供 increment 与 cumulative 的 source/rollback patch 及各自 SHA 清单；`work/native_patch.py` 先校验补丁、所有目标的输入 hash、精确 hunk 上下文和输出 hash，再保持目标文件原生 LF/CRLF。CLI 默认只检查，明确 `--apply` 才写入；逐文件替换，不是跨文件原子事务。两种补丁正反向均在独立临时树逐字节往返；累计 CLI 四文件前向/回退 hash 均匹配，主工作树从未应用回滚。使用命令与路径见 VALIDATION.md。`SAFE-TOOL.patch` 供审阅新旧 SAFE 工具差异，不应覆盖旧工具。

## 剩余限制

原生 Windows HTTP socketpair 挂起本轮未重跑，HTTP 端到端仍未验证。加密入口调用已有 Fernet 读取与 envelope/binding 校验，不能代替保管方对历史证据树、manifest、receipt、角色授权及当前代码绑定的额外核验。捕获关闭、单故障及 19 场景等价结论来自前述独立席位对上一版的测试，本次只改校验；最终结论仍需独立复验。人工双故障 H01/H02 未改。无真实外发、付费模型、OCR、judge 或业务 API 运行；未重对账，费用账本未改。
