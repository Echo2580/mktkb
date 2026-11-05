角色：开发助手。任务 T006a「门禁硬层（8 项）+ 退出码」（P0 第 10 包）。全新上下文。
第一步：完整读 `.claude\handoffs\T006a-gate-hard\handoff.md`，按其「输入 / 交付物 / §5 六条验收标准 / 边界」执行；基线 = T005 收口 commit（先 `git log --oneline -5` 与 `git status --short` 确认，HEAD 可能是 PM 簿记 commit）。
本包只做硬门禁 + 退出码 + `gate_v0_1.json` 骨架；**不实现质量层/校准/豁免**（T006b），不得因质量指标返回 2。
必守口径：`required_spans(..., reason=record.reason)`；`status=replayed` 跳过 path/outcome 与 Span 校验；`*_json` 非法 JSON fail closed；不依赖内核拒绝 `mode=live`；`value_no_fabricated` 不作硬门禁；`citation_required` 不得仅凭 `source_hit`；`security_leak` 的 forbidden 引用按解析后 unit 映射比对，无法解析即 unknown(3)。
交付物只写到 handoff §2 指定路径；草稿放 `.claude\handoffs\_scratch\T006a\`；证据 ≤4 份、报告 ≤80 行。
结束时写同目录 `report.md`（五段，自证带命令或 `文件:行`），并给 ≤10 行交接摘要（commit sha、8 项门禁触发矩阵、全量通过数、偏离/风险）。
