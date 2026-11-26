# repair1 范围、保护及补丁包装独立复验

主人，本席位结论：`SCOPE=PASS`、`PROTECTION=PASS_LIMITED`、`NATIVE_EOL_PACKAGING=PASS`。repair1 已补齐上轮指出的补丁可操作性缺口，接收方式是经本次独立执行验证的 EOL-aware 工具步骤；不是宣称原裸 patch 的默认 Git 应用通过。HTTP 保留 `INCOMPLETE`，本轮未重跑。本结论不替其他席位的 SAFE、IO 或真实索引验收下判定，也不改变真实 R2 4/5、C29 根因 unknown。

## 1. 实际执行与范围

项目根目录执行：

```powershell
& .\.venv\Scripts\python.exe -B -X utf8 'docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/11-observability/revision2/repair1/independent-acceptance/scope/scope_recheck_probe.py'
```

退出码 0。独立探针没有调用开发测试的断言；它调用交付 CLI，在新建的 `.tmp-r2-obs-acceptance-scope-repair1/` 内建立独立临时树并核对字节。证据为同目录 `SCOPE-RECHECK-EVIDENCE.json`。

- increment：仅 `backend/src/mktkb/observability/evaluation_capture.py`，1 hunk、增加 7 行候选组合检查。改动位于既有 capture 清洗器，条件为 direct-RAG scope 且存在 candidate_count；没有进入产品问答/检索/渲染业务。
- cumulative：仅 conversations/service.py、evaluation_capture.py、rag/answer.py、rag/retrieval.py，16 hunks。与上轮相比，新增差异只有上述 capture hunk；其他三个产品文件字节与上轮 after 一致。
- query.py、facts.py、qa/service.py 的保护 SHA 与上轮相同。累计严格重建可以复现当前四文件，原始 baseline 中未被补丁涉及的业务字节保持。
- 所有补丁应用仅发生在独立临时树。没有在主工作树应用 source/rollback，没有源码修改、Git 写、HTTP 重跑、系统/依赖/网络例外更改或真实外部调用。

## 2. 双向 CLI 与逐字节往返

输入基线独立核对：

- increment 输入 capture 同时取自 repair1/baseline/evaluation_capture.py.before 与本席位上轮独立重建并保留的 rev2 after；二者原字节一致，SHA 为 `7429be11226916419d8061241b6284b6b9b2a0e8467cb8aae37646d81a1967c1`。
- cumulative 输入为原 `.tmp-r2-obs-baseline/` 的四文件开工字节，使用上轮已经核验的脏树基线，不使用 HEAD。
- repair1 当前 capture SHA 为 `24a66783fb622164cf5c22ab79cffb211f7b44f7d97e4a9c6590e1cc7bd4b675`；其余六个源码摘要与上轮相同。

每套均实际执行如下四步，`<tree>` 均为本席位独立临时树，`<prefix>` 分别为 increment/cumulative：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 <repair1>/work/native_patch.py --root <tree> --patch <repair1>/patches/<prefix>-source.patch --manifest <repair1>/patches/<prefix>-source.json
.\.venv\Scripts\python.exe -B -X utf8 <repair1>/work/native_patch.py --root <tree> --patch <repair1>/patches/<prefix>-source.patch --manifest <repair1>/patches/<prefix>-source.json --apply
.\.venv\Scripts\python.exe -B -X utf8 <repair1>/work/native_patch.py --root <tree> --patch <repair1>/patches/<prefix>-rollback.patch --manifest <repair1>/patches/<prefix>-rollback.json
.\.venv\Scripts\python.exe -B -X utf8 <repair1>/work/native_patch.py --root <tree> --patch <repair1>/patches/<prefix>-rollback.patch --manifest <repair1>/patches/<prefix>-rollback.json --apply
```

| 套装 | 默认前向检查 | 显式前向应用 | 默认反向检查 | 显式反向应用 | 字节结果 |
|---|---|---|---|---|---|
| increment | exit 0，OK 1 | exit 0，OK 1 | exit 0，OK 1 | exit 0，OK 1 | rev2 → repair1 → rev2 全等 |
| cumulative | exit 0，OK 4 | exit 0，OK 4 | exit 0，OK 4 | exit 0，OK 4 | 原 baseline → repair1 → 原 baseline 全等 |

两套的默认检查前后，临时树文件集合及 SHA 全等；只有明确 `--apply` 才写。正向应用后与当前产品文件逐字节比较，反向后与各自原输入逐字节比较；临时树中额外放置的保护文件也保持。独立探针另用本席位上轮自写的严格 hunk matcher 重建 source，再与当前源码核对，结果一致；没有依赖 `--ignore-space-change` 或开发测试声称。

完整逐文件输入、输出、回退 SHA 和每次 CLI exit/output 在机器证据内。

## 3. 绑定及写前拒绝

四组 patch/JSON 均独立核对以下三层关系：patch 当前 SHA 等于 manifest.patch_sha256；patch 当前 SHA 等于 repair1 PROTECTION；manifest 当前 SHA 等于 repair1 PROTECTION。四组均 true。工具 SHA 为 `0412731057f45a0d028b33292cfd04d54d5e8a6dac4812b7e0b9c149ecbc4959`，与 PROTECTION 一致。

源码定点复核：native_patch.py:61–76 在写入前读取并验证补丁 SHA、路径集合、root 内目标、每个输入 hash、精确旧行上下文、hunk 行数及每个重建输出 hash；所有目标先进入 staged。77–84 才按文件写临时文件并 replace；89–91 的 CLI 默认 apply=false，只有 `--apply` 才进入写循环。清单本身应作为已核对的可信交付使用；工具的 patch SHA 校验不是清单来源的认证。本席位以 PROTECTION 逐项校验该来源绑定。

独立执行以下 8 项明确带 `--apply` 的反例：

| 反例 | CLI exit | 固定错误码 | 目标及临时文件集合未变 |
|---|---:|---|---|
| manifest.patch_sha256 错误 | 1 | patch_hash | true |
| 补丁字节篡改，未更新清单 | 1 | patch_hash | true |
| 累计最后一个目标输入字节错误 | 1 | before_hash | true |
| 累计最后一个输出预期 hash 错误 | 1 | after_hash | true |
| 最后文件 hunk 上下文增加空格，同时更新补丁 SHA | 1 | hunk_context | true |
| manifest 路径集合缺项 | 1 | path_set | true |
| hunk 行数错误，同时更新补丁 SHA | 1 | bad_hunk_count | true |
| 回滚的最后一个目标输入字节错误 | 1 | before_hash | true |

最后文件的失败发生在前面有效目标已完成内存重建之后，仍没有部分写入，证明验证失败不会先提交此前目标。这不是运行时多文件原子事务证明：逐文件 replace 时若发生后续磁盘/权限错误或并发外部修改，工具没有跨文件事务回滚。本次按授权保留该明确限制，不要求或实施额外事务重构。

## 4. 保护证据的可证范围

独立可追溯到本席位上轮记录的 5 项历史哈希检查全部相等：原 SOURCE.patch、原 ROLLBACK.patch、本席位原 SCOPE-HTTP-VERDICT.md、原 scope_probe.py、原 http_probe.py。上轮 `final-integrity.json` 和 `scope-evidence.json` 仅作为只读核对来源，没有更新。

原六交付、原 SAFE 脚本、本席位原报告/探针/JSON 及合同验收席位的原探针/报告/结果摘要，在本轮开始时定点采样并于结束重算，均未变；全部 SHA 记录在机器证据。这里的本轮前后相等不能单独证明从原开发开工以来未改。

另据经理提供的定点哈希复核，原六交付加原 work/safe_plan_projection.py 共 7 件，与经理此前最初实测 SHA 比对 mismatch=0。该条明确是经理提供的保护证据；不冒称本席位拥有这 7 件全部的旧开工快照。

没有所有旧报告、旧脚本、封存等的完整开工哈希，故 `PROTECTION=PASS_LIMITED` 仅指上述明确证据覆盖范围。没有以 mtime 或开发自述扩展为全旧证据保护。

## 5. 接收结论及停止点

本席位上轮的“裸补丁默认应用失败”事实与原报告保留；repair1 新增经独立 CLI 和哈希验证的原生 EOL 操作步骤，已解决本席位提出的包装阻塞。因此可接收本次范围/补丁包装返工，不表示整个 T-R2-OBS、R2 或 T207 已通过。

HTTP 上轮原生 socketpair/asyncio/TestClient 超时、元数据诊断替身与原环境区别，以及未覆盖业务 HTTP 的限制，仍以原 SCOPE-HTTP-VERDICT.md 为准，状态 `INCOMPLETE`。本轮没有重复实验、修改网络守卫或推测更深环境根因。其他验收席位继续负责其授权范围，本席位完成收口停止。
