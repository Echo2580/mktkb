# P2-T202 报告：H2 受限数据加载器（开发自测）

- provider=wb、model=cn:deepseek-v4.1-flash、reasoning_effort=max（派发方指定）。
- 结论：T202 **开发自测完成**；未自验为独立通过、未派发验收、未开工 T203、**零真实调用**；
  未接触真实 H2/密钥，未读 .env / H1 / `D:/mktkb-p2-holdout`。
- 分支 `codex/p2-e2e`，HEAD `3afe8c3`；**未 commit/push**、未切分支、未建 worktree；
  `dataset.py` **0 行修改**（未新增公开包装，直接复用私有逐行校验）。

## 1. 交付清单（全部为新增文件）

| 文件 | 类型 | SHA-256 前 16 | 字节 |
|---|---|---|---|
| `backend/src/mktkb/evaluation/p2_dataset.py` | 新增 | `5ddb3d4d3cb52a33` | 41467 |
| `backend/tests/evaluation/test_p2_dataset.py` | 新增 | `a7e390a390684ff3` | 45222 |
| `docs/evaluation/p2-dataset-v0_1.md` | 新增 | `fdc17ff2c825de90` | 15024 |
| `docs/reports/OBS-EVAL/P2/T202/report.md` | 新增 | 报告自身不写自身 hash | — |
| `evidence/verify.json` | 证据 | 完整 hash/字节见该文件 `files[]` | — |
| `evidence/coverage-map.json` | 证据 | 同上 | — |
| `evidence/synthetic-fixture.json` | 证据 | 同上 | — |
| `evidence/pytest-p2-t202.log` | 证据 | 同上 | — |

未改其它文件；工作区其它未跟踪文件（.claude 协调文档、docs/面试/、任务书、同期保管方新增的
`docs/evaluation/p2-holdout-v2.manifest.json` 与 `P2-T202-verify.md`）保持原样（非本包产出）。
测试临时目录 `backend/.pytest-tmp/` 已在 .gitignore 内；一次性的探针脚本已删除，无残留。

## 2. 接口与错误码

- 冻结接口：`load_p2_dataset(manifest_path: Path|str, *, visibility: str) -> P2Dataset`；
  `visibility` 必须显式、只接受 `"public"` / `"holdout"`（无默认，非关键字传入直接 TypeError）。
- **public**：只读 manifest（repo-safe 元数据：版本/题数/分层/四个 sha256/turn_stats）；
  路径落在 `MKTKB_P2_HOLDOUT_ROOT` 内直接 `visibility_root_violation`、零读取；
  返回 `cases=()`、`labels={}`，`repr` 不含题目/答案。
- **holdout**：`MKTKB_P2_HOLDOUT_ROOT` + `MKTKB_P2_HOLDOUT_KEY_FILE` 注入；manifest 必须
  位于 root 内；校验顺序 = 密文 sha256 -> Fernet 解封 -> 明文 sha256 -> 逐行 holdout schema
  -> 题数/分层/label_version/唯一 id/集合相等 -> 轮数/turn_stats -> 合并 `CaseSpec` 并
  `validate_case`；返回 `cases`（30 条）与 `labels` 映射（只读）+ `metadata_mismatch_count`。
- 错误：`P2DatasetError`（`ValueError` 子类，族码 `P2_DATASET_INVALID`，`.reason` +
  `.detail`），**46 个稳定原因码**分三组（manifest 20 / holdout 路径-key-解封 13 / 数据契约 12 + 1），
  逐条写入 `docs/evaluation/p2-dataset-v0_1.md` §6；错误只带字段名/行号/计数/摘要。
- 复用 `dataset.py`：`CaseSpec` / `validate_case` / `HoldoutPolicy` / `_question_row` /
  `_label_row`（H2 行仍是 questions 13 键、labels 11 键、suite/split=`"holdout"`）。
  未改 dataset.py 的常量/校验/行为，因此未跑 P1 holdout 旧测试；改共享代码前已确认无变更。

## 3. 任务书 §8 T202 四条

1. **开发用合成小型题集实现加载器与受限入口**：`test_holdout_decrypts_and_merges`、
   `test_holdout_reads_exactly_four_files`、`test_holdout_writes_no_plaintext_to_disk`、
   `test_holdout_is_deterministic`、`test_metadata_mismatch_is_counted_not_fatal`。
2. **缺元数据、错 hash/重复 id/题数或分层不符/多轮缺轮必须拒绝**：`test_manifest_*`（14 个）、
   `test_ciphertext_tamper_is_rejected` / `test_plaintext_sha_mismatch_is_rejected`、
   `test_duplicate_case_id_*`、`test_question_row_count_mismatch`、`test_data_strata_mismatch`、
   `test_multi_turn_stratum_needs_two_turns`、`test_turn_stats_must_match_the_data`。
3. **H2 默认只产聚合、题干/标签不进仓库**：契约 §7 写明 T203 trace/产物只带
   `manifest_sha256`/版本/计数，产物不落明文；本包代码不写任何文件，测试后递归扫描
   `tmp_path` 证明无明文（`test_holdout_writes_no_plaintext_to_disk`）。
4. **质量目标与分层分母**：加载器冻结 30 题与 10/5/5/5/5，T206 准入直接引用
   `P2_CASE_COUNT` / `P2_STRATA`。

## 4. 开发提示词测试清单（→ `evidence/coverage-map.json` 13 组）

public 不打开封存 root（读探针 + root 内拒绝）、holdout 解密+合并、缺 env/key/文件、坏 key、
密文/明文 sha 不符、case_count/strata/label_version 不符、重复 case_id、questions 含答案字段、
labels 缺/多 case、turns/locator 非法、多/缺字段拒绝、错误信息不含题干答案、契约文档同步——
每项都有对应测试函数，64 个测试函数全部通过。

## 5. 实际命令与结果

    .\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_p2_dataset.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t202

→ **64 passed, 1 warning**（耗时见日志）（原始输出：`evidence/pytest-p2-t202.log`；
唯一 warning 是仓库既有 `starlette.testclient` 弃用提示，与本次改动无关）。
**未执行**：全仓测试、其它包测试、浏览器、真实 provider/OCR/H2；理由：任务书禁止默认重跑，
且本包未触碰共享代码。若经理要求，可加跑 `backend/tests/evaluation/test_dataset.py` 作对照。

## 6. 隔离自证（全部在 pytest --basetemp 的 tmp_path）

- public 读探针：`Path.read_bytes` 只命中 1 次（传入的 manifest）；env 指向真实/存在的 root
  时仍然 0 次访问 root 内文件；root 内 manifest → 拒绝且 reads 为空。
- holdout 读探针：恰好 4 次（manifest、key、questions.fernet、labels.fernet），无其它文件。
- 明文不落盘：load 后递归扫描 tmp_path，合成题干/跟进/答案标记均不出现；root 目录仍只有
  manifest + 两个密文。
- 错误文本：7 类失败路径（答案字段泄漏/缺轮/labels 非法/manifest 错/明文 sha/key/解封）的
  `str`、`detail`、`repr` 均不含三个合成标记；`P2Dataset` 与 `P2Manifest` 的 `repr/as_dict` 也不含。
- 未联网、未装依赖、未读 .env / H1 原件 / 真实 H2、未访问 `D:/mktkb-p2-holdout`。

## 7. 限制与需协调事项（请经理核，尤其 T206 准入）

1. **turn_stats 口径已冻结，且与保管方 manifest 对齐**：单题轮数 = `len(turns)`（`turns` 非空时），
   否则 1。仓库内已出现的 `docs/evaluation/p2-holdout-v2.manifest.json`（**非本包产出，未读题干、
   未修改**）用 public 路径加载**通过**：30 题 / 10-5-5-5-5 / `turn_stats` = 25-4-1（合计 36、
   max 3），与本口径一致（该文件 sha256 前 16：`8874985ef8f4aacc`，可能随保管方更新而变化）。
   holdout 路径未跑（无 key、无权限、也不允许）；若 manifest 后续变更，T206 前按同一口径复核。
2. **key 文件格式**：裸 44 位 url-safe base64 Fernet key（允许行尾换行）；带前缀/多行/引号会
   `holdout_key_invalid`。本包未实现封存工具（保管方职责），无法替其生成 key。
3. **依赖**：`cryptography 50.0.2` 已在 .venv，但**未写入** `pyproject.toml`（本包不改依赖）；
   缺依赖时 `crypto_unavailable` fail closed。若 T206 需可移植，建议在评测依赖锁中声明版本。
4. **labels 的 locator/不透明 id 非法**报 `holdout_case_invalid`（dataset.py 的 `_label_row`
   只校验“对象列表”，结构校验在合并后的 `validate_case`）；同样 fail closed，已写入契约 §5/§6。
5. **未检查 symlink**：root/key 由操作者注入，内容安全由 sha256 保证；部署侧路径由 T206 核。
6. **public 读一个环境变量做越界判断**（只读变量、不打开文件）；未配置 root 时无法识别封存
   manifest 路径，但 public 只读该 manifest（repo-safe 元数据），不打开密文/key/root 内其它文件，
   也不返回题目。
7. **dataset_version / label_version 以 manifest 为权威**（代码只校验 token 与行内一致），
   未被冻结成常量；T203 必须把它们与 `manifest_sha256` 一起写进 run 身份。
8. 复用 `dataset.py` 私有逐行校验（`_question_row` / `_label_row`）：若 P1 侧后续改规则，
   H2 加载器自动跟随；本包用合成夹具锁定行为，未能锁死“函数签名不变”。

## 8. 证据入口（4 个）

1. `evidence/verify.json`——文件 hash/字节、分支与 HEAD、接口签名、46 个原因码、文档同步结果、
   Python/cryptography 版本、测试命令与结果、工作区状态、零真实调用声明。
2. `evidence/coverage-map.json`——13 组需求 → 测试函数映射 + 3 项有意未覆盖说明。
3. `evidence/synthetic-fixture.json`——合成 30 题/分层/35 turn 的夹具形状、合成标记、封存布局、
   “明文不落盘”结论（不含任何真实题目）。
4. `evidence/pytest-p2-t202.log`——指定命令原始输出（64 passed）。
