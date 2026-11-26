# T209 首次真实 B0 经理复核

2026-11-20（Asia/Shanghai）。**确认本次 `BLOCKED`，零真实请求、零预留、0 元。** 执行退出码 3，`live_chat_model_not_authorized` 在打开真实门之前触发。输出目录未创建，无原始运行件或质量结论。T209 继续待真实 B0。 [首轮执行回执](b0-live-execution-report.md)

## 现场与来源

- 经理核对原始 stdout、执行元数据、已封存本轮 GO 和签发前副本。固定槽与原副本逐字节一致，账本和预算与发送前摘要一致。正式计划规范摘要 `c3dbbafa2a1baa9b447495dc1bab06a8f6322e5b376a87a7c12ae563abec3228`，当前绑定重新计算一致，19 项冻结件无漂移。原回执 SHA-256 `45e9956210d1e65104c5329e5d7cf3347b0a91661daeb01e077bc51dc55e617b`。
- 本次启动脚本显式把工作区 `.env` 白名单值注入进程，实际模型为 `deepseek-chat`，冻结计划的 `answer` 和 `query_expansion` 均要求 `deepseek-flash`。原生 B0 CLI 的 `load_live_env` 从进程取值，且先于 `open_live_gate`。经理按相同读取方式只读复现原模型拒绝，在同一内存配置仅改模型后，本地 `load_live_env` 通过。网络和子进程守卫实际命中 0，`.env` 与共享文件复核前后摘要一致。账户可用性与供应商响应待真实运行。 [模型环境检查](../../../../../backend/src/mktkb/evaluation/p2_live.py#L176)
- 历史 T207 公开矩阵 runbook 使用仓外 `--env-file`，公共包装器按指定文件注入子进程。T207 H2 受控入口也有独立的环境加载路径。当前 H2 包装器在 `applied_env` 里将已冻结的 `CHAT_MODEL` 显式写入进程，所以历史报告的 `model_pinned=deepseek-flash` 无法反推工作区 `.env` 默认模型。正式 B0 继续用原生公开入口。 [T207 公开 runbook](../T207/PM/T207-runbook.md) · [H2 进程模型绑定](../../../../../tools/p2_h2_controlled_execute.py#L617)

## 处置

采用方案 ①，待主人明确授权再次执行。沿用已绑定计划、候选 run ID 和 **194 次、7.464016 元**上限，先重查 run 目录和账本确认无该 ID 预留。沿用已获准的凭据来源，只在该次执行进程中将 `MKTKB_MODEL_NAME` 显式设为计划的 `deepseek-flash`，保留工作区 `.env`。沿用正式公开 CLI 和原生真实门，不传测试用 `env_overrides`。

首轮任务书缺一项同环境模型预检。接续时先在与运行完全相同的进程环境调用 `load_live_env()`，核有效模型、供应商主机和 OCR 模式，再办理本轮新 GO。使用独有的执行证据目录，保全首轮报告、旧 GO 与日志。真实运行、正式基线接收及 P2 放行的授权边界沿用原任务书。 [首次真实运行任务书](../../../../superpowers/plans/2026-11-20-t209-b0-live-execution-taskbook.md)

后续授权已取得。主人回复「批准」，允许其他 AI 按方案 ① 再执行一次。 [续跑任务书](../../../../superpowers/plans/2026-11-20-t209-b0-live-attempt2-taskbook.md)
