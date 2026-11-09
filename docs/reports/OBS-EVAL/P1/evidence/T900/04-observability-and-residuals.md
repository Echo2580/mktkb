# T900 证据 04：监控 API 独立探针 + 残余 #51–#59

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 监控 API（独立探针，零真实调用）

脚本 `.claude/handoffs/_scratch/T900/probe_observability.py`（T900 自写；tmp 数据目录 +
受控 TraceRepository + 手工 run 目录；不读 `.env`、不触碰 `var/`）：

```text
SUMMARY 39/39 checks passed; 0 failed
```

覆盖：4 端点 × 匿名 401 `AUTH_REQUIRED` / employee 403 `ROLE_REQUIRED`
（`required_role=admin`）/ admin 200；成功响应不含 secret/路径/`*_json`/原文；
span 只返回 `attribute_keys` + `attribute_count`；trace 关闭 4 端点 200 +
`trace_disabled`；holdout run 有 `cases.jsonl` 时 `details_withheld=true` 且 secret 不出现；
OpenAPI 仅 4 paths、仅 GET、401/403 声明齐全、无 `limit/offset`。
`securitySchemes` 仍为空（已知 LOW-2，文档已声明 cookie-session）。
OpenAPI 快照 sha256 `51f7edfc…db5979` 与 T114 证据逐位一致。

## B. T105 独立探针（#51 复核）

运行 `docs/reports/OBS-EVAL/P1/evidence/verify/T105-R3/02-probe.py`（T105 验收方脚本，
EchoGateway + tmp，零真实调用）：

```text
SUMMARY 131/133 checks passed; 2 failed
FAIL B2-material: 未记录 text
FAIL B2-display: 未记录 text
```

两条失败是 **T105 验收脚本写死旧文案“未记录”**，T106 统一文案后该字面已变为
“没有答案/无法判断”一类；kind/无来源/无泄露断言均 PASS。不是产品回归。
#51 仍存在（H 组 notes，同一上文“那个海报的位置呢”后追问）：

```text
H-standard-spec  kind=answer  len=576  record_markers=8
H-price-standard kind=answer  len=576  record_markers=8
H-submit-qty     kind=answer  len=576  record_markers=8
H-display-rule   kind=not_found len=49 markers=0
```

即“政策词+台账字段词”组合仍 8×8 整条倾倒，与 `_index` #51 描述一致。

## C. 残余 #51–#59 逐条判断

| # | 是否仍存在 | 复核 |
| --- | --- | --- |
| 51 | **是** | 同上 576 字/8 markers ×3；相对基线不变差，P2 |
| 52 | **部分是** | `format.ts:165` not_found 徽标仍“无匹配资料”；`INVALID_QUERY` 徽标已细分但 e2e 注入仍 NOT-RUN |
| 53 | **是** | T108 report 167 行；holdout 23 fail/7 pass（含 3 个拒答题） |
| 54 | **是** | T109 report 140 行；fail-closed 行保留 1 条诊断 trace（不在 turn_traces） |
| 55 | **是** | `scorers.py:914-916` ideal 按 unit 各占一 chunk（保守下界）；`empty_recall` 仍“无任何 retrieved unit” |
| 56 | **是** | GO `bindings.rag.embedding_requests=7 / rerank_requests=4`，实际 T112 39/31、T111 17/10；pilot 指标平凡；“pass=执行成功”表述仍在 |
| 57 | **是** | OpenAPI `securitySchemes` 缺失；T113 report/证据 01 父提交仍写 `fcc3434`（实际 `10bb42b`） |
| 58 | **部分是** | LOW-1 仍是：manifest `holdout_details=false` + summary `details_written=true` + 无 cases 时 `details_withheld=false`（本 probe 复现，无泄露）；LOW-2 同 #57；**第三项“trace_unavailable/partial_data 无专项测试”不再成立**——`backend/tests/observability/test_routes.py:558,807-818` 已有测试且随 407 定向套件通过 |
| 59 | **是** | R1 重写 run `gate.json`（exit 3→0，已披露；canonical digest 仍绑定 approval）；审批后 config_hash `5362de3c…`→`b5bfdb49…`；R0 §5 跨版本 NOT-RUN 理由“P1 baseline 未建”已过时；`diff_runs` 放行路径不重核当前 gate 配置哈希（`report.py:492-508` 仅比 gate_version） |

另：T112 report 105 行 > 80 行预算（非 #51–#59 列名，但属同一类形式偏差）；T105/T106
report 99/113 行亦已记录在 #51/#52。
