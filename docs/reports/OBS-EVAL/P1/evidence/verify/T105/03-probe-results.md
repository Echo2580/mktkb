# T105 独立 HTTP 探针结果（verify/T105/03）

- 脚本：`02-probe.py`（独立编写，未复用 `backend/tests/{rag,integration}/test_p1_t105_anaphora_field.py`）。
- 路径：`create_app` + `TestClient` 真实 HTTP 产品入口（上传→worker→发布→`POST /conversations/{id}/messages`），可控 `EchoGateway` 只回显证据；隔离临时 SQLite/数据目录；零真实模型/embedding/rerank/OCR，未读 `.env`/Holdout。
- 夹具：临时 xlsx，8 列（标识/门店/物品/别名/位置/数量/参考供价/规格型号）× 12 行（12 家门店的“宣传海报”），用于同时验证位置唯一性、枚举分页（page_size=10）和整条倾倒检测。原始观察：`backend/.pytest-tmp/T105-verify/probe-results.json`。
- 断言口径：只看响应 JSON 的 `kind/text/sources/pagination`；未使用 12 字段整条渲染假设（夹具 8 列，倾倒时 8 列全部出现即判失败）。

## 当前树（`2306aaa`）结果：64/70 checks passed，6 failed

| 场景 | 上文 → 本轮 | 当前树实际 | 判定 |
| --- | --- | --- | --- |
| S1b | 城西店宣传海报在哪里 → 那个海报呢 | `answer`：`根据资料，城西店的宣传海报的位置：C区2号货架第一层。`（27 字，无规格/价格/数量/标识，无分页，sources=1） | PASS |
| S2b | 数量是多少 → 那个海报呢 | `answer`：`…的数量：20。`（27 字，未问值 0） | PASS |
| S3b | 参考供价是多少 → 那个海报呢 | `answer`：`…的价格：2.6 元。`（27 字，未问值 0） | PASS |
| S4b | 规格型号是什么 → 那个海报呢 | `answer`：`…的规格：A2 铜版纸 157g。`（29 字，未问值 0） | PASS |
| S5 | （无上文）那个海报呢 | `clarification`：`请问要查询宣传海报的哪项信息？可指定位置、数量、规格、价格等。`；无字段值，sources=[] | PASS |
| S6 | 把宣传海报都列出来 | `answer` + `pagination={page:1,total:12,returned:10,has_more:true,next_page:2}` | PASS |
| **S7** | 同上 → **那个海报的第2页** | **`clarification`**：`请问要查询宣传海报的哪项信息？…`，`pagination=null` | **FAIL（B1）** |
| S7b | 同上 → 第2页（无指代） | `answer` + `pagination={page:2,total:12,returned:2,has_more:false}`，`共 12 条，当前第 2 页显示 2 条…` | PASS |
| S8 | 城西店海报在哪里 → 把那个海报的位置列出来 | `answer` + `pagination={page:1,total:1}`，列位置 | PASS |
| S9 | 同上 → 那个海报的全部信息 | `answer` + `pagination={page:1,total:1}`，但只列继承的位置（与基线一致） | PASS（分页保留；语义待确认） |
| S10 | 城西店海报在哪里 → 刚才那个呢 | `answer`：只答位置（27 字） | PASS |
| S11 | 同上 → 前面那个呢 | `answer`：只答位置（27 字） | PASS |
| S12 | （无上文）那个呢 | `clarification`：`请说明您指的是哪个物品、门店或哪份资料。`；无字段值 | PASS |
| S13 | 城西店海报在哪里 → 这个呢 | `answer`：只答位置（27 字） | PASS |
| S14 | 同上 → 那家呢 | `answer`：只答位置（27 字） | PASS |
| **S15** | 城西店海报在哪里 → 那个海报的打印材质呢 | `answer`：576 字，**8 条记录 × 8 个字段**（8 次“标识：”），含 QF02/城西店/C区2号货架第一层/20/2.6/A2 铜版纸 157g 等未问值 | **FAIL（B2）** |
| **S16** | 同上 → 那个海报的陈列要求呢 | 同 S15：576 字，8 条 × 8 字段 | **FAIL（B2）** |
| **S15b** | 同上 → 那个海报的规格型号呢 | 同 S15：576 字，8 条 × 8 字段（连“规格”也未按字段作答） | **FAIL（B2）** |
| S15c | 城西店海报（标识：QF02）在哪里 → 那个海报的规格型号呢 | `answer`：`根据资料，城西店的宣传海报的规格：A2 铜版纸 157g。`（29 字） | PASS |

## 与 T105 前基线 `17c0e63` 的逐场景对照（同一探针，`PYTHONPATH=<worktree>\backend\src`；已打印 `mktkb.__file__` 指向基线副本）

| 场景 | 基线 `17c0e63` | 当前 `2306aaa` | 变化 |
| --- | --- | --- | --- |
| S1b 那个海报呢（上文问位置） | `answer`，576 字，8 条 × 8 字段 | 只答位置 27 字 | **修复** |
| S5 无上文 那个海报呢 | `answer`，576 字，8 条 × 8 字段 | `clarification`，无字段值 | **修复** |
| S7 枚举后 那个海报的第2页 | `answer` + `page=2`（266 字） | `clarification`，无分页 | **回退（B1）** |
| S7b 枚举后 第2页 | 未运行（脚本加入前） | `page=2` | — |
| S10 刚才那个呢 | `not_found`（15 字） | 只答位置 27 字 | **修复** |
| S11 前面那个呢 | `not_found`（15 字） | 只答位置 27 字 | **修复** |
| S12 那个呢（无上文） | `clarification`（18 字，文案不同） | `clarification`（20 字） | 等价 |
| S13 这个呢 | `service_error`（16 字） | 只答位置 27 字 | **修复** |
| S14 那家呢 | `not_found`（15 字） | 只答位置 27 字 | **修复** |
| S15/S16 新内容追问 | `answer`，576 字，8 条 × 8 字段 | 同基线（576 字，8 条 × 8 字段） | **未修（B2，非本包引入）** |

## 结论

- T105 的主目标（纯指代 `那个海报呢`：继承唯一字段只答该字段；无字段/无源澄清）在当前树成立，且相对基线修复了 7 个场景（S1b/S5/S10/S11/S13/S14 等）。
- 但 S7 是 T105 分支引入的**分页回退**；S15/S16/S15b 表明“带新内容”的指代追问仍走 legacy 整条倾倒（基线已有，report §5 声称“不会再整条倾倒”不成立）。
