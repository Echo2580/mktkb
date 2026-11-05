# P1 开工门：两个文件的成品草稿（PM 准备，等主人签）

> 这两个文件是**本地配置文件**，不是代码、不入 git；它们决定"真实付费调用能不能发、最多花多少"。
> 本目录只有草稿；**原件未动**。主人确认后再复制到原件路径（或授权 PM 复制）。

## 一句话解释

代码在每次真实调用（embedding/rerank/chat）前，都会读这两个文件做硬校验：

- `budget.json` = **项目预算分配表**：总额 20 元封顶，记录各阶段分多少、已花多少。
- `S2-LIVE-GO.json` = **真实调用许可证**：写明允许哪些服务、哪个阶段、单次/累计上限、有效期、绑定哪本账。

现在 P0 用的许可证是"S2-DEV 阶段、rag+chat、600 次、单次上限 2.10 元、**今晚 23:59 到期**"。P1 要换一张新许可证，否则 T111 真实检索评测会被代码直接拒绝（不是报错信息，是硬闸门）。

**签这张许可证不等于花钱**：它只是"允许的上限"；真正花钱只在 T111 跑评测时发生，预计 0.8–1.7 元，硬顶 3 元；而且主人已定 pilot（10 题）跑完先停一次看结果。

## 文件 1：`budget.json`（预算分配表）

位置：`docs/evidence/LOCAL-R1-20261101/budget/budget.json`

只改两处（其余原样）：

| 改什么 | 原来 | 改成 |
|---|---|---|
| `stages.S2-DEV` | 18.4 | **15.4** |
| `stages.P1-RETRIEVAL` | （没有） | **3.0** |
| 合计校验 | 0+0+18.4+1.57+历史0.03=20.00 | **0+0+15.4+3.0+1.57+0.03=20.00**（总上限 20 不变） |
| `stage_revision` | revision 7 | 更新为 revision 8，记录本次划转（草稿已写好） |

依据：S2-DEV 阶段目前实际只用了 15.0266296 元（账本实测 381 次预留/381 条结果），划走 3 元后仍剩 0.3733704 元，不会出现"已花超分配"。

## 文件 2：`S2-LIVE-GO.json`（真实调用许可证）

位置：`docs/evidence/LOCAL-R1-20261101/PM/S2-LIVE-GO.json`

只改这些字段（草稿已按此生成）：

| 字段 | 原来（P0 许可证） | 改成（P1 许可证） |
|---|---|---|
| `stage` | S2-DEV | **P1-RETRIEVAL** |
| `scope.services` | ["rag","chat"] | **["rag"]**（P1 不生成答案，不许 chat） |
| `scope.stage_limits_cny` | {"S2-DEV":18.4} | **{"P1-RETRIEVAL":3.0}** |
| `scope.max_requests` | 600 | **1000**（累计口径；已用 381，P1 预计再需 320–420） |
| `scope.max_request_cny` | 2.103552 | **0.05**（单次请求保守上限） |
| `expires_utc` | 2026-11-05T23:59:59+08:00（今晚到期） | **2026-11-30T23:59:59+08:00** |
| `nonce` / `issued_utc` / `issued_by` | 旧值 | 新 nonce、签发时刻、签发人（草稿已生成） |
| `budget_ledger_sha256` | f4710b18…a014 | **保持不动**（这是账本历史前缀哈希；改成整本哈希会在一笔新调用后全面拒绝） |
| `scope.bindings.rag` | 32 个字段 | **整块原样保留**（供应商/型号/区域绑定）；chat 绑定删除 |

注意：一个 GO 文件只能承载一个阶段。换成 P1 许可证后，S2-DEV 的产品 live 调用不再被授权——P1 期间没有这个需求（P1 只做 retrieval_only 检索评测）。

## 怎么落地（二选一）

### 方案 A（最快，推荐）：主人回一句"授权你写入"

PM 执行：备份旧 GO → 把本目录两份 `.proposed` 复制到原件路径 → 立刻做只读验签（`load_live_authorization` + `resolve_live_gate`，零 HTTP、零账本写入）→ 把校验输出给主人看。

### 方案 B：主人自己复制（不用手改 JSON）

在项目根目录 PowerShell 执行三条命令：

```powershell
Copy-Item 'docs\evidence\LOCAL-R1-20261101\PM\S2-LIVE-GO.json' 'docs\evidence\LOCAL-R1-20261101\PM\S2-LIVE-GO-20261104.json'
Copy-Item '.claude\handoffs\p1-gate-drafts\budget.json.proposed' 'docs\evidence\LOCAL-R1-20261101\budget\budget.json'
Copy-Item '.claude\handoffs\p1-gate-drafts\S2-LIVE-GO.json.proposed' 'docs\evidence\LOCAL-R1-20261101\PM\S2-LIVE-GO.json'
```

然后回一句"已保存"，PM 做只读验签。

## 草稿已做的校验（PM，零真实调用）

- 两份草稿 JSON 可解析；字段齐全；
- `stages` 合计 + 历史 = 20.00；`P1-RETRIEVAL` 阶段当前已用 0、可用 3.0；
- 共享账本只读汇总：累计占用 15.0566296 / 20（历史 0.03 + S2-DEV 15.0266296），381 次预留，未新增事件；
- 草稿 sha256：`budget.json.proposed` = `084ba9ac…cc58`，`S2-LIVE-GO.json.proposed` = `39070de5…1df4`（复制后原件应与之一致）；
- 不含任何密钥；原件未被修改。
