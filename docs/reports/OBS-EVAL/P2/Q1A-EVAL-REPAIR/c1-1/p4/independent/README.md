# C1-P4 独立验收探针（`c1-1/p4/independent/`）

本目录是 **C1-P4 全新独立验收**的自建证据：合成 v2 合同 / v0.3 快照的构建器、9 支探针、
零出站守卫与机器可读输出。**不 import 开发测试模块、不复制其 fixture、不修改任何被测文件。**

## 运行方式（Windows / 仓内 venv）

```powershell
$env:PYTHONPATH = "<repo>\backend\src"
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONIOENCODING = "utf-8"
python probe_01_version_dispatch.py
python probe_02_redline_document.py
python probe_03_class_c.py
python probe_04_key_space.py
python probe_05_failclosed.py
python probe_06_counts_output.py
python probe_08_zero_call.py
python probe_09_tests.py
python probe_07_preservation.py      # 最后跑：保全基线
```

输出写入 `out/*.json`；`probe_09` 另写 `out/09-pytest.txt`（pytest 原始输出，
`-p no:cacheprovider`、仓外 `--basetemp`、`PYTHONDONTWRITEBYTECODE=1`，不在仓内留缓存/字节码）。

## 文件

| 文件 | 作用 |
|---|---|
| `harness.py` | 逐项记录器（checks/failures/verdict → JSON）；固定码提取（兼容 `AdapterError` 与 `RescoreError` 的 `.code`） |
| `synth.py` | 自建 v2 合同（30 题/4 runs/17 bindings/9 键 projection）与 v0.3 快照（15 键/9 使用层/3 候选层）构建器 |
| `netguard.py` | 自建零出站守卫（socket connect/connect_ex/create_connection/getaddrinfo/gethostbyname、http.client、httpx 传输层） |
| `probe_01_version_dispatch.py` | v1 拒绝、v2 不被 v1 常量收下、schema sha 钉扎（含逐字节反例） |
| `probe_02_redline_document.py` | M-C1P1-01：document 粒度目标 / uuid 键 / 文档行；doc_code 降级通道 |
| `probe_03_class_c.py` | M-C1P2-01：class C 六种形状一律 `empty_set_not_proven`；真空集才 pass |
| `probe_04_key_space.py` | 键空间：静态前缀/包含/模糊扫描、运行时矩阵、确定性、顺序依赖、R-ENT-1 复算保真 |
| `probe_05_failclosed.py` | 66 类结构化反例 + 全码 unknown→N/A 门 + 800 次确定性变异（含非标量枚举崩溃点） |
| `probe_06_counts_output.py` | 三公式、`basis` 不进 verdict、输出无 verified/threshold/release、provenance 无运行期 id |
| `probe_07_preservation.py` | 冻结 12/12、15 tracked modified、Q1a-1 38、R2 28、2086 外来 untracked、git 状态、新增前缀白名单 |
| `probe_08_zero_call.py` | 干净段 external=0、7 层正对照被拦并记账、不清账必报错、清账后通过 |
| `probe_09_tests.py` | 独立执行 43 项 + AST 质量（skip/xfail/恒真/固定码断言上下文/覆盖） |

## 边界

只用合成数据与仓库内公开契约文本；未读真实 H2 题面/标签/答案/私有密文/key/`.env`/保管会话；
未 stage/commit/push；未改任何既有文件（本目录与 `out/` 为唯一新增）。
`probe_07` 对 36 个命中敏感名模式（custody / `.fernet` / holdout-private）的基线文件**只跳过、不读取**，
并在输出里逐个列出，作为“本会话未验证”的显式残余。
