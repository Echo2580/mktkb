# T207 冻结数据契约独立审查

主人，独立结论：**确认存在冻结 H2 来源期望与公开单一终态 active 规则的矛盾，完整 H2 契约验收阻断，须由主人裁决契约。** 本次没有修改金标、题面、答案、active 校验，也没有拆分场景。该结论不表示 24/30 的分数阈值数学上不可达到；达到该分数也不能消除已确认的契约矛盾。

审查基线为 `d7728db35655ae67569aec84cc4ededeaf7f7c13`，日期 2026-11-11。只审查经理的 `contract_audit.py`、`contract-audit.json`、公开导入计划和旧公开状态，并以全新受控探针复核封存期望的安全聚合。没有执行产品 ASGI、真实评测或真实 provider 调用；本次不是当前运行环境的重新灌库证明。

## 独立证据

使用 `contract_review_probe.py`，没有导入或调用经理审计脚本。探针从公开计划的上传文件、上传名、document_ref 和顺序重建文档版本，再以公开文件 SHA-256 匹配旧状态的版本 SHA-256。结果记录于 `contract-review-aggregate.json`。

- 公开计划共 12 份上传、8 个最终文档。12/12 文件哈希与旧状态版本一致；顺序版本号匹配 12/12；上传回执顺序匹配 12/12；8/8 文档的最终 active 等于其最后发布版本。计划 label 与旧状态 label 一致。
- 独立确认公开变体映射：V03 → D01 v1、V04 → D01 v3、V05 → D01 v4、V06 → D02 v2。旧状态中 D01 active 为 4，V04 对应的 v3 为 superseded 且 inactive；D02 active 为 2。
- 封存进程只导出计数：30 个 case、24 个正向 case；1 个正向 case 的 expected_sources 要求 inactive 版本，且该 case 没有 active 的 expected_sources 替代；inactive expected 引用 1 个、inactive relevant 引用 1 个。全部 58 个来源引用均可经公开映射识别，未映射引用为 0。
- 58 个来源引用均未显式携带 `version_number`。此计数本身不等同于 58 个错误；本次矛盾通过公开变体的文件哈希和导入身份确定，不依赖从题目、答案或隐藏 locator 猜测版本。
- 经理聚合计数与独立探针完全一致；经理记录的 manifest/state hash 与实际输入一致；探针前后所观察输入 hash 不变。

| 公开输入 | SHA-256 |
| --- | --- |
| H2 ingest-plan | `362e3ea10f673021d78c7a647305f04b8557b364a14482ebc2ba370d7752ed19` |
| 旧公开 h2-state-out | `86489ad4b5a5f08d755a3e9c6f231db42d964ea04c524e5d7398b3f703ebd614` |
| H2 manifest | `8874985ef8f4aacc5689d5dc4dc60db759c2620492d159171712f7a9b679ce4b` |

## 对经理脚本的审查

脚本只在进程内调用既有 holdout loader；key 由 loader 读取，脚本不读取或输出 key 内容。输出为固定计数、固定公共版本枚举和公开 hash；没有导出题号、题干、答案、locator 或逐题 trace。网络连接入口被禁止，异常只导出固定失败码。该脚本使用的变体映射原本为固定表；本次独立探针对其增加了公开上传顺序及文件哈希证明，因此审计结论不再仅依赖固定表的注释。

经理脚本基于旧公开状态，不重新执行产品；它也不证明四类硬失败为 0。本次独立审查只确认契约矛盾和公开历史终态，不能替代运行时验收。

## 阻断范围与剩余问题

在同一公开终态、冻结 expected_sources 与当前 active 校验同时保持的前提下，上述正向期望与 active 约束不能同时满足。后续不得将其包装成检索或答案修复已经完成，也不得通过修改金标、放松 active 校验、删题、降分母或自行拆分场景使其通过。完整 H2 验收及以该完整口径宣称通过的受控真实复测，应等待主人对冻结数据契约的明确裁决；独立的离线产品修复工作可继续，不构成该阻断已解除。

另已只读检查 `p2_score_run.py` 的 `holdout_case_scores_from_rows`：所构造评分的 `hard_failure=None`，注释明确未分类不能冒充零硬失败。`gate.py` 还区分适用性、unknown 与 not_applicable，并声明当前 case 契约对实体及生效时间字段覆盖的限制。因此本次契约审查**没有证明跨用户、跨实体、过期和安全四类硬失败为 0**；缺覆盖、N/A 或未分类不能记成真实环境零失败。本任务没有扩展为评分器或门禁代码修复。

验证命令：仓库根执行 `.venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207-QUALITY-REPAIR/contract_review_probe.py`，最终退出码 0。探针使用未修改的数据层 loader，以仅设置包搜索路径的方式避开无关 ASGI 应用初始化；socket 网络入口与子进程均被禁止。解封仅在内存中，输出只含固定枚举、计数、布尔值和公开 hash。新增真实调用 0，预算、GO、账本和冻结文件未改，未 commit。
