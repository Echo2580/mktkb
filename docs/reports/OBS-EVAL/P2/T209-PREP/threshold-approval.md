# T209 正式门槛批准记录

2026-11-20（Asia/Shanghai），主人在 T209 确认项回复「批准正式门槛」。本记录落实该次阈值授权。真实 B0 请求、费用、正式基线接收及发布各自办理。 [会话交接](../../../../../.claude/handoffs/2026-11-20-080407-t209-approved-thresholds-next-baseline.md) · [T209 任务书](../../../../superpowers/plans/2026-11-19-t209-official-baseline-taskbook.md)

| 项目 | 批准口径 |
| --- | --- |
| B0 | 执行 40/40，至少正确 36/40，Q01–Q24 精确题正确 24/24，OCR 执行 8/8。 |
| N / C / U | 分别通过 8/8、6/6、10/10。U 按已批准的真实 smoke 与本地关键控制口径分列。 |
| H2 | 同批至少正确 24/30，硬失败 0，保留五个分层及受限聚合。正式准入须核实必要硬门禁证据。 |
| 硬门禁 | 沿用冻结配置的八项硬门禁及原最小样本，必要证据未知时阻止正式准入。 |
| 诊断 | 沿用 15 项观测指标及空阈值。Ragas 两项用作辅助诊断。 |

使用 `docs/evaluation/gate_v0_3_approved.json` 显式绑定新正式 run。默认加载路径仍指向冻结模板，历史 run 按原摘要回查。使用项目加载器逐项核对阈值、八项硬门禁、套件及 15 项诊断指标。 [正式配置](../../../../evaluation/gate_v0_3_approved.json) · [冻结模板](../../../../evaluation/gate_v0_3.json)

| 工件 | 文件 SHA-256 | 加载器配置摘要 |
| --- | --- | --- |
| 冻结模板 `unapproved` | `3af301dba2d4dbd1bcc9d8f17c656f8a80755820fa2a8559b787974f20b5619d` | `d10975732dd50616f959fde71a3ead42822b877e98c55c4367902cb053cfd2a8` |
| 正式配置 `approved` | `b1094cc726230be2ec22ec811d34a948ea4a2fe03aab2c0fcc4f20c99764d961` | `7fa6f47a445f9643eb7f2e5ae78a72411007da38a56fca1082657870b2eab094` |
