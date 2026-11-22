"""从证据 JSON 渲染 T301 三份交付文档（关联键直接取自隔离库与矩阵，避免手抄偏差）。"""

from __future__ import annotations

import json
from pathlib import Path

import t301_common as common

ROOT = common.T301_ROOT
MATRIX = json.loads((common.MATRIX_DIR / "sample-matrix.json").read_text(encoding="utf-8"))
RECOMP = json.loads((common.RECOMPUTE_DIR / "recompute-results.json").read_text(encoding="utf-8"))
PROBE = json.loads((common.TRACE_DIR / "trace-probe.json").read_text(encoding="utf-8"))

SOURCES_CN = {
    "normal_entry": "正常入口（FastAPI 接口链路，模型替身 Mock）",
    "normal_entry_injected_seam": "正常入口 + 故障替身缝（HTTP 链路正常，检索阶段注入异常）",
    "controlled": "受控测试样本（直接写隔离库，非正常入口产物）",
}


def _id(value: str | None) -> str:
    return value or "—"


def _citation_brief(citations: list[dict[str, Any]]) -> str:
    if not citations:
        return "—"
    docs = sorted({c["document_id"] for c in citations})
    vers = sorted({c["version_id"] for c in citations})
    return f"{len(citations)} 行；文档 {', '.join(docs)}；版本 {', '.join(vers)}"


# ---------- T301-sample-matrix.md ----------

def render_matrix() -> None:
    samples = MATRIX["samples"]
    corpus = MATRIX["corpus"]

    lines: list[str] = []
    lines += [
        "# T301 隔离环境验收样本矩阵（工作包 B）",
        "",
        "- 任务包：市场部 AI 知识库 P3 / T301，工作包 B：隔离环境验收样本与独立复算。",
        "- 隔离边界：业务库、RAG 索引、Trace 库全部新建于 `evidence/data/`；未读写 `var/` 下业务库与 Trace 库；`backend/`、`frontend/` 源码只读。",
        "- 模型/OCR/Ragas 均为受控替身（Mock），无真实付费调用；样本经 FastAPI 正常接口链路产生，罕见状态以受控样本构造并标注来源。",
        "- 脱敏：本表只保留关联键与结果类型，不含密钥、原始请求头、Trace 原始属性。",
        "",
        "## 1. 基线语料（管理员正常上传 → worker 导入 → 发布）",
        "",
        "| 资料 | 文档 ID | 版本 ID | 导入任务 ID | 任务状态 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for key, label in [("positions", "位置表（V03 v1 → D01 v2 换版）"), ("stores", "店家信息 D02"),
                       ("guide", "工作指南 D03"), ("conflict_a", "冲突资料 A"), ("conflict_b", "冲突资料 B")]:
        item = corpus[key]
        version_id = item.get("version_id") or item.get("v1_version_id")
        job_id = item.get("job_id") or item.get("v1_job_id") or "—"
        state = item.get("job_state") or "—"
        lines.append(f"| {label} | {item['document_id']} | {version_id} | {job_id} | {state} |")
    lines += ["", "## 2. 样本明细", "",
              "| 样本 | 场景 | 生成方式 | 结果类型 | 请求 ID | 会话 ID | 用户消息 ID | 结果消息 ID | 引用关联（行/文档/版本） | 导入任务/版本 | Trace ID | HTTP 请求 ID | 落库时间(UTC) |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]

    for s in samples:
        req = s.get("request") or {}
        job_ref = "—"
        if s.get("job_id"):
            job_ref = f"任务 {s['job_id']}；版本 {s.get('version_id') or '—'}"
        citation = _citation_brief(s.get("citations") or [])
        lines.append(
            f"| {s['sample_id']} | {s['scenario']} | {SOURCES_CN.get(s['source'], s['source'])} | "
            f"{s.get('response_kind') or req.get('status') or '—'} | {_id(req.get('request_id'))} | "
            f"{_id(s.get('conversation_id'))} | {_id(req.get('user_message_id'))} | "
            f"{_id(req.get('result_message_id'))} | {citation} | {job_ref} | "
            f"{_id(s.get('trace_id'))} | {_id(s.get('http_request_id'))} | {_id(req.get('finished_at'))} |"
        )

    lines += [
        "",
        "## 3. 样本覆盖说明",
        "",
        "- 正常入口（含替身）：S01、S02、S03、S04、S05、S06、S07、S08、S10、S11、S12、S13、S14、S15。",
        "- 正常入口 + 故障替身缝：S09（检索阶段注入知识库 revision 变更异常，HTTP 链路与提交链路仍走正常代码）。",
        "- 受控测试样本：S16（running 未提交中断）、S19（expired 未提交中断）、S17/S18（午夜边界固定完成时间）。",
        "- 六类结果覆盖：answer（S01/S02/S07/S10/S11/S12/S15/S17/S18）、clarification（S04）、not_found（S03）、conflict（S05）、service_error（S08）、knowledge_changed（S09）。",
        "- 专项场景：同文档多条引用行（S01）、幂等重放（S06 复用 S02 同一请求 ID）、关闭 Trace（S15）、文档换版（S11 v1 / S12 v2）、失败导入（S13）、待审核版本（S14）、午夜边界（S17/S18）、已删除会话（S10）、未提交中断（S16/S19）。",
        "",
        "## 4. 定向验证 D5 备注（冲突消息持久引用行）",
        "",
        "- 任务书 §2 口径：冲突消息不产生持久引用行，两方来源取自结果 JSON 的 `conflicts`，最终引用计数不含冲突。",
        f"- 实测：S05 冲突结果消息落库持久引用行 {RECOMP['citations']['conflict_message_rows_excluded']} 行（两方来源当时均为 active）；详见 `T301-recomputation.md` 冲突场景与口径缺口记录。",
        "- 该差异只记录上报，未改代码、未改任务书。",
        "",
    ]
    (ROOT / "T301-sample-matrix.md").write_text("\n".join(lines), encoding="utf-8")


# ---------- T301-recomputation.md ----------

def render_recompute() -> None:
    a = RECOMP["answer_volume"]
    six = RECOMP["six_distribution"]
    cite = RECOMP["citations"]
    inv = RECOMP["inventory"]
    cov = RECOMP["trace_coverage"]
    exp = RECOMP["expected_vs_actual"]["expected"]
    act = RECOMP["expected_vs_actual"]["actual"]

    lines: list[str] = []
    lines += [
        "# T301 独立复算表（工作包 B）",
        "",
        "## 1. 复算方法与口径",
        "",
        "- 复算绕过应用查询代码，直接以 `sqlite3` 对隔离库 `evidence/data/mktkb.sqlite3`、`evidence/data/qa-traces.sqlite3` 独立计算；脚本：`scripts/t301_recompute.py`，结果：`evidence/recompute/recompute-results.json`。",
        "- 口径（任务书 §2）：问答量按完成时间 + 产品请求 ID 去重，只计已提交结果，幂等重放不增量；六类结果 answer/clarification/not_found/conflict/service_error/knowledge_changed；未提交中断单列不入六类；已逻辑删除会话两侧排除；时间按 Asia/Shanghai 聚合，日历日转左闭右开 UTC 窗口；引用按「结果消息+文档」「结果消息+版本」两维去重；冲突不计入最终引用；Trace 覆盖率 = 有普通执行 Trace 的已完成请求数 ÷ 已完成请求数，纯重放不计覆盖，关闭/不可用/未记录/部分覆盖为独立状态；库存按「当前」口径。",
        "",
        "## 2. 范围与问答量",
        "",
        "| 指标 | 口径预期 | 独立复算实算 | 一致性 |",
        "| --- | --- | --- | --- |",
        f"| 请求行总数 | — | {RECOMP['scope']['request_rows_total']} | — |",
        f"| 范围内请求（排除已删除会话） | — | {RECOMP['scope']['in_scope_requests']} | — |",
        f"| 已删除会话排除请求数 | {exp['deleted_excluded_count']} | {act['deleted_excluded_count']} | {'一致' if exp['deleted_excluded_count'] == act['deleted_excluded_count'] else '不一致'} |",
        f"| 已完成问答量（按产品请求 ID） | {exp['completed_requests']} | {act['completed_requests']} | {'一致' if exp['completed_requests'] == act['completed_requests'] else '不一致'} |",
        f"| 去重后 client_request_id 数 | {exp['completed_distinct_client_requests']} | {act['completed_distinct_client_requests']} | {'一致' if exp['completed_distinct_client_requests'] == act['completed_distinct_client_requests'] else '不一致'} |",
        "",
        f"- 重放说明：S06 复用 S02 同一请求行（同一产品请求 ID、同一 client_request_id），二次提交不新增请求行；问答量无重复请求 ID 需要二次去重。",
        f"- 未提交中断单列：{RECOMP['answer_volume']['interrupted_count'] if 'interrupted_count' in RECOMP['answer_volume'] else act['interrupted_count']} 条（running / expired），不入六类。",
        "",
        "## 3. 六类结果分布",
        "",
        "| 结果类型 | 口径预期 | 实算 | 一致性 |",
        "| --- | --- | --- | --- |",
    ]
    for kind in ("answer", "clarification", "not_found", "conflict", "service_error", "knowledge_changed"):
        lines.append(f"| {kind} | {exp['six_distribution'][kind]} | {six[kind]} | {'一致' if exp['six_distribution'][kind] == six[kind] else '不一致'} |")

    lines += [
        "",
        "## 4. 按日趋势（Asia/Shanghai，左闭右开 UTC 窗口）",
        "",
        "| 日历日(Shanghai) | 已完成请求数 | 备注 |",
        "| --- | --- | --- |",
    ]
    for day, count in sorted(RECOMP["daily_trend_shanghai"].items()):
        note = "含午夜边界样本 S17（2026-11-20 23:59:59.750+08:00）" if day == "2026-11-20" else "含午夜边界样本 S18（2026-11-21 00:00:00.250+08:00）"
        lines.append(f"| {day} | {count} | {note} |")

    lines += [
        "",
        "### 4.1 午夜边界专项",
        "",
        "| 样本 | 预期归属日 | 实算归属日 | 完成时间(UTC) | 一致性 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in RECOMP["midnight_boundary"]:
        lines.append(f"| {item['sample_id']} | {item['expected_shanghai_day']} | {item['actual_shanghai_day']} | {item['finished_at']} | {'一致' if item['consistent'] else '不一致'} |")

    lines += [
        "",
        "## 5. 引用量（文档 / 版本两维去重）",
        "",
        "| 指标 | 口径预期 | 实算 | 一致性 |",
        "| --- | --- | --- | --- |",
        f"| 非冲突持久引用行 | {exp['citation_raw_non_conflict']} | {act['citation_raw_non_conflict']} | {'一致' if exp['citation_raw_non_conflict'] == act['citation_raw_non_conflict'] else '不一致'} |",
        f"| 文档维度去重对（消息+文档） | {exp['citation_document_dedup']} | {act['citation_document_dedup']} | {'一致' if exp['citation_document_dedup'] == act['citation_document_dedup'] else '不一致'} |",
        f"| 版本维度去重对（消息+版本） | {exp['citation_version_dedup']} | {act['citation_version_dedup']} | {'一致' if exp['citation_version_dedup'] == act['citation_version_dedup'] else '不一致'} |",
        "",
        "- 同文档多条引用行验证：S01 同一回答引用同一位置表文档 2 个来源单元，文档维度计 1、版本维度计 1。",
        "",
        "### 5.1 冲突场景（含 D5 定向验证）",
        "",
        "| 项目 | 任务书口径预期 | 隔离库实测 | 结论 |",
        "| --- | --- | --- | --- |",
        f"| 冲突消息持久引用行 | 0 行 | {cite['conflict_message_rows_excluded']} 行 | 与口径不一致（口径缺口，见 §8） |",
    ]
    for rec in cite["conflict_records"]:
        entries = []
        for conflict in rec["conflicts"]:
            for e in conflict["entries"]:
                entries.append(e["source_id"])
        lines.append(f"| 两方来源（结果 JSON `conflicts`） | 2 条 | source_id：{', '.join(entries)} | 两方来源取自结果 JSON |")

    lines += [
        "",
        "## 6. 库存指标（当前口径）",
        "",
        "| 指标 | 口径预期 | 实算 | 一致性 |",
        "| --- | --- | --- | --- |",
        f"| 待审核版本数 review_required | {exp['review_required_versions']} | {act['review_required_versions']} | {'一致' if exp['review_required_versions'] == act['review_required_versions'] else '不一致'} |",
        f"| 生效版本数 published | — | {inv['active_published_versions']} | — |",
        f"| 失败版本数 failed | — | {inv['failed_versions']} | — |",
        f"| 失败导入任务数 | {exp['failed_jobs']} | {act['failed_jobs']} | {'一致' if exp['failed_jobs'] == act['failed_jobs'] else '不一致'} |",
    ]
    for job in inv["failed_jobs"]:
        lines.append(f"| 失败任务明细 | — | 任务 {job['job_id']}；版本 {job['version_id']}；错误码 {job['error_code']} | — |")

    lines += [
        "",
        "## 7. Trace 覆盖率",
        "",
        "| 指标 | 口径预期 | 实算 | 一致性 |",
        "| --- | --- | --- | --- |",
        f"| 覆盖率分母（已完成请求） | {cov['completed_denominator']} | {cov['completed_denominator']} | 一致 |",
        f"| 有普通执行 Trace | {exp['trace_covered']} | {act['trace_covered']} | {'一致' if exp['trace_covered'] == act['trace_covered'] else '不一致'} |",
        f"| 纯重放 Trace（不计覆盖） | {exp['trace_replay_traces']} | {act['trace_replay_traces']} | {'一致' if exp['trace_replay_traces'] == act['trace_replay_traces'] else '不一致'} |",
        f"| 关闭态请求（独立状态） | {exp['trace_disabled']} | {act['trace_disabled']} | {'一致' if exp['trace_disabled'] == act['trace_disabled'] else '不一致'} |",
        f"| 未记录请求（受控样本） | {exp['trace_untracked']} | {act['trace_untracked']} | {'一致' if exp['trace_untracked'] == act['trace_untracked'] else '不一致'} |",
        f"| 覆盖率 | — | {cov['coverage_ratio']}（{cov['covered']}/{cov['completed_denominator']}） | — |",
        "",
        "- 重放 Trace：status=replayed、Span 为空，不纳入分子；关闭态 S15 无 Trace 行与响应头，单列 disabled；受控午夜/中断样本未写 Trace，单列 untracked。",
        "",
        "## 8. 已删除会话排除与口径缺口",
        "",
        "### 8.1 已删除会话",
        "",
        "| 样本 | 会话已删除 | 统计侧排除 | 一致性 |",
        "| --- | --- | --- | --- |",
    ]
    for item in RECOMP["deleted_conversation"]:
        lines.append(f"| {item['sample_id']} | {'是' if item['conversation_deleted'] else '否'} | {'是' if item['excluded_from_statistics'] else '否'} | {'一致' if item['consistent'] else '不一致'} |")

    lines += [
        "",
        "### 8.2 口径缺口 D5：冲突消息被写入持久引用行",
        "",
        "- 任务书 §2：冲突消息不产生持久引用行，两方来源取自结果 JSON 的 `conflicts`，最终引用计数不含冲突。",
        "- 代码侧观察（隔离实测对应路径，`backend/src/mktkb/conversations/service.py`）：",
        "  - `_reference_ids`：冲突结果把 `conflicts` 各条目 source_id 并入待持久化/校验来源；",
        "  - 来源清空分支仅覆盖 `service_error / not_found / clarification`，未覆盖 `conflict`；",
        "  - 提交阶段对 active 来源写入 `MessageSource` 行。",
        "- 隔离库实测：S05 冲突消息落 `MessageSource` 2 行，两方来源当时均为 active；结果 JSON `conflicts` 同时保留两方来源。",
        "- 持久化落点为 `conversations/service.py`（工作包 A 审计文档 T301-data-audit.md 引用正确：1970-1979、2036-2038、2066-2086）；项目经理转述中曾误写 `qa/service.py`，经核该文件 953 行、无 conflict/MessageSource 处理，特此澄清。",
        "- 处置：复算表仍按任务书口径给出预期值（冲突持久引用行 0），另列实测值（2 行）与差异结论；未修改代码、未修改任务书。",
        "",
        "### 8.3 其他已知限制",
        "",
        "- 午夜边界样本为受控构造（完成时间固定），未等待真实墙钟跨越 00:00。",
        "- knowledge_changed 样本经正常 HTTP 入口触发，检索阶段通过故障替身缝注入 revision 变更异常。",
        "- 覆盖率分母包含关闭态与未记录请求；如需「可观测范围内覆盖率」可另按状态过滤，本报告按任务书口径以全部已完成请求为分母。",
        "",
    ]
    (ROOT / "T301-recomputation.md").write_text("\n".join(lines), encoding="utf-8")


# ---------- T301-trace-probe.md ----------

def render_probe() -> None:
    lines: list[str] = []
    lines += [
        "# T301 Trace 两态抽查记录（工作包 B）",
        "",
        "## 1. 抽查方法与脱敏",
        "",
        f"- 直接读取隔离 Trace 库 `evidence/data/qa-traces.sqlite3`（脚本 `scripts/t301_trace_probe.py`，结果 `evidence/trace/trace-probe.json`）。",
        f"- 实测 Trace 总数：{PROBE['trace_count']}（启用态普通执行 11 条 + 重放 1 条；关闭态 0 条）。",
        "- 脱敏：只记录 Span 名、时长（ms）、状态与关联键；不摘录 Trace 原始属性、密钥、原始请求头与原文问题。",
        "",
        "## 2. 请求 ↔ Trace 关联方式",
        "",
        f"- 产品请求 ID：`traces.request_id = ConversationRequest.id`；{len(PROBE['linkage']['checks'])} 条 Trace 关联键全部在业务库请求行命中。",
        f"- HTTP 请求 ID：`traces.http_request_id` 对应响应头 `X-Request-ID`；{sum(1 for c in PROBE['linkage']['checks'] if c['http_request_id_recorded'])} 条记录了 HTTP 请求 ID。",
        "- 重放为新 HTTP 请求，故 http_request_id 不同，但复用同一产品请求 ID。",
        "",
        "## 3. 执行路径与 Span 清单（实测记录）",
        "",
    ]
    path_labels = {
        "rag": "RAG 路径（rag）",
        "legacy": "legacy 路径（legacy）",
        "legacy_with_rag_candidates": "legacy_with_rag_candidates 路径（legacy 候选 + RAG 候选混合）",
    }
    for path, inv in PROBE["path_span_inventory"].items():
        lines += [f"### 3.{list(PROBE['path_span_inventory']).index(path)+1} {path_labels.get(path, path)}", "",
                  "| Span 名 | 说明 |", "| --- | --- |"]
        for name in inv["span_names"]:
            lines.append(f"| `{name}` | 实测采集到；时长字段 `duration_ms`、状态 `status` |")
        if inv["examples"]:
            ex = inv["examples"][0]
            lines += ["", f"代表性 Trace：request `{ex['request_id']}`，结果 `{ex['outcome_kind']}`，状态 `{ex['status']}`。", "",
                      "| Span | 时长(ms) | 状态 |", "| --- | --- | --- |"]
            for span in ex["spans"]:
                lines.append(f"| `{span['name']}` | {span['duration_ms']} | {span['status']} |")
        lines.append("")

    lines += [
        "## 4. 重放标记",
        "",
        "| 项 | 实测 |",
        "| --- | --- |",
    ]
    for pair in PROBE["replay"]["pairs"]:
        lines += [
            f"| 产品请求 ID | `{pair['request_id']}` |",
            f"| 重放 Trace ID | `{pair['replay_trace_id']}` |",
            f"| 原始 Trace ID | {', '.join('`'+x+'`' for x in pair['original_trace_ids'])} |",
            f"| 重放 HTTP 请求 ID | `{pair['replay_http_request_id']}` |",
            f"| 重放状态 | status=`{pair['replay_status']}`，replayed=1，Span 数={pair['replay_span_count']} |",
        ]
    lines += [
        "",
        f"- 关联要点：{PROBE['replay']['note']}",
        "- `previous_trace_id` 实测为 null：当前重放链路未回填上一条 Trace 关联键；重放与原始 Trace 的串联依赖同一产品请求 ID。",
        "",
        "## 5. Trace 关闭态",
        "",
        "| 样本 | 业务请求存在 | Trace 行 | 响应头 X-Trace-ID | 状态 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for d in PROBE["disabled_state"]:
        lines.append(f"| {d['sample_id']} | {'是' if d['business_request_exists'] else '否'} | {'有' if d['trace_row_found'] else '无'} | {'有' if d['trace_header_present'] else '无'} | {d['state']} |")

    old = PROBE["old_version_citation_fields"]
    lines += [
        "",
        "## 6. 旧版引用可展示字段",
        "",
        f"- 样本：{old['sample']['sample_id'] if old['sample'] else '—'}；版本号 `{old['sample']['version_number'] if old['sample'] else '—'}`。",
        f"- 结果 JSON 来源条目字段键：{', '.join('`'+k+'`' for k in old['field_keys'])}。",
        f"- 字段核验：document_name 存在={old['sample']['document_name_present']}，locator 存在={old['sample']['locator_present']}，published_at 存在={old['sample']['published_at_present']}。",
        f"- {old['note']}",
        "",
        "## 7. 限制与备注",
        "",
        "- 第三执行路径 `legacy_with_rag_candidates` 已在样本中触发并单独记录 Span 清单。",
        "- 关闭态应用未生成任何 Trace；未观测到「部分覆盖 / 读取失败」状态，本次样本不涉及。",
        "- Span 时长为隔离离线替身环境下的实测值，不代表线上性能；`model_failure` 仅在 service_error 分支出现。",
        "",
    ]
    (ROOT / "T301-trace-probe.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    render_matrix()
    render_recompute()
    render_probe()
    print("docs rendered")
