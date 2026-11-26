# CONTRACT-VERDICT

主人，本轮独立契约验收结论：**FAIL**。角色合并、malformed 与 unknown 的区分、候选组合一致性均有实际失败例。此结论不表示 R2/T207 通过；真实 C29 根因仍为 unknown。

执行者 B 未参与本批开发；只新增本目录与指定临时目录中的验收文件，以及经理追加批准的仓外全新合成密文。本结论使用独立编写并实际执行的探针，不将开发自测作为验收证据。

## 实跑证据

工作目录为项目根。最后一次命令如下；指定仓外子目录在运行前检查不存在，再新建，未覆盖旧文件。

```powershell
$io='C:\Users\dell1712\.codex\visualizations\2026\11\17\01a1e9da-ffd9-7f60-8a65-b3195fe9af11\contracts-synthetic-io\run-b-20261117-02'
if(Test-Path -LiteralPath $io){throw 'SYNTHETIC_DIRECTORY_EXISTS'}
New-Item -ItemType Directory -Path $io | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 'docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/11-observability/revision2/independent-acceptance/contracts/contract_probe.py' $io
```

退出码 **1**，耗时约 2.74 秒；70 项断言中 53 pass / 17 unmet。17 项由 14 项确定缺陷断言、1 项 SAFE 上下文集成缺口、2 项故障注入加固断言组成，不等于 17 个独立产品缺陷。结果固定码见 `PROBE-RESULTS.json`。探针设置 55 秒 watchdog，进程正常退出，无后台测试遗留。

首次启动在依赖导入的 Windows 平台探测阶段被子进程守卫拦截，exit 1；未执行业务节点。验收脚手架将 `platform._syscmd_ver` 固定为合成平台信息，避免依赖调用 cmd.exe，未改产品。随后 run-01 为 53 pass / 16 unmet；仅追加失败上下文与坏 envelope 校验后运行 run-02，未把原失败断言改绿。

## 确定缺陷

| 固定码 | 源码位置 | 实际最小结果 | 影响 |
|---|---|---|---|
| F01_PRIMARY_ROLE_DROPPED | `work/safe_plan_projection.py:16-34`；`conversations/service.py:2498-2502` | 合法 `field_role=location, field_roles=[]` 经真实 prepared 事件接线后主角色仍在事件中，投影却给 `observed_empty / [] / 0`。多角色 `[status]` 时也不并入 location。 | 合法观测被投影成空角色；不是“原捕获缺失”。effective 路径合并主角色通过，prepared 与 effective 不能互相替代。 |
| F02_ROLE_UNKNOWN_INVALID_IGNORED | `work/safe_plan_projection.py:30-34` | `role_unknown_count` 为负数、bool、非法字符串、None 时均被忽略，空列表得到 `observed_empty / invalid_count=0`。合法非负 2 则正确得到 `invalid_role / invalid_count=2`。 | malformed 被清成合法空；SAFE 入口未做到 malformed/unknown/empty 分离。capture schema 本身拒绝这些坏类型，不能据此宣称独立 SAFE helper 已处理非法输入。 |
| F03_RETRIEVAL_INVALID_UNKNOWN_COLLAPSE | `work/safe_plan_projection.py:58-75` | 负数/bool candidate_count → `candidate_count_status=unknown`；负 stores_count → `stores_status=unknown`；非法 truncated → null；这些均顶层 `status=observed`，无任何 invalid 标记。 | 顶层 observed 可仅表示 join 字段被读取，不能单凭它指称候选成功；但非法与缺失/unknown 已实际合并，消费者无法知道输入坏掉。此次判失败不强制具体顶层 status 名称，要求明确表达 malformed。 |
| F04_CANDIDATE_COMBINATION_UNCHECKED | `observability/evaluation_capture.py:544-573` | schema 实际接受 `candidate_count=0 + 非空 unit_ids`、`candidate_count=1 + empty=true + 空 unit_ids`、`candidate_count=513 + 仅1个 unit_id + truncated=false`。 | 逐字段类型合法而组合矛盾；可通过 envelope 校验，不能作为可信同次检索观测。需要仅对具有新事实的事件检查一致性，保持旧事件缺键兼容。 |

F01 对应 3 项失败断言；F02 对应 4 项；F03 对应 4 项；F04 对应 3 项，共 14 项。完整实际状态仅输出固定角色码、布尔和计数，未输出原始身份。

## 集成缺口与加固项

- G01_SAFE_FAILED_SINK_CONTEXT（INCOMPLETE）：真实 `CaptureSink` 先收一条合法合成检索事件，再经未知 kind 派发进入 failed。将已保留的事件 payload 送入 SAFE helper，仍返回 `observed / candidate_count=0`。helper API 只收 payload，没有 sink/envelope 上下文。代码检索仅发现 helper 定义与测试调用，未发现随包的完整上下文消费者。因此不能声称现有 helper 单独保证“先检查事件及 sink 完整性”。这也不是证明所有外部保管调用者都错误；需由实际调用方先做失败门禁，或补交能验收的消费接线。坏 event_count 的合成 envelope 已由真实 validator 拒绝。
- H01_SINK_FAIL_SECONDARY（加固，不作为正常业务回归）：`rag/answer.py:241-244` 的异常处理直接调用 `sink.fail`。使用可被 `capture_scope` 接受的 `CaptureSink` 子类，同时让 emit 与 fail 抛 RuntimeError，可实际使异常逃逸，未返回业务答案。该例人为注入双故障，未证明标准 CaptureSink 在合法内部状态下自然触发；不单靠此项要求产品返工。正常 CaptureSink 的 helper 故障、仅 emit 故障均不改变合成回答，sink 正确 failed。
- H02_PREPARED_HELPER_EXCEPTION（加固）：`conversations/service.py:2474-2505` 没有 helper 外层防护；人为替换 safe_roles 抛 RuntimeError 时 `_answer` 逃逸。没有发现其对普通合法内置 list/tuple 自然抛出的证据，不将人为故障替身当成真实业务回归。

## 覆盖矩阵

| 项目 | 独立结果 | 证据边界 |
|---|---|---|
| 角色白名单、安全角色与非法计数 | PASS，F01/F02 除外 | 纯函数 + 合成 prepared/effective 接线；未知元素不回显。 |
| stores 缺失、None、空、非空、负数、bool、非法容器 | PASS | safe_stores 正确 unknown/None 或 available/计数；schema 拒负数、bool，拒 state/count 矛盾。SAFE 非法/unknown 分离见 F03。 |
| missing / empty / invalid / not_processed / failed / unknown | 部分 PASS | 基本角色与检索状态均独立探测；非法 unknown_count 等见 F02/F03。 |
| prepared/effective | 部分 PASS | prepared 真实服务函数同步前段直接推进 coroutine，绕开 Windows asyncio/socketpair；effective 实际 answer_question + 合成 search。没有 HTTP 验收主张。 |
| 候选 512 / 513、分页与 scope | PASS，F04 除外 | schema 接受512拒513条；实际 answer 捕获513计数、512 ID、truncated=true；page_has_more 独立 true，scope_limit 保持 unknown。计数仅该次返回候选并集，不是全库候选量。 |
| 前置拒答 / 检索异常 / 无 sidecar | PASS | 前置拒答不 search，异常回 error，均无成功检索事件；正常无 sidecar 为 unknown，不是 joined/not_applicable。无事件不能由此断言空候选或明确未执行；需要该次执行证据。 |
| sink 故障 | 部分 PASS / G01 | 正常 sink 下 helper故障及 emit故障保持回答；失败上下文消费缺口与双故障加固见上。 |
| 旧事件/envelope 不带新键 | PASS | clean 前后逐键相等；新生成旧式合成事件经真实 EvidenceWriter、Fernet、磁盘密文、read_encrypted_evidence 往返，无新字段合成。未开真实旧封存。 |
| 新事件真实加密 IO + SAFE | PASS，SAFE 缺陷除外 | prepared/retrieval 合成事件读回逐键相等，检索读回后 SAFE count=0；独立新 key 仅内存生成，未记录或输出。 |
| envelope 非法完整性 | PASS | 合成 event_count 与事件数量不一致被 EvidenceIntegrityError 拒绝。没有声称遍历全部历史 envelope。 |
| 隐私哨兵 | PASS | 非法角色、原始候选 ID、实体、路径合成哨兵不进入 SAFE 输出；结果文件仅固定码/布尔/计数。 |
| 外发守卫 | PASS | 导入后至业务/IO结束，network/subprocess/private_file 尝试计数均0；随后网络和子进程正对照各被拦1次。网络守卫覆盖 audit socket.connect/getaddrinfo，子进程覆盖 subprocess.Popen；不宣称全系统审计。 |
| 真实索引大矩阵 | OUT_OF_SCOPE | 由独立助手 A 负责，本助手未重复，未引用其未完成结果。 |

## 保护与停止点

按要求依次读取 DEV-REPORT、VALIDATION、PROTECTION、SOURCE.patch、ROLLBACK.patch、CUSTODY-CONTRACT；再定点读取源码、SAFE helper 与两项开发测试。旧 `work/r2_case_boundary.py:1365-1366` 的 `field_role_not_captured` 为无条件追加，不能证明真实旧捕获缺角色；未读取任何真实旧封存。

七个产品文件开工与结束 SHA-256 均与开发 PROTECTION 的结束摘要一致，详见 `PROTECTION-AFTER.json`。结束 HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，tracked 修改39、staged0，均与开工快照一致。本助手未修改产品源码、开发测试、旧证据、预算/账本/GO、评分器/分类器/标签/阈值或真实 `_index`；未执行 Git 写操作。

未运行全量、真实 provider、付费模型、OCR、judge、外部业务 API；没有读取真实 .env、私有 key、真实 ciphertext、题答、实体值、合同、计划或 binding。已有真实质量结论与 C29 unknown 保持不变。验收交付后停止，供经理安排限定观测范围的返工。
