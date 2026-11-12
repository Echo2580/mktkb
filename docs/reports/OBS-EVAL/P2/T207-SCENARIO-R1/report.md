# T207 SCENARIO R1 离线最小修复

主人，开发自测完成，SCENARIO 专项 **76 passed**；待全新 R1 独立验收及经理受控实际绑定，当前不代表 T207/P2 质量通过。

基线 HEAD：`a751889bd4673fe43ba9c631f4e2ea13ce4fe585`；日期：2026-11-12。原 SCENARIO 未提交成果、旧报告/独立 review/实际失败证据均保留，未重做原包。

## 最小改动与接口

- `backend/src/mktkb/evaluation/p2_holdout_scenarios.py` 仅改 `_axis` 的目标字符串条件：`entity_type` 仍非空 str、长度≤256；`entity_key` 仍 str、长度≤256，允许空串作为未解析占位，不把它作为可信实体身份。
- 其它结构、refs、filters、覆盖、hash、冻结批准及固定错误码校验不变；load/contract/subset/plan/compose 接口和默认评分源码不改。
- `backend/tests/evaluation/test_p2_holdout_scenarios.py` 原内容按字节保留，仅追加3个合成测试函数（24项）：空键与 unknown/BLOCKED 保持、256边界、22项非法类型/超长/filters反例。
- `docs/evaluation/p2-h2-scenario-execution-v0_1.md` 仅补一句占位语义；v0.1/v0.2保管 schema、公共配方、manifest/金标及真实密文不改。

## 实际检查（开发自测）

| 检查 | 结果与证据 |
|---|---|
| 空键红例 | `evidence/red.txt`：1 failed/75 deselected，非空合成占位先可加载；改空串准确触发 `scenario_targets_invalid`。 |
| 初次专项 | `evidence/green-initial.txt`：75 passed/1 failed；加载已成功，新增断言误要求 safe_summary 输出原先省略的0计数，仅纠正测试预期，产品未再改。 |
| 最终专项 | `evidence/green.txt`：**76 passed，29.53秒，0 skip/xfail**；1项既有 Starlette/httpx 弃用警告。包含旧52项及新增24项，真实 CLI Mock 正常四库/首错停止均覆盖。 |
| 未解析语义 | 合成2个实体 unknown，空键前后 safe_summary 完全相等；unknown=2、实体/日期缺口各2、quality BLOCKED、runtime_axis_evidence_produced=false、release_ready=false；组合未解除硬失败未验证 block。 |
| 出站检查 | `evidence/network-guard.json`：76项全启 guard，external_attempts=0；3次 Windows asyncio 回环单列，非真实调用。 |
| 精确范围 | `evidence/r1-exact.diff` + `protection_check.py`：产品源码逐字节仅该条件变化；旧测试原字节为现文件前缀；执行契约只增一句。 |
| 保护 hash | `evidence/protection-before.json` / `protection-after.json`：21项保护件及12项公共语料 hash 不变；包含冻结元数据、两版schema、原manifest/source-map/配方/计划、旧报告/review、其余接线/评分源码、固定资金三件。 |
| 空白检查 | `git -c core.whitespace=cr-at-eol diff --check` exit0；新增文件由精确diff和实际pytest加载核验。 |

复跑环境：项目 `.venv/Scripts/python.exe -B`、`MKTKB_NO_DOTENV=1`，TEMP/TMP 固定本次 visualizations 的 `t207-temp/scenario-r1-dev` 独占目录，红/首绿/终绿分别使用新 basetemp。

```text
PYTHONPATH=docs/reports/OBS-EVAL/P2/T207-SCENARIO-R1/evidence
.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider -p r1_guard backend/tests/evaluation/test_p2_holdout_scenarios.py --basetemp <上述独占目录>/green-final
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/T207-SCENARIO-R1/evidence/protection_check.py
```

红例另加 `-k unresolved_empty_entity_key`。含 ASGI 的专项仅按已确认 socketpair 沙箱限制，使用命令级 require_escalated；未 skip/xfail 或改产品绕过。保护探针首次引用不存在的旧评分路径而失败，在任何快照写入前纠正路径；不属于产品失败。

## 遗留与停止点

未读取真实 H2/附件/保管会话/.env/凭据，未运行真实绑定、模型/服务、付费/预留、四轴分类、全仓或原346项链路；无stage/commit/部署/资金/GO变更，无子助手。

经理之前 `FAIL/scenario_targets_invalid` 实际证据未覆盖；本轮只证明合成接口兼容，不宣称真实冻结附件已加载成功。开发自测不替代全新独立验收或经理受控绑定。完整质量仍 BLOCKED，真实复测交另一个 AI 按另行授权执行；不进 T208/T209/T900。

交付后停止写入并暂停，待经理验收。
