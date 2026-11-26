# SAFE-STRUCTURE-v6-EXECUTION

- `projection_written`；`case_count=4`。
- 已执行脚本 SHA256：`957043e6b49bc23dbcabe4d2fa6bc5f37defbd84f46952d0075c18d0b5b2da81`；与 B 记录一致。
- `SAFE-STRUCTURE-v6.json` 含四个固定 case 的结构字段及安全来源摘要；未确定的字段保持 `unknown`。
- 本机出站拦截正对照 `socket` / `urllib` / `httpx` 为 3/3；账本与预算执行前后哈希相同，见 `SAFE-STRUCTURE-v6-GUARD.json`。
- 只执行一次受控内存投影，未执行产品验收、重打分或真实请求。待 B 复核来源与出口。
