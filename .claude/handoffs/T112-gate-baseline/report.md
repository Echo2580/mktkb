模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# T112 报告：门禁阈值校准与 P1 b0 live baseline

## 1. 完成内容

- 新增 `docs/evaluation/gate_v0_2.json`：v0.2 契约、8 项硬门禁不变、`suites` 含
  `regression`、检索 5 指标 + 四阈值字段、`status=unapproved`（未审批）。
- `gate.py`：v0.2 解析/校验（非法 fail closed）；`live+retrieval_only` 仅 v0.2 放行，
  答案类硬门禁显式 not_applicable、trace 只要求 `recall/fuse`、质量层只评估 retrieval；
  `calibrate_gate` 只产 retrieval 提案，`write_gate_proposal` 拒绝覆盖 v0.1/v0.2 配置。
- `live.py`/`runner.py`：默认关闭的 `--allow-full-live`；打开时仅 b0 + 冻结
  `b0.jsonl` 字节级 sha + 恰好 40 题；live manifest 绑定 `mktkb.gate.v0.2`。
- `baseline.py`：`live` 仅允许绑定 gate v0.2 建立 P1 release baseline；P0 口径不变。
- 真实 b0 全量 40 题 live（retrieval_only）一次 + gate 判定 + 校准提案 + 证据/test。

## 2. 验收标准自证

1. **gate_v0_2**：`load_gate_config` 通过；8 gates/`suites`/15 metrics/四字段齐全
   （`gate.py:189,381,404`；`test_gate_v0_2_config_contract`）；未审批 → exit 3。
2. **校准可复现**：两次 `gate --calibrate` 的 proposal sha 一致
   `0E7D641F…`；未改写配置（`gate.py:3181`；证据 02）。
3. **baseline 机制**：现场重算 + 缺 approver/reason 拒绝（`baseline.py:150`；
   `test_baseline_approve_refuses_unapproved_gate`）；六要素身份/无 copy/跨版本只分析
   沿用既有实现；临时 approved 副本接受审批（`test_baseline_approve_accepts_approved_live_gate`）。
4. **b0 全量 live**：40 题、`aborted=false`、manifest 七要素+sha、逐行 versions；
   请求 70（embedding 39 + rerank 31）、chat 0、重试 0；账本 stage
   `P1-RETRIEVAL` +0.0090459 元；预检/上限见证据 01。
5. **全量守卫**：默认关闭行为不变；打开仅 b0+40+冻结 sha
   （`live.py:677`；`runner.py:1052`；13 条测试含拒绝负例）。
6. **回归/预算**：本包 13 / evaluation 433 / 全量 **1933 passed**（0 failed/0 error，
   787.08s，峰值 RSS 509.1MB）；local b0/badcase/regression 对 T114 `diffs=0`、
   gate hard `[]`（证据 04）。
7. **范围诚实**：badcase/regression/holdout live 与审批均 NOT-RUN（证据 04 §D）。

## 3. 实际运行结果

- 本包：`13 passed`；evaluation：`433 passed`；全量：`1933 passed / 0 failed / 0 error`。
- 本包 1 commit（父 `cd1b3ca`；开工时 HEAD=177dab7，期间 PM 推进了 T900 簿记
  cd1b3ca；sha/stat 见提交，`git show --stat`）：代码 4 文件 +
  gate_v0_2.json + 1 测试 + 4 证据 + 本报告；不含 `var/`/账本/GO。
- live run：`b0-live-20261109T111828086143Z-0efd058b`（40 题，32 计分/8 OCR）。
- 请求/成本：70 请求（embedding 39 + rerank 31，chat 0，零重试）；预检上限 0.771174 元，
  账本保守记录 +0.0090459 元，`provider_billed_cny=null`。
- 指标：Recall/MRR/nDCG@10 all=0.96875、exact=1.0、text=0.875；
  hard_filter_violation_rate=0；empty_recall_rate all=0.03125、text=0.125。

## 4. 偏离

- 预检估算 71 请求，实际 70：1 个 query 无候选，未触发 rerank（`rerank=31`）；
  其余与预检一致，未超预算/未重试。
- 为让 retrieval_only 可判定，`trace_integrity` 在 live retrieval_only 下只要求
  `recall/fuse`（不要求 parse/answer/commit）；仅 v0.2 + retrieval_only 生效，P0 不变。

## 5. 风险与 NOT-RUN / 待主人书面批准

- **需批准（建议值，单一阈值需取跨层最宽松值）**：retrieval 5 指标
  `min_sample=8`；Recall/MRR/nDCG `absolute_min=0.855`；hard_filter `absolute_max=0.02`；
  empty_recall `absolute_max=0.145`；`max_regression_pp=2.0`。若坚持 all 层
  `min_sample=32` / `0.9487`，exact/text 会 unknown/fail，本 run 不能作 baseline。
- **待批准 baseline 信息**：run_id `b0-live-20261109T111828086143Z-0efd058b`；suite b0；
  mode live；scope retrieval_only；dataset_version `b0:b0-2026-11-04:bd4f0f7ccc6e`;
  corpus_sha256 `68899152…`; pipeline_version `08166b113481`; gate_version
  `mktkb.gate.v0.2`; gate_config_hash `5362de3c…`；32 计分/8 OCR。
  审批前置：R1 先把 `gate_v0_2.json.status=approved` + 上述阈值落盘，再
  `baseline approve --approver/--reason`（R0 未审批、未 approve）。
- **NOT-RUN**：badcase/regression/holdout live（方案 A 请求上限，未扩套件/未重跑 b0）；
  gate 审批与 baseline approve（R1）；与 P0 baseline 的跨版本比较（P1 baseline 未建）。
- 无凭据/答案原文入证据；账本/GO 未 commit；未 push/amend；无 skip/xfail/删断言。
