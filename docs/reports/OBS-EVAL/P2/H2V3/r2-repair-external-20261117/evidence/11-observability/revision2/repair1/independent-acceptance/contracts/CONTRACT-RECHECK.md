# CONTRACT-RECHECK — repair1 independent B

主人，**本席限定契约复验 PASS**：F01–F04 与 G01 的新认证完整入口已由独立实跑验证。原 revision2 历史 FAIL 报告不改写；本结论不是 R2/T207 通过，不证明真实 C29 根因，真实 C29 仍 unknown。

日期：2026-11-18。本席未参与开发，未修改产品或开发测试；先依次读取 repair1 的 DEV-REPORT、VALIDATION、PROTECTION、CUSTODY-CONTRACT，再核对增量 schema patch、新 SAFE 工具与定点源码。下述结果来自本席独立执行，不把开发的 19 passed 或自测复制为验收。

## 实际命令、退出码与检查结果

项目根工作目录，使用 `.venv`。两个仓外子目录均先检查不存在再创建；新 key 只在内存中生成，未输出或落盘。

```powershell
$p='docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/11-observability/revision2/repair1/independent-acceptance/contracts'
$io='C:\Users\dell1712\.codex\visualizations\2026\11\17\01a1e9da-ffd9-7f60-8a65-b3195fe9af11\contracts-synthetic-io\repair1-b-original70-01'
if(Test-Path -LiteralPath $io){throw 'SYNTHETIC_DIRECTORY_EXISTS'}
New-Item -ItemType Directory -Path $io | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 "$p/recheck_original70.py" $io
```

实测 **exit 1：67 pass / 3 unmet，70 项**，约 5.78 秒。原独立 `contract_probe.py` 按已知 SHA-256 先校验，再在内存中只替换新工具与临时输出路径；原断言不改。原探针、结果和报告字节均未写入。记录为 `ORIGINAL70-RESULTS.json`。

```powershell
$io='C:\Users\dell1712\.codex\visualizations\2026\11\17\01a1e9da-ffd9-7f60-8a65-b3195fe9af11\contracts-synthetic-io\repair1-b-authenticated-02'
if(Test-Path -LiteralPath $io){throw 'SYNTHETIC_DIRECTORY_EXISTS'}
New-Item -ItemType Directory -Path $io | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 "$p/authenticated_recheck.py" $io
```

实测 **exit 0：42 pass / 0 fail，36 个合成加密 case**，约 3.75 秒。初次为 40/0；补充候选重复身份与 candidate=false 两个分支后用新独占目录再次执行，得到最终 42/0。记录为 `AUTHENTICATED-RESULTS.json`。合法数据走真实 EvidenceWriter → Fernet → 磁盘密文 → 新 `project_authenticated_turn` → 既有认证/绑定/结构校验 → 上下文门禁 → SAFE。非法 envelope 无法由 writer 接受，故只用本次新合成 key 直接加密虚构非法 envelope，再由同一真实读取入口验证拒绝；未绕过 writer 对合法写入的路径保护。

两脚本均设 55 秒进程内 watchdog，以正常进程退出确认结束。没有运行 HTTP、全量或其它席位的真实索引矩阵。未启动后台任务。

## 逐项 verdict

| 编号 | 复验结论 | 独立实际证据 |
|---|---|---|
| F01_PRIMARY_ROLE_DROPPED | PASS | 原 prepared 接线探针通过，primary + multi 合并正确；新加密入口另核 primary/multi/safe 三集合合并并去重。prepared 与 effective 分别保留于 prepared_plans/events，不互相替代。 |
| F02_ROLE_UNKNOWN_INVALID_IGNORED | PASS | 原负数、bool、非法字符串、None unknown_count 四例均转 malformed；合法非负计数仍生效；missing、empty、unknown、invalid_type、not_processed、projection_failed 原断言通过。 |
| F03_RETRIEVAL_INVALID_UNKNOWN_COLLAPSE | PASS | 原非法候选/stores 计数及 truncated 类型均明确 malformed，未再投影为合法空或仅 unknown。合法 stores=available/0 与 unknown/None 分开；缺键保留 not_captured。 |
| F04_CANDIDATE_COMBINATION_UNCHECKED | PASS | 原三矛盾组合均被 schema 拒绝；新认证入口增加重复 ID、candidate=false 拒绝。0/1/512/513 合法事件加密往返；513计数只带512身份且 truncated=true；分页 has_more 独立保持 true；scope_limit 仍 unknown，不扩成全库覆盖。 |
| G01_FULL_CONTEXT_GATE | PASS（新认证入口） | 真实 CaptureSink 收合法事件后因未知 kind 进入 failed，其新合成密文经认证入口返回 sink_failed；unsealed、capture.errors、completeness status/replay/errors/missing_kind、timeout 均阻断。错 key、错 binding、缺完整预期 binding、篡改密文、坏计数和坏 event_count 均无 observed 成功输出。 |
| G01_PAYLOAD_ONLY | 仍无 sink 权限，保留限制 | 原低层断言 `SAFE_FAILED_SINK_CONTEXT_GATE` 仍 unmet：只传 payload 无法看见失败上下文。repair1 文档已明确该职责边界，不能再将低层函数当完整入口。新完整入口实际通过后，此项不再是本次完整消费入口的阻塞项。 |
| H01 / H02 | 原加固项未修，不阻塞本限定复验 | 原 `ANSWER_SINK_FAIL_FAULT_HARDENING` 与 `PREPARED_HELPER_FAULT_HARDENING` 仍抛 RuntimeError。人为双故障/替换 helper 不等于证明合法标准 sink 的自然业务回归，不扩大成本轮产品必修。 |

**不能把原 70 项说成全绿。** 其余 3 unmet 是 H01、H02 和 payload-only 上下文断言；最终应同时报告 67/3 与新认证入口 42/0，不能只取后者覆盖前者。

## 缺事件、未执行与旧证据语义

新工具 `work/safe_plan_projection.py:99-127` 在无 direct 检索事件时返回 not_captured；无 direct answer、普通旧 context-only 事件、未知/未登记 reason、多条 direct answer，均保持 execution=unknown。旧 retrieval 事件缺新字段时不合成候选计数，底层结果 field_missing；原 payload 经真实认证读回逐键不变。

新工具仅把 DOCUMENT_NOT_FOUND、UNKNOWN_STORE、RECORD_ONLY 三个 reason 列为可识别的 not_executed。源码核对 `rag/answer.py:118-130`、`:160-173`、`:174-187`，均早于唯一初次 search 调用 `:189-190`。本席另实际执行 `answer_question`，分别构造这三个分支：返回 reason 对应固定码，调用账本均只有 save，无 search。SECURITY_RESTRICTED_CONTACT 也确实在 search 前，但未列入本工具闭集，输出 unknown；保守遗漏不会推断为已执行。

未对缺字段反推原业务执行；未把旧 `field_role_not_captured` 聚合码当成原始捕获缺角色证明；没有打开真实旧封存。

## 完整入口与隐私覆盖

- 新入口 `work/safe_plan_projection.py:130-141` 实际使用真实读取器与完整 expected_bindings；`:99-127` 再进行结构与 sealed/failed/errors/completeness/replay/timeout 检查。`project_validated_turn` 只证明结构，不证明认证来源；`project_plan`、`project_retrieval` 只证明单 payload 投影。
- 合成新旧 envelope、0/1/512/513、prepared三集合合并、缺事件、失败 sink、未 sealed、捕获错误、完整性错误、replay、timeout、错 key/binding、缺 binding、篡改密文、坏类型/枚举/组合均通过各自断言。
- 汇总所有认证入口实际输出后，原始合成候选 ID、实体、路径、文本、请求身份、非法值与错误 binding 哨兵均未出现。公开结果只固定码、布尔、计数；没有保存 key。
- 两套脚本正常阶段 network/subprocess/private_file audit 尝试计数均为0；随后网络与子进程正对照各被拦1次。守卫覆盖 Python socket.connect/getaddrinfo、subprocess.Popen，以及 .env 与非本轮密文路径读取；不声称全系统调用审计。依赖的平台探测固定为脚手架平台信息，避免启动 cmd.exe，未替换检索或业务输出。

## 字节保护与当前快照

`PROTECTION-RECHECK.json` 保存结束摘要。七个产品文件开工、结束与 repair1 PROTECTION 一致；其中 evaluation_capture.py 为 `24a66783fb622164cf5c22ab79cffb211f7b44f7d97e4a9c6590e1cc7bd4b675`，其余六文件与上一版相同。repair1 新 SAFE 工具为 `486fae88978aa876ade7461948f07883632da523a49bb17fd34a2f222c1375ca`。结束 HEAD 为 `97b0066726e5b8d6f94cbc0b63a890084550c106`，tracked 修改39、staged0。

原独立材料保持：contract_probe.py=`cca7de10fd03f4437aa37354ef48d22f6d91f79901ca0926b72939af6eabe8bd`；PROBE-RESULTS.json=`d379d91014052f30cd8062e5486a59829a2bf0d177ea48c9b60903b551d04533`；CONTRACT-VERDICT.md=`73f0a474d2384681784880e973532aacf94d71501b12e024242224ace864cac9`。

本席新增仅本目录、指定仓内临时目录及授权仓外合成 IO 子目录；未修改产品、旧工具、旧证据、开发测试、预算账本、GO、评分器、分类器、标签、阈值或真实索引；无 Git 写操作。

## 剩余问题与停止点

H01/H02 仍为非强制加固；低层接口仍不可单独消费 failed-sink payload 冒充认证完整入口。HTTP 环境问题未重跑；真实索引与补丁包装由 A/C 独立席位负责，本席不为其未验项目背书。真实保管消费还需合法授权、历史封存树/manifest/receipt、回合与源码身份核验，本合成认证矩阵不替代这些。

无真实 provider、付费模型、OCR、judge、外部业务 API；未读取真实私有 key/ciphertext/.env/题答/实体/合同/计划/binding。费用账本未改。按本次任务停止，不进入质量修复或真实 C29 运行。
