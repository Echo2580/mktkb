# P2-T207-FIX-H2PURGE 开发报告（CLI live 未把 holdout purge 开关传给 run_live_p2）

## 根因
`cli.py::_cmd_p2_run` 对 `--visibility holdout` 置 `purge_traces=True`，也传给了 `_run_p2_live`，
但 `_run_p2_live` 调 `run_live_p2` 时没转发该开关；`run_live_p2` 本身也没有这个形参，于是
`build_live_adapter` 用 `ProductEvalAdapter` 默认值 `purge_traces_on_close=False`，
`p2_runner.py:779` 在首个发送之前以 `holdout_requires_purge` 拒绝（0 发送、账本未变）。

## 改动（3 个文件，全部最小接线，无语义放宽）
- `backend/src/mktkb/evaluation/p2_live.py`：`run_live_p2` 增 `purge_traces_on_close: bool = False`
  形参并转交 `build_live_adapter`（默认值不变，与既有签名对齐）。
- `backend/src/mktkb/evaluation/cli.py:729`：`_run_p2_live` 转发 `purge_traces_on_close=purge_traces`。
  public 分支 `purge_traces=False`，live 行为不变。
- `backend/tests/evaluation/test_p2_live_wiring.py`（§14，只增）：3 组用例（5 个 case）。
  未改账本/预算/GO/fixtures/评分/业务代码，未加 skip/xfail，未 commit。

## 测试（零真实调用）
- CLI holdout live：monkeypatch `p2_live.run_live_p2` 捕获 kwargs（替身返回伪造 result/build，
  `p2_dataset.load_p2_dataset` 用同形 holdout 视图）→ 断言 `purge_traces_on_close is True`、
  dataset.visibility=holdout。
- CLI public live：同一路径断言 `purge_traces_on_close is False`（行为不变）。
- `run_live_p2 → build_live_adapter` 形参对齐：True/False/缺省（缺省仍是 False）；
  截停在装配处（`_StopBuild`），不构造适配器、不出网。
- 负例保留：`test_p2_runner.py::test_holdout_without_purge_is_refused_before_any_work`
  原样通过（holdout + purge=False 仍在发送前拒绝，缺省 False 保证该规则可达）。
- 反证（evidence/02）：临时移除 cli.py 的转发行 → 两个 CLI 用例以
  `KeyError: 'purge_traces_on_close'` 失败（已恢复，文件逐字节一致）。
- 命令：`pytest backend/tests/evaluation/test_p2_live_wiring.py
  backend/tests/evaluation/test_p2_runner.py -q -p no:cacheprovider
  --basetemp backend/.pytest-tmp/p2-t207-fix-h2purge` → **68 passed**（evidence/01）。
  另跑 `test_p2_holdout_scorecard.py + test_p2_live_request_ceiling.py` → 27 passed。

## 限制
- 本次只证明"开关被正确转发到装配层"，未做真实 live 发送验证（按要求零真实调用）。
- H2 真实 run 仍受 GO/预算/账本/环境真实准入约束；本修复不改变任何门禁口径。
