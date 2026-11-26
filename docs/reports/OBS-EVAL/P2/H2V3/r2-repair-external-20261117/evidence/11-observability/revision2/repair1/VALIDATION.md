# repair1 定向验证记录

本记录为开发自测，不替代独立验收。所有测试使用完全虚构输入；未读真实封存、私有 key、题答、计划或 binding。

## 独立探针复现

保留原独立探针与结果原字节。由于原探针固定写入独立验收的临时目录，复制到 `work/reproduce_before.py` 和 `work/reproduce_after.py`，只调整自身输出目录与加载路径；修后副本加载 repair1 的新 SAFE 工具。两次运行均使用项目 `.venv`、独占的新仓外合成密文目录，并由探针原有 55 秒 watchdog 限时。探针的 `platform._syscmd_ver` 合成替身仅阻止标准库平台信息探测启动 cmd，未替换产品检索或输出。

- 改前首次运行：退出码 1，53 pass / 17 unmet，与独立报告一致。初次结果由工具输出记录，但本轮复跑时误覆盖了本轮副本输出；独立报告和 `independent-acceptance/contracts/PROBE-RESULTS.json` 未被修改，仍保留原始 53/17。
- 为恢复可复核改前结果，之后以 `work/reproduce_before_exact.py` 在进程中加载本轮保存的原 capture 字节并运行旧 SAFE 工具：退出码 1，54 pass / 16 unmet。与原探针只差 `PREPARED_HELPER_FAULT_HARDENING`，这属于人为双故障加固，模块注入会影响 monkeypatch 对象身份；不能把此复跑说成原运行的完全重现。其余阻塞项仍复现。结果在 `probe-before/probe-results.json`。
- 改后运行 `work/reproduce_after.py`：退出码 1，67 pass / 3 unmet，结果在 `probe-after/probe-results.json`。剩余 `ANSWER_SINK_FAIL_FAULT_HARDENING`、`PREPARED_HELPER_FAULT_HARDENING` 是验收报告列为非强制的加固项；`SAFE_FAILED_SINK_CONTEXT_GATE` 仍按原探针直接调用旧式 payload-only 接口，不能识别 sink。repair1 完整上下文入口的真实 failed sink 正反例另由下列测试验证，不伪称原探针全绿。

运行形式（每次的 IO 目录为先检查不存在的独占新子目录；以下 `$io` 指本次新目录）：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 <本目录>/work/reproduce_before_exact.py $io
.\.venv\Scripts\python.exe -B -X utf8 <本目录>/work/reproduce_after.py $io
```

## 最终定向测试

工作目录为项目根：

```powershell
$w='docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/11-observability/revision2/repair1/work'
.\.venv\Scripts\python.exe -B -X utf8 -m pytest "$w/test_repair1.py" "$w/test_native_patch.py" backend/tests/observability/test_evaluation_capture.py backend/tests/evaluation/test_r2_observability_io_revision2.py backend/tests/evaluation/test_p2_evidence_io.py::test_turn_and_manifest_roundtrip_with_ciphertext_only -c backend/pyproject.toml -o 'pythonpath=backend/src' -q -p no:cacheprovider --tb=short --basetemp='C:/Users/dell1712/.codex/visualizations/2026/11/17/01a1e9ec-6a25-7d40-9c2d-fcba2ba67814/repair1-test-final-04'
```

退出码 0：19 passed、1 warning。覆盖角色合并、非法值与缺失、候选组合和 0/1/512/513 边界、旧 payload、真实 `CaptureSink` 失败、未封存、缺事件、坏计数、鉴权失败、合成 Fernet 加密读回、前置未执行与未知分离。上下文合成 IO 节点对 socket connect/connect_ex/create_connection/getaddrinfo、httpx 同步 transport 和 subprocess.Popen 安装守卫：正常阶段账本 0，网络与子进程正对照各拦截 1 次。该节点只证明所列拦截通道，不宣称全系统审计。

首次测试因测试脚本定位项目根目录的层级写错，收集失败 exit 2；修正测试装配后通过。此前新工具开发期间的独立验证记录和失败未删。没有全量测试，未重新执行已充分诊断的 HTTP 挂起节点或 19 场景矩阵。

## 原生行尾包装验证

`work/test_native_patch.py` 在独立临时目录对 increment 和 cumulative 两套包装分别做检查、正向应用、反向应用，逐文件比较原生字节；并验证输入哈希不符时拒绝写入。最终组合测试中两项通过。另在独占仓外临时树通过 CLI 实际执行累计补丁：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 <本目录>/work/native_patch.py --root <独立临时树> --patch <本目录>/patches/cumulative-source.patch --manifest <本目录>/patches/cumulative-source.json
.\.venv\Scripts\python.exe -B -X utf8 <本目录>/work/native_patch.py --root <独立临时树> --patch <本目录>/patches/cumulative-source.patch --manifest <本目录>/patches/cumulative-source.json --apply
.\.venv\Scripts\python.exe -B -X utf8 <本目录>/work/native_patch.py --root <独立临时树> --patch <本目录>/patches/cumulative-rollback.patch --manifest <本目录>/patches/cumulative-rollback.json
.\.venv\Scripts\python.exe -B -X utf8 <本目录>/work/native_patch.py --root <独立临时树> --patch <本目录>/patches/cumulative-rollback.patch --manifest <本目录>/patches/cumulative-rollback.json --apply
```

四次均输出 `OK 4`、退出码 0；回退后四个文件 SHA-256 均与 `.tmp-r2-obs-baseline/` 字节相等。仅在独立临时树应用；主树未应用回滚。包装默认只检查，必须显式 `--apply` 才写入；其逐文件替换不是多文件事务。各补丁清单与工具 SHA 见 PROTECTION.md。

结束时分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，39 tracked 修改、暂存为空。中断恢复后定点重核本轮产品文件及关键工具 SHA 与保护记录一致；未发现同范围变化，不据此声称所有旧文件均已逐字节重验。
