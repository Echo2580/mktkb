# T114 验收证据 01：pytest 复跑

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

cwd = `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；每个命令前
`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`；同一时间只跑一套 pytest。

## A. 本包（新增安全/负例/文档测试）

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_routes_security.py `
  -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t114v-pkg
```

```text
62 passed, 1 warning in 17.56s
```

- 仅 1 个既有 `StarletteDeprecationWarning`（fastapi/testclient），非本包引入。
- 收集数 62 与参数化断言一致；无 `pytest.mark.skip` / `xfail`。

## B. observability 目录

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability `
  -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t114v-obs
```

```text
352 passed, 1 warning in 46.13s
```

## C. 全量

跑前空闲内存：`(Get-Counter '\Memory\Available MBytes')` = **3297 MB**（≥2GB）。

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests `
  -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t114v-full
```

```text
1920 passed, 1 warning in 473.84s (0:07:53)
0 failed / 0 error
```

- 全量包含本包 62 条；1858（T113 基线）+ 62 = 1920。
- 未触发 handoff 所列既有 flake（`test_g08_short_budget...`、
  `integration/test_lifecycle.py::test_concurrent_publish_and_global_revision_cas[v05]`），
  因此无隔离复跑记录。
- 唯一 warning 与 A/B 相同，为既有 Starlette 弃用提示。
