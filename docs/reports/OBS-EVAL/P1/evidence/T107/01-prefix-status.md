# T107 证据 01：regression 初始 RED（修复前状态）

- 分支 `p1/fix-retrieval`，基线 `40901b5`（执行时 HEAD）；未切换/新建分支，未 push。
- 命令（仓库根目录，`PYTHONPATH=backend/src`）：
  `.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite regression --mode local --out <tmp>`
- 结果：`run_id=regression-local-20261105T144032858382Z-57a1d4fd`，`cases=7`，`status_counts={"fail":7}`；**7/7 初始 RED**，没有把失败改写成绿。
- 版本绑定：`dataset_version=regression:regression-p1-2026-11-05:760fb06576ce`；
  `dataset_sha256=760fb06576ce991f0f9af6b13a75ed6ec0794dbb61262fdb275cfa082ae06562`；
  `corpus_manifest_sha256=5f41b1b811a5fecb0c0beab1b5070540e3c622a175a59939e293cc9b17ec3218`；
  `index_revision=49`；`mode=local`；`scope=end_to_end`；`case_count=7`。
- 语料选择：`corpus/enterprise-20261101` **全量**（`rag_experiment` 既有 subset policy 排除 boundary/scan/X04 后 49 份）。
  理由：7 项缺陷种子需要法规 L02、制度 W02、终端位置 E11、领用台账 E05 等同源资料；badcase 子集（E03/E11/P03/W01）覆盖不了 T101/T102-policy/T103。
  全量索引在本机离线模式约 50–90 秒，确定性可跑；未触碰 `var/`。

## 修复前逐条状态（local，单轮 runner）

| case | 缺陷 / source_err_id | status | 实际 kind | 失败 checks | 回答摘要 | 依赖说明 |
| --- | --- | --- | --- | --- | --- | --- |
| RG001 | T101 / ERR-20261104-03 | fail | clarification | value_hit, value_no_fabricated, source_hit, kind_correct | “请补充要查询的商品名称或规格…”（法规题被缺失字段路径截断） | T101 在 `conversations/intent.py` + `rag/query.py` 一致性；local 走 `RagIndex.ask`，已复现“未答题” |
| RG002 | T102 / ERR-20261104-01 | fail | ambiguous | value_hit, source_hit, kind_correct | “资料中有多个符合条件的对象…”，未落到鹿鸣路店 QF02 | 多轮状态继承复现依赖 T109；T102 若选“未知区域词澄清”口径，需在本包把 `expected_kind` 改为 clarification |
| RG003 | T102 / ERR-20261104-02 | fail | clarification | value_hit, source_hit, kind_correct, pagination_* | “请补充要查询的门店…”；`给出所有内容` 触发 enumerate 但无分页数据 | 多轮复现依赖 T109；`pagination_contract` 硬失败是 enumerate 旧行为的症状，T102 reset 后应消失 |
| RG004 | T103 / ERR-20261104-04 | fail | no_answer | kind_correct, refusal_unexpected | “资料‘物料领用通知’未收录…” | D09 不在 enterprise 语料；候选/回落断言由 T103 的 service 层测试承担（见报告 §4） |
| RG005 | T104 / ERR-20261104-07 | fail | answer | kind_correct, refusal_expected | “根据资料，启沣饮品（苏城）有限公司 市场部｜启市字〔2026〕41号”（答非所问） | 异常映射需 T104 monkeypatch；dataset 层只断言越界题应为 no_answer 且不出现 MODEL_UNAVAILABLE |
| RG006 | T105 / ERR-20261104-06 | fail | answer | value_forbidden, kind_correct | “滨江店的宣传海报（标识：QF01）位于店内外侧，数量 40 张。”（指代无上文仍倾倒字段） | 多轮指代复现依赖 T109；T105 需澄清“问哪项信息” |
| RG007 | T106 / ERR-20261104-05 | fail | answer | kind_correct, refusal_expected | “根据资料，第一条 新品指公司首次进入流通的单品…”（答非所问） | 文案映射主体由 T106 包内断言；dataset 层用 kind+forbidden+notes 表达 |

## 说明

- `no_answer` 在 scorer 中按拒答处理（`scorers.py:609-647`），故 RG005/RG007 显式 `should_refuse=true` 并给 `refusal_reason`，避免修复后 `refusal_unexpected` 误判。
- 每条种子的 `source_err_id` 逐条对应错误台账：ERR-01/T102、ERR-02/T102、ERR-03/T101、ERR-04/T103、ERR-05/T106、ERR-06/T105、ERR-07/T104；无一条无映射。
- 本节“实际 kind”来自 `<tmp>/cases.jsonl` 的 `outcome.kind`；未读取 `.env`、未调用真实模型/embedding/rerank/OCR。
