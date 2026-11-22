# T305 独立验收记录（知识资产与导入状态）

- 验收人：项目经理（MainAgent）
- 日期：2026-11-22
- 对象：开发窗口交回的 T305（交付说明 `T305-evidence\T305-delivery.md`）
- 依据：`T305-dispatch.md` §7 完成条件、§8 红线；T301 冻结口径；T303 裁决②与兼容契约

## 一、结论

**正式 PASS（无条件项）**

任务书 4 场景（同文档多引用 / 旧版换版 / 待审核 / 导入失败）全部可核对，计数与问答明细口径一致，旧版未当新版内容展示，全页只读，边界干净。3 项上报裁决见 §四。

## 二、独立复跑证据（验收人本机执行）

| # | 命令 | 退出码 | 结果 | 验收日志 |
| --- | --- | --- | --- | --- |
| 1 | `npm.cmd run build`（含 tsc） | 0 | 646 modules，dist 成功 | `T305-acceptance-rerun-build.txt` |
| 2 | `npx.cmd playwright test --config=playwright.operations-assets.config.ts`（派单原命令，未设复用变量） | 0 | **20 passed / 0 failed**（37.6s，A1-A10 双 project） | `T305-acceptance-rerun-assets.txt` |
| 3 | `npx.cmd playwright test --config=playwright.operations.config.ts operations-overview --reporter=list` | 0 | **26 passed / 0 failed**（46.9s，P1-P13 双 project） | `T305-acceptance-rerun-t303.txt` |

- 开发方报告的「webServer 收尾挂起」在本次两条复跑中**均未复现**，全部干净退出，未执行任何释放监听进程的动作。
- 本次复跑已生成配置声明的 `T305-evidence\playwright-assets.json`（expected=20 / skipped=0 / unexpected=0 / flaky=0），补齐了交付时缺失的 JSON 报告产物。
- 开发方两份自报日志（20 passed 26.1s 复用跑法 / 20 passed 6.3m 原命令）与本次复跑结论一致。

## 三、红线逐条核对（代码实读 + 用例断言双重确认）

| 红线 | 结论 | 依据 |
| --- | --- | --- |
| 当前生效只认 published，不把最新版当生效版 | 符合 | assetModel.effectiveVersion 仅 state='published'；launch 文档（仅 V1 待审核）显示「暂无生效版本」（A1/A6 断言） |
| 旧版不展示新版内容 | 符合 | VersionList 逐版本只渲染自身字段；A5 断言 V1 superseded「已替换」、无「当前生效」标记 |
| 失败/待审核旧版继续生效 | 符合 | A7 断言「V2 导入失败，V1 继续生效」+ 失败环节「文字识别」+ PARSE_INCOMPLETE；A6 横幅含继续生效说明 |
| document_id 下钻走详情端点 | 符合 | assetsApi.loadDocumentDetail 直调 GET /operations/documents/{id}；列表参数不含 document_id/version_id（A7 直链开抽屉） |
| 引用数排除 conflict、冲突关联单独标注 | 符合 | 列表取 final_citations；抽屉 related>final 时标注「含冲突关联，不计入最终引用」（A4 断言 price 7d final=2 / related=3） |
| 库存口径不回溯 | 符合 | 横幅与表脚均注明「待审核为当前库存口径，不随窗口回溯」 |
| 零处理按钮 | 符合 | 全页仅跳转/筛选/分页/详情；A5/A10 断言无上传/发布/删除/审核/重试类按钮 |
| 兼容 testid 语义 | 符合 | ops-placeholder-ready/total/document/state 在摘要条；P7 场景 total=state 过滤后总数==overview failed_total（两者同为全量失败文档计数，口径恒等）；T303 回归 26 条全绿实证 |
| 名称搜索降级已标注 | 符合 | UI 明示「名称搜索为已加载页的客户端过滤」，表脚重复说明 |
| 不编造字段 | 符合 | 无逐阶段时间线（接口未返回不画）；详情未取到显示「版本状态未取到/详情未取到」，不臆造 |

种子核对：25 份资料 / 2 页 / review 2 / failed 1，与 seed-summary.json 及用例期望一致；种子只写隔离目录，唯一 POST 为登录。

## 四、上报事项裁决

1. **列表接口补 latest_version 字段与 name 搜索参数：接受建议，转 T306 评估。** 当前两处降级（needsDetail 按需补详情 + 客户端名称过滤）均已登记、UI 标注、不编造数据，验收接受。是否立 T302 补充单由 T306 汇总后报主人决定，与 T303 裁决①的「截断影响对账再立补充单」合并评估。
2. **Playwright 收尾挂起：接受报告，缓解措施接受，统一整改转 T306。** T305 专用配置的 gracefulShutdown / 直启 node vite / stdout ignore 属测试基础设施适配，不改被测逻辑，接受；本次验收复跑未复现挂起（可能与内存压力相关）。T303/T304 冻结配置的同类加固与 reporter 按轮次分目录一并列入 T306。
3. **T304 联动参数名：已静态核实一致，无需额外动作。** T305 的 requestsPath 与 T304 的 readFilters 同出冻结的 filters.ts（document_id/version_id/window 同名同义）；A8 断言 href 含 document_id+window，T304 侧资料横幅与筛选已验收接收同参数。T306 端到端链路（待处理→导入失败详情→关联问答）再做一次实跑串联。

## 五、边界实核

- git：开工快照与当前已修改集合一致（9 个文件，均为 T302/T303 既有改动），验收复跑后不变；HEAD 仍 0d6ba61。开发窗口收尾时 PATH 无 git 的说明接受——验收人已用本机 git 独立复核。
- 冻结文件时间戳全部早于 T305 开工（03:35:18）；3 个晚于开工的文件（RequestsPlaceholderPage.tsx、operations-qa.spec.ts、playwright.operations-qa.config.ts）均为 T304 独占文件、由 T304 窗口在自身交付/C1 期间修改，内容已在 T304 验收中实读复跑，非 T305 越界。
- `var\` 三库时间戳验收前后均为基线值（2026-11-21 16:42:50 / 2026-11-05 20:52:22），未写。
- 无新依赖（package.json/lock 时间未变）、无付费调用、无上传/发布/删除、git 无写操作；验收后 8288-8292/5299-5302 无残留监听。

## 六、接受的实现决定与已知限制（登记，不阻塞）

1. needsDetail 节流（无生效版本或 latest_import 非空才补详情，约每页 3 次）与「已发布且无导入线索→无新版」保守分支，接受；后端补字段后可移除（§四.1）。
2. 图片类型筛选客户端完成、名称搜索仅覆盖已加载页（当前 25 份全量加载等价全量；>400 条时受限），接受，UI 已标注。
3. 待审核横幅文案较原型补充「无生效版本的资料暂不参与问答」，属事实性完善（覆盖 launch 场景），接受。
4. 列表累计上限 20 页（400 条）页脚标注，沿用 T303 裁决①口径。
5. 交付时证据目录缺配置声明的 playwright-assets.json/html 报告——本次验收复跑已补 JSON；html 报告非必需，不阻塞。

## 七、P3 进度

T301 / T302 / T303 / T304 / T305 全部 PASS。下一步 T306 集成验收与候选交付，已登记移交事项：testMatch 收窄 + reporter 分目录 + Playwright 收尾加固（§四.2）、T302 补充单评估（§四.1）、启动路径变更核对（04515f3/0d6ba61）、最小 P2 回归集与三条端到端链路、性能实测与查询计划、发布候选提交主人。