# T900 阶段二 · candidate_drift 证据

2026-11-21（Asia/Shanghai）。本文件记录 T900 冻结清单复核的漂移事实。复核窗口 `t900-acceptance` 只读，未修改任何候选或冻结文件。

## 复核命令

```powershell
.\.venv\Scripts\python.exe docs\reports\OBS-EVAL\P2\evidence\T900\probes\freeze_drift.py `
  docs\reports\OBS-EVAL\P2\evidence\T900\probes\out\freeze_drift.json
# 第一次：exit 2（drift_count=1）
# 第二次（约 1 分钟后）：仍 drift_count=1，同一文件
```

## 结果

- 清单文件：`docs/reports/OBS-EVAL/P2/candidate-freeze.json`（13,839 B，mtime `2026-11-21 01:13:19`）
- 清单声明：`files=49`、`missing=0`、`frozen_at_local=2026-11-21T01:15:00+08:00`
- 实测：`files_checked=49`、`drift_count=1`、`missing_count=0`
- 其余 48 个文件 SHA-256 与字节数全部一致；正式门禁 JSON `d4c98f92…`（53,053 B）一致；批准配置 `b1094cc7…`（5,785 B）一致。

## 唯一漂移

| 项 | 值 |
| --- | --- |
| 路径 | `docs/reports/OBS-EVAL/P2/manager-acceptance.md` |
| 冻结期望 SHA-256 | `5edeade6311afd9f78046e54bdda982be6fa421332e1a8ea2cfa42c183d85c16` |
| 实测 SHA-256 | `e2831432072819dd6dc0a73547472af70a59acf8cea8362802f029520ae72227` |
| 冻结期望字节 | 17,265 |
| 实测字节 | 19,857 |
| 实测 mtime | `2026-11-21 01:13:39`（晚于冻结 JSON 的 `01:13:19`） |

## 漂移内容（只读观察）

当前文件比冻结期望多出 `## 任务 1 · H2 文档级禁源与离线重建 · 经理核收`（约 2.6 KB），并在顶部状态表把“任务 1”标为“已核收（带保留）/已接收”。该文件还包含任务 4 的独立 FAIL→T4-R1 复验历史与任务 2/3 的核收记录。

未观察到该文件在两次复核之间继续变化（两次 SHA 相同）。本窗口未写入该文件；其 mtime 晚于冻结 JSON，属冻结后更新。

## 判定

按 `candidate-freeze.md` §冻结声明“任何文件变动即视为候选漂移，须重新冻结并定向复验”，本候选**不满足 drift=0**，T900 正式总验收停止于冻结门，报 `candidate_drift`。技术门 JSON 与批准配置本身未漂移；重新冻结该文档并确认其余 48 项后，可在同一窗口继续。

## 产物

- `probes/out/freeze_drift.json`（第一次）
- `probes/out/freeze_drift_second.json`（第二次）
- `logs/freeze-drift.log`（第一次控制台输出）
