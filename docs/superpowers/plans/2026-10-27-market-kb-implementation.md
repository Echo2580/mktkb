# 市场部 AI 知识库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本项目建议当前聊天单线执行；本稿不代表已选择多代理执行或已启动开发。

**Goal:** 交付具备多格式资料导入、检查发布、有来源问答、版本更新与删除的市场部知识库，并在不影响家电项目的前提下以公网IP和HTTPS提供访问。

**Architecture:** React静态前端调用FastAPI；SQLite保存账号、版本、来源、索引、会话与持久任务。精确记录查询结合中文全文检索，DeepSeek组织有依据的回答；独立单并发worker解析文档并调用腾讯云OCR。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、SQLite FTS5、jieba、python-docx、openpyxl、pdfplumber、pypdfium2、Pillow、腾讯云OCR SDK、DeepSeek API；React、TypeScript、Vite；pytest与Playwright。

**Spec:** [PRD V1.3](../../../市场部AI知识库-产品需求文档.md)、[技术方案 V0.1](../../../市场部AI知识库-技术方案.md)、[接口与数据契约](../../接口与数据契约.md)、[验收矩阵](../../验收矩阵.md)。

版本V0.1，2026-10-27；状态：与墨刀原型并行完成的实施推荐稿。所有任务和测试均未执行，当前没有产品代码或运行服务。

## Global Constraints

- 首版一个部门、共享知识库，管理员和员工两角色，个人会话隔离；不开放注册。
- 文件支持.docx、.xlsx、.pdf、.png、.jpg、.jpeg；图片仅清晰印刷文字和规则表格，不做货架实物识别或手写识别。
- 文件20MB、PDF50页、Excel单文件5,000条有效记录、图片20,000,000像素；有效文件50份、有效Excel累计10,000条为验收目标。
- 上传/解析完成不代表生效，管理员检查后发布；同一逻辑资料只有一个有效版本。
- DeepSeek问答，腾讯云OCR适用免费资源优先；不自动开通后付费、不自动购买资源包、不自动换收费识别服务。
- 常规问答以20秒内完成为目标，总时限60秒；一次返回最终结果，模型调用不持有数据库写事务。
- 更新、删除与问答提交使用revision检查；旧会话追问仍查询当前资料；已删来源不再提供原件或提取内容。
- 暂不买域名，保留公网IP、HTTPS、自动续期与实际访问验证要求。
- 现有腾讯云Ubuntu24.04、2核2GB、40GB、3Mbps，已有家电项目；资源到期日截图为2026-11-23。不得覆盖、停止或改写旧项目来腾资源。
- home、session、states、staff、materials五页HTML原型已交付；T08沿用现有视觉和组件，按PRD补齐登录、手机查询及管理细节。源码与ZIP一致不代表渲染、交互或产品验收通过，不强制补独立手机画板或继续消耗墨刀积分。
- 本次只写计划、契约和验收文件，不创建产品骨架、安装依赖、初始化Git、提交、推送、连接服务器或执行真实API请求。

## Review Focus

1. 超时/重试与并发提交不得产生重复任务、重复版本或重复消息；T03/T06覆盖。
2. 删除、取消及租约过期后，迟到的worker/OCR结果不能恢复资料；T04/T07覆盖。
3. 中文短词、别名、同名、无词面重合问法及截断候选不得漏报歧义或编造唯一结果；T05/T09覆盖。
4. 恶意压缩文档、大像素图、混合PDF失败页不能拖垮共用服务器或静默发布；T03/T07/T09覆盖。
5. 个人会话与失效来源的直链访问、模型伪造引用和资料诱导指令不能绕过权限；T02/T06/T08覆盖。

## 1. 环境事实与执行前提

本次实际只读检查：`python --version`为3.13.14，`node --version`为24.16.0；Python路径为`C:\Users\dell1712\AppData\Local\Programs\Python\Python313\python.exe`；`py -0p`未列出已注册解释器。项目尚无`.git`，当前内容为需求、方案、提示词及用户的原型设计目录。

生产目标为Python3.12，不能把本机3.13检查结果作为Ubuntu3.12兼容性证据。执行T01前先定位或准备独立Python3.12解释器；没有可用解释器时明确报告，不静默改系统或安装其他环境。

未来Windows命令统一显式使用`.\.venv\Scripts\python.exe`和`npm.cmd`，无需激活PowerShell脚本，不绕过执行策略。Linux使用项目虚拟环境解释器。计划中的检查命令均是未来操作，不表示本次已运行。

依赖范围：Python3.12.x、React19.x、TypeScript5.x、Vite8.x、Pydantic2.x、SQLAlchemy2.x；其他库选择与Python3.12兼容的维护版本。T01/T02/T08解析依赖时检查支持范围和许可证，生成精确锁文件；不捏造尚未解析的patch版本。若范围冲突，先修订计划，再安装。

推荐按T01～T10单线推进，现有五页墨刀原型已交付。项目经理负责任务准备与交付核对，开发/验收角色及是否另开窗口由主人决定，不自动派发或启动实现。模型/OCR真实调用先固定模拟载荷、目标和范围；服务器操作先落实连接方式及只读预检。与PRD不一致的变更先同步文档。

## 2. 未来文件结构与职责

以下是拟创建路径，本次不创建这些实现文件：

```text
backend/
  pyproject.toml
  requirements.lock
  requirements-dev.lock
  alembic.ini
  migrations/
  src/mktkb/
    main.py                 # create_app与依赖组装
    config.py               # 数据目录、服务地址、密钥与限额配置
    db.py                   # 数据库会话、迁移、SQLite能力检查
    errors.py               # 稳定业务错误与安全响应
    auth/{models,schemas,service,routes}.py
    documents/{models,schemas,service,lifecycle,routes}.py
    ingestion/{models,worker,routes}.py
    ingestion/parsers/{types,excel,word,pdf,image}.py
    retrieval/{types,tokenize,service}.py
    providers/{types,deepseek,tencent_ocr}.py
    conversations/{models,schemas,service,routes}.py
    sources/{schemas,service,routes}.py
  tests/{conftest.py,unit/,integration/,acceptance/}
frontend/
  package.json
  package-lock.json
  src/{app/,features/auth/,features/chat/,features/documents/,features/sources/}
  src/api/{client.ts,schema.d.ts}
  src/styles/{tokens.css,global.css}
  e2e/
tools/{build_demo_corpus.py,export_openapi.py,server_preflight.py,backup.py,restore.py}
fixtures/acceptance/{manifest.json,questions.json,normal/,variants/}
deploy/{mktkb-api.service,mktkb-worker.service,entry.conf.example,README.md}
docs/原型交付记录.md
docs/evidence/
.env.example
.gitignore
README.md
```

各feature的models是ORM数据，schemas是对外协议，service是业务操作，routes仅鉴权和协议适配；禁止把解析、模型请求与事务全部堆在一个路由函数中。入口代理类型依据服务器实况确定，示例配置不能未经检查覆盖已有代理。

## 3. Task T01：冻结模拟语料与检查基线

**Files:** 创建`backend/pyproject.toml`、`backend/requirements-dev.lock`、`tools/build_demo_corpus.py`、`fixtures/acceptance/manifest.json`、`fixtures/acceptance/questions.json`、normal与variants样本、`backend/tests/acceptance/test_corpus.py`。

**Interfaces:** `build_corpus(output_dir: Path) -> CorpusManifest`；`load_manifest(path: Path) -> CorpusManifest`。manifest含文件ID、类型、SHA-256、业务版本、来源定位和normal/variant标签；questions含id、group、category、question、expected_values、expected_sources、scenario。group固定normal/negative/ambiguity_conflict/mutation；normal题的category固定exact/text/ocr，其他题category为null。

**独立交付:** 可重现的10份正常资料、40道正常题、8道无答案题、6道歧义/冲突题与U01～U10变化场景；不是一组与实现一起改答案的临时样例。

- [ ] 在已落实的独立Python3.12环境中配置pytest及语料生成依赖（reportlab、python-docx、openpyxl、Pillow、pdfplumber、pypdfium2）；使用pip-tools从pyproject的dev依赖解析并固定requirements-dev.lock。根据验收矩阵生成10份正常文件，给生成器加入固定时间、随机种子及模拟标识；附加失败页、坏文件、超限和版本差异样本不计入正常10份，正常D01的隐藏表仍保留。
- [ ] 写语料检查，明确断言：
  ```python
  assert len(manifest.normal_files) == 10
  assert len([q for q in questions if q.group == "normal"]) == 40
  assert len([q for q in questions if q.category == "exact"]) == 24
  assert manifest.record("P01")["位置"] == "B区1号货架第二层"
  assert manifest.source("P01").row == 8
  ```
  normal总计40题，其中exact=24、text=8、ocr=8；其他分组分别8、6、10条，不混入normal计分。
- [ ] 检查原始文件可读、哈希一致，人工核对图像和扫描PDF中的真实文字/表格与expected_values一致；不能只核对生成器自己的JSON。
- [ ] Run：`.\.venv\Scripts\python.exe -m pytest backend/tests/acceptance/test_corpus.py -q`。Expected：10份正常文件与40题完整，变体隔离；报告仍将业务验收标为未执行。
- [ ] 冻结manifest及问题文件，记录哈希；以后更改标准答案需说明原因并重新冻结，不因产品回答错误临时改题。

## 4. Task T02：应用、数据库与登录权限

**Files:** 创建`.env.example`、`.gitignore`、`backend/requirements.lock`、`backend/src/mktkb/{main,config,db,errors}.py`、auth模块、初始迁移、`backend/tests/conftest.py`和`integration/test_auth.py`；修改T01创建的pyproject与dev锁，加入生产依赖，使用pip-tools分别生成生产及dev精确锁，服务器仅安装生产锁。

**Interfaces:** `create_app(settings: Settings) -> FastAPI`；`Database.session() -> Session`；auth接口按契约。测试提供`client`、`admin_client`、`employee_client`、`second_employee_client`、`db`、`store`，均使用独立临时目录与临时数据库。

- [ ] 写API检查：未登录GET`/api/v1/auth/me`为401；错误凭据401；合法登录返回user与csrf_token；密码、令牌不在响应/日志中出现；过期和退出会话不可复用。
  ```python
  assert client.get("/api/v1/auth/me").status_code == 401
  assert admin_client.get("/api/v1/auth/me").json()["user"]["role"] == "admin"
  assert employee_client.get("/api/v1/auth/me").json()["user"]["role"] == "employee"
  ```
- [ ] Run：`.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_auth.py -q`，先确认缺失应用/行为导致失败，不把环境导入错误当作业务测试已建立。
- [ ] 实现配置、SQLite外键与FTS5能力检查、迁移、预置账号、会话、CSRF和Origin规则；认证日志脱敏。环境变量缺失时给出明确启动错误，不读取旧项目配置。
- [ ] 重跑auth检查及迁移检查，Expected：401/403语义、会话撤销、数据库独立性正确；`healthz`不泄露配置。
- [ ] 更新README本地启动说明和版本记录；首次正式编码时再按授权建立本地Git并记录检查点，不设置远程或推送。

## 5. Task T03：上传、持久任务与Excel/Word检查

**Files:** documents模块（lifecycle留T04）、ingestion/models.py与worker.py、parsers/types.py、excel.py、word.py，`integration/test_import.py`、`unit/test_parsers.py`。

**Interfaces:** `stage_upload(...) -> UploadReceipt`、`claim_job(...) -> JobLease | None`、`run_one_job(...) -> JobRunResult`，解析器统一`parse_document(path, kind, services) -> Iterator[ParsedUnit]`。沿用契约，T04/T05消费已保存的SourceUnit。

- [ ] 写解析与上传检查：同名/同字节并发去重、严格字节限额、表头在第7行、多表与隐藏表、原始行号、电话前导0、公式缓存缺失、后台任务可恢复。
  ```python
  units = list(parse_document(normal_d01, "xlsx", parse_services))
  p01 = next(u for u in units if u.fields.get("标识") == "P01")
  assert p01.locator.row == 8
  assert p01.fields["位置"] == "B区1号货架第二层"
  assert not any(u.locator.sheet == "旧草稿" for u in units)
  ```
  `normal_d01`与`parse_services`在本任务的测试fixture中定义；字段与locator沿用契约。
- [ ] Run：`.\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_parsers.py backend/tests/integration/test_import.py -q`，Expected：实现前针对缺失功能失败。
- [ ] 实现流式暂存与实际大小检查、指纹和短事务落库、租约/检查点、原文顺序及分页预览。压缩容器检查解压规模，不执行宏；关闭浏览器不取消任务。有效版本和最新处理版本分开返回。
- [ ] 重跑上述检查，另模拟worker在保存检查点后退出再启动，Expected：不丢任务、不重复发布、未发布内容不进入查询；错误文件不变成完整成功。
- [ ] 生成OpenAPI快照，记录新增接口及检查结果；保持契约中的字段名和错误码。

## 6. Task T04：原子发布、取消与删除

**Files:** documents/lifecycle.py、对应迁移、`integration/test_lifecycle.py`；修改文档路由、任务状态检查与查询基础过滤。

**Interfaces:** `publish_version(...) -> Publication`、`delete_document(...) -> Deletion`、`cancel_version(...) -> None`，全部采用契约中的expected版本与revision。发布后`Document.active_version_id`和`KnowledgeState.revision`在同一事务更新。

- [ ] 写U01/U02/U04/U08/U09及替换前后记录总量测试，包含过时发布、重复发布、取消新版保留旧版、删除任务和旧租约提交；50文件/10,000记录是负载目标，不在本任务擅自变成发布拒绝阈值。
  ```python
  result = publish_version(db, doc_id, v2_id,
      expected_active_version_id=v1_id, expected_revision=revision)
  assert result.revision == revision + 1
  assert db.get(Document, doc_id).active_version_id == v2_id
  ```
  v1/v2暂存fixture在本任务通过T03接口创建，不直接篡改生产数据。
- [ ] Run：`.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_lifecycle.py -q`，确认错误顺序及并发场景失败。
- [ ] 实现发布状态校验、原子切换、可见性过滤、文件/任务取消、有效记录总量维护及幂等结果。物理清理异步，但访问与查询权限立即撤销。
- [ ] 重跑并发检查，Expected：两个旧revision请求只能一个生效；已删/取消任务的迟到结果不能写回，原有效版不被失败新版影响。
- [ ] 记录数据库事务边界与清理行为；删除消息、删资料和取消新版三个操作不能混为一谈。

## 7. Task T05：精确记录与中文全文检索

**Files:** retrieval/{types,tokenize,service}.py、索引迁移、`unit/test_retrieval.py`、`integration/test_visible_index.py`。

**Interfaces:** `QueryIntent(mode, terms, entity_filters, requested_fields)`；`retrieve(db, intent, revision=..., limit=20) -> EvidenceSet`。EvidenceSet提供units、kind、total_candidates、revision、candidates；kind为matches/ambiguous/conflict/none。字段类型详见契约。

- [ ] 先建立B0语料的本地精确检索检查，覆盖Q01～Q24、别名“海报/展示架/价签纸”、1～2字短词、候选超过limit、有效资料冲突及历史旧索引。
  ```python
  evidence = retrieve(db, QueryIntent(mode="record", terms=["海报"],
      entity_filters={"store": "城东店"}, requested_fields=["位置"]),
      revision=revision)
  assert evidence.kind == "matches"
  assert evidence.units[0].fields["位置"] == "B区1号货架第二层"
  ```
- [ ] Run：`.\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_retrieval.py backend/tests/integration/test_visible_index.py -q`，确认未分词、错实体和旧版泄露场景会失败。
- [ ] 实现一致的中文分词与业务词典、编号/短词精确与受限子串匹配、FTS5排序、有效版本关联及候选总数。冲突只对明确相同实体的字段比较，同名不明时澄清。
- [ ] 重跑并记录正文问题的召回来源；包含无词面重合问法的真实模型查询扩展留T06/T09验证，不能凭本地固定词典宣称全部语义检索已通过。
- [ ] 保存检索证据与失败样本。若B0检索达不到目标，报告实际缺口再改方案，不私自引入新付费模型或降低题目难度。

## 8. Task T06：DeepSeek、个人会话与来源校验

**Files:** providers/types.py与deepseek.py、conversations模块、sources模块、`integration/test_chat.py`、`test_source_access.py`、`test_answer_commit.py`。

**Interfaces:** 模型网关`async complete(request: CompletionInput, timeout_seconds=...) -> CompletionOutput`；`async ask(...) -> AskResult`；`get_message_source(...) -> SourceView`。沿用契约六类结果与来源绑定本人message的接口。

- [ ] 写会话所有权、client_request_id、追问、候选、冲突、无答案、伪造来源ID、错误精确字段、提示注入、生成中发布/删除及提交事务竞态测试。
  ```python
  assert employee_client.get(other_user_messages_url).status_code == 403
  assert forged_reference_result.kind == "service_error"
  assert forged_reference_result.error_code == "MODEL_OUTPUT_INVALID"
  assert changed_revision_result.kind == "knowledge_changed"
  assert changed_revision_result.sources == []
  ```
  结果fixture由本任务的可控模型适配器与事务屏障产生，不是写死业务答案。
- [ ] Run：`.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_chat.py backend/tests/integration/test_source_access.py backend/tests/integration/test_answer_commit.py -q`，先确认关键行为失败。
- [ ] 实现受约束查询扩展、证据构建、模型适配和输出检查。精确字段不允许模型改写；无效模型引用按MODEL_OUTPUT_INVALID服务错误处理，不能伪称知识库无资料。最终revision检查、请求/会话有效性与答案写入同一短事务；外部调用在事务外。
- [ ] 重跑本地检查；真实DeepSeek验证按验收矩阵单独进行并记录模型、目标、模拟载荷、用量，未获得对应条件时R保持未执行。超时、断网和进程恢复时不重复创建业务消息。
- [ ] 导出更新后的OpenAPI和真实/替身检查记录；来源删除后只返回410元信息，直链原件同样撤销。

## 9. Task T07：PDF、图片与腾讯云OCR

**Files:** parsers/pdf.py、image.py、providers/tencent_ocr.py、OCR调用记录迁移，`unit/test_pdf_image.py`、`integration/test_ocr_jobs.py`。

**Interfaces:** 文本PDF/扫描PDF/图片继续输出同一ParsedUnit；OCR网关`recognize(page: OCRInput, mode: OCRMode) -> OCRPageResult`。额度错误映射OCR_QUOTA_UNAVAILABLE，限流映射OCR_RATE_LIMITED；不把整份文件仅第一页识别当成功。

- [ ] 写混合PDF逐页选择、空页报告、部分失败禁止发布、原图/单元格定位、20MB与编码限制差异、最大像素、OCR配额和租约取消测试。
  ```python
  assert quota_exhausted_job.state == "blocked"
  assert quota_exhausted_version.state == "failed"
  assert failed_page_report.failed_pages == [3]
  assert failed_page_publication_allowed is False
  assert late_ocr_result_was_saved is False
  ```
  上述fixture通过可控OCR网关和真实PDF/图片输入生成。
- [ ] Run：`.\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_pdf_image.py backend/tests/integration/test_ocr_jobs.py -q`，确认失败页、额度和迟到结果场景先失败。
- [ ] 实现按页文本/表格提取与有界渲染、图片内容/像素校验、尺寸/体积分块和定位映射、腾讯SDK适配、2次/秒限制、有限退避、成功检查点复用。传输前后校验任务有效性；已发送请求不承诺可退额度。
- [ ] 重跑本地检查；账号开通、适用免费资源包、后付费状态核对后，再执行矩阵指定的真实文字图和表格图；不故意耗尽真实额度来测试错误。所有8页都必须有成功/空页/失败记录。
- [ ] 更新处理报告、错误码和识别原图对照证据。真实识别字段不达标时保留失败，不用模型编造纠正缺失值。

## 10. Task T08：对接墨刀原型的前端

**Files:** frontend目录、生成的api/schema.d.ts、features/auth/chat/documents/sources、styles、e2e；`tools/export_openapi.py`、`docs/原型交付记录.md`。

**前置条件:** 以已交付的五页HTML及ZIP记录视觉版本，先完成浏览器渲染、关键交互和差异核对；技术方向沿用推荐方案，关键冲突在相应任务前落实。现有原型未覆盖的登录、手机查询和管理细节按PRD及现有组件补齐，不以必须新增独立手机画板或继续消耗墨刀积分作为启动条件；不将源码检查表述为已获人工视觉验收。

**Interfaces:** API以契约和服务端OpenAPI为准，使用锁定的生成工具输出schema.d.ts；ApiClient统一处理Cookie、CSRF、业务kind和HTTP错误。页面路由`/login`、`/chat/:conversationId?`、`/documents`，来源与检查可用面板承载，不引入额外业务模块。

- [ ] 先定义浏览器检查：员工无资料管理入口且直达受限；上传→处理→检查→发布不同状态；当前有效V2与处理中V3同时表达；来源抽屉、会话删除、异常结果和移动端回退正确。
  ```typescript
  await page.goto('/chat'); // 本测试使用预置employee storageState
  await expect(page.getByRole('link', { name: '资料管理' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '发送' })).toBeDisabled();
  ```
  storageState由测试用账号通过T02接口生成，不使用真实生产凭据。
- [ ] Run：`npm.cmd --prefix frontend run test:e2e -- --project=chromium`，实现前确认目标页面/交互缺失导致失败；截图基线等原型确认后建立。
- [ ] 按原型实现布局和共享组件，业务数据来自真实后端接口。模型/OCR配置不出现在前端；按钮、表格、弹层及加载/错误状态复用。手机只做登录、问答、个人会话与来源查看，管理提示使用电脑。
- [ ] Run：`npm.cmd --prefix frontend run typecheck`、`npm.cmd --prefix frontend run build`及上述e2e。以1440×900、1366×768、1440×720、390×844及375px宽核对；不以静态截图代替真实上传、发布和查询。
- [ ] 保存原型对照、实际截图与差异清单；修正必要差异后记录交付版本，不把尚未实现的按钮画成已完成业务。

## 11. Task T09：完整效果、容量和安全验收

**Files:** `backend/tests/acceptance/test_qa_baseline.py`、`test_mutation_regression.py`、`test_limits.py`、`frontend/e2e/acceptance.spec.ts`、`docs/evidence/`下按版本保存的报告。

**Interfaces:** 读取T01的固定manifest/questions；输出逐题`expected/actual/source/status/provider/environment`，不能修改输入答案。T04/T06提供独立数据库恢复与模型适配入口。

- [ ] 写40题计分与关键规则测试，逐项映射矩阵；加入10条更新回归、压缩炸弹/超大图、提示注入、共享额度处理及凭据泄露检查。
  ```python
  assert exact_correct == 24
  assert normal_correct >= 36
  assert negative_passed == 8
  assert ambiguity_conflict_passed == 6
  assert mutation_regressions_passed == 10
  ```
  所有计数来自实际结果，不是固定赋值或从报告标题推断。
- [ ] Run：`.\.venv\Scripts\python.exe -m pytest backend/tests -q`；前端typecheck、build、test:e2e。先完成L/B，再独立记录允许执行的R，不能把模拟模型成绩混入真实问答成绩。
- [ ] 在固定语料上记录召回、回答、来源与识别错误，按所属任务修复并回归受影响项；标准数据和阈值不因失败而改变。
- [ ] 用50份有效资料、10,000条有效Excel记录和3个同时在线用户执行容量/延迟检查，记录失败和资源占用；目标服务器结果在T10补充，不能用本机结果冒充服务器结果。
- [ ] 完成验收矩阵的已执行证据；外部条件不足的行明确未测试或阻塞，不通过删用例实现全绿。

## 12. Task T10：同机部署、IP HTTPS与恢复检查

**Files:** `tools/server_preflight.py`、`tools/backup.py`、`tools/restore.py`、`backend/tests/integration/test_backup_restore.py`、`deploy/mktkb-api.service`、`mktkb-worker.service`、`entry.conf.example`、deploy/README.md、最终README及服务器证据。

**前置条件:** 服务器连接方式、只读预检结果、现有入口归属、备份位置与资源余量已明确；有足够条件安全实施新增服务。当前未提供连接凭据，本次不连接或尝试登录。

**Interfaces:** `collect_preflight() -> PreflightReport`只读收集端口、服务摘要、系统/磁盘/内存和代理类型，不收集密钥正文；`create_backup(data_dir, destination) -> BackupManifest`；`restore_backup(manifest, target_dir)`只允许空的独立目标目录。

- [ ] 写备份/恢复路径校验、WAL一致性、已存在目录拒绝覆盖及配置脱敏检查；备份恢复测试在临时目录运行。
  ```python
  assert restored_dataset.record("P01")["位置"] == "B区1号货架第二层"
  assert restore_into_existing_directory_is_rejected is True
  assert preflight_contains_secret_values is False
  ```
- [ ] Run：`.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_backup_restore.py -q`，完成本地检查；Linux上以项目Python3.12重复后端检查与依赖验证。
- [ ] 读取服务器预检和旧项目健康基线，确认新目录/运行用户/端口；部署本地构建的静态产物与独立虚拟环境，新增两个systemd服务。配置IP证书、自动续期及续期加载；不得停止旧服务抢占证书验证端口。
- [ ] 运行新服务的重启、断开SSH后访问、数据库/文件持久化、可信HTTPS、个人来源权限和旧家电项目访问回归；按真实端口和服务名执行，不预设旧项目启动方式。容量负载检查同时观察两项目。
- [ ] 在独立目录完成恢复演练，记录访问链接、部署版本、账号交付方式、到期日和续费/迁移待办。若IP证书或资源条件无法满足，报告实际证据和替代方案，不降级HTTPS验收或修改旧项目。

## 13. 实施完成与版本记录规则

每个任务先运行针对性失败检查，再实现、验证并记录文件及接口变化；合格后记录本地检查点。Git尚未初始化，当前不执行提交。用户启动实现后，先固定本地版本管理方式；任何推送、公开仓库、资源购买、真实资料外发或现有服务调整均不能从本计划自动推导授权。

任务之间只重复受影响的检查；最终阶段执行完整矩阵。前端原型、技术方案、接口契约、标准语料与代码分别记录版本，原型新增功能不自动进入需求。

## 14. 本稿自检与当前剩余事项

- 已列T01～T10的交付、文件、接口、行为断言与未来检查命令；20条F需求和30条A用例在验收矩阵中逐条映射。
- 尚未执行任何产品测试，代码和二进制语料尚未创建；所有任务复选框保持未完成。
- 五页HTML原型已交付，含资料管理核心模拟流程；源码及ZIP一致性已核对，浏览器渲染、逐点交互和人工视觉验收尚未执行。技术方案及本计划仍是推荐稿，T08沿用原型视觉并核对差异，不照搬演示数据或占位规则。
- Python3.12路径/环境、真实服务配置及载荷、免费包与后付费设置、服务器连接及运行余量、IP HTTPS与续期均需要后续落实。
- 下一项可交接工作是T01语料与检查基线；进入实现前须获主人明确的任务授权，并落实相应任务的关键前提。技术细节优先沿用推荐方案，发现影响准确性、资源或交付的关键矛盾时具体报告，不重复开展整轮需求确认。
