角色：独立验收者，不是开发者，也不是项目经理。任务 T104（D1 异常原因透传，ERR-07 产品侧）。
你的任务是证伪，不是帮它说话。
先读 `.claude\handoffs\T104-error-classification\handoff.md` 与同目录 `report.md`（只当线索）。
逐条独立复核并亲自复跑（本包 + 受影响目录 + 全量；b0/badcase/observability），每条给 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`。
重点证伪：
1) 自己做 monkeypatch 探针逐类触发（配置/预算/provider/超时/输出校验/内部/未知），证明 error_code/retryable **真的可区分**、非 provider 原因不再报 `MODEL_UNAVAILABLE`；开发测试不算数，自己跑。
2) 文案模板：是否每类都说清"失败≠资料中没有答案/可否重试/不重复落库"；provider 类是否保留 ERR-07 正面语义；有无"换皮"。
3) 响应结构不变：对比改动前后 `AskResult`/响应 JSON 字段集合；`retryable`/`error_code` 语义未变；trace reason/error_code 与响应一致（observability 真过）。
4) 既有断言同步是否**只限取值**、清单是否与 diff 一致；有无借机削弱结构/行为断言。
5) b0/badcase local run+gate 前后对照（hard 无新增、case 级 0 变化）；全量 0 failed/0 error；改动范围/report/证据格式。
写同目录 `review.md`（≤120 行，首行注明 `wb / cn:deepseek-v4.1-flash / reasoning_effort=max`），证据放 `docs\reports\OBS-EVAL\P1\evidence\verify\T104\`，回复末尾 ≤10 行结论摘要。
你不修改任何交付物；不引用开发报告作 PASS 证据；不 commit/push/切分支；不读 Holdout；不调用真实模型。
