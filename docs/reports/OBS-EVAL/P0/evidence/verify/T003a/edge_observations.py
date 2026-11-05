"""T003a 边界行为观察（仓库外，只读）：用于 review 的“观察/风险”条目，不作为 §5 判定依据。"""

from __future__ import annotations

import threading
from dataclasses import replace

from mktkb.observability import (
    TraceMode,
    TracePath,
    TraceRecord,
    current_trace,
    start_trace,
    validate_required_spans,
)


class Spy:
    def __init__(self) -> None:
        self.calls = []

    def write_best_effort(self, record, spans):  # noqa: ANN001
        self.calls.append((record, list(spans)))


SCOPE = "end_to_end"


def record_of(**start_kwargs):
    spy = Spy()
    start_kwargs.setdefault("http_request_id", "h")
    start_kwargs.setdefault("mode", TraceMode.LOCAL)
    start_kwargs.setdefault("scope", SCOPE)
    with start_trace(repo=spy, **start_kwargs) as trace:
        pass
    record, spans = spy.calls[0]
    return record, spans, trace


print("== 1. replayed 优先级 vs incomplete（§5.4 与设计 §6.1 的边界） ==")
rec, _, _ = record_of(replayed=True)
print(f"replayed=True, 未设置 outcome -> status={rec.status!r} outcome={rec.outcome_kind!r} path={rec.path!r}")
rec, _, _ = record_of(replayed=True, path=None)
print(f"replayed=True, path=None, 未设置 outcome -> status={rec.status!r}")

print("\n== 2. mode=live 是否被内核拒绝（设计 §9：P0 不得用 live） ==")
try:
    rec, _, _ = record_of(mode="live")
    print(f"start_trace(mode='live') 被接受 -> record.mode={rec.mode!r}")
except Exception as exc:  # noqa: BLE001
    print(f"start_trace(mode='live') 被拒绝：{type(exc).__name__}: {exc}")

print("\n== 3. annotate 可覆盖 start_trace 参数字段（mode/replayed/outcome_kind/path/scope） ==")
spy = Spy()
with start_trace(http_request_id="h", mode=TraceMode.LOCAL, scope=SCOPE, path=TracePath.RAG, repo=spy) as tr:
    tr.annotate(mode="live", replayed=True, path="legacy", outcome_kind="answer", scope="retrieval_only")
rec, _ = spy.calls[0]
print(
    f"after annotate: mode={rec.mode!r} replayed={rec.replayed!r} path={rec.path!r} "
    f"outcome_kind={rec.outcome_kind!r} scope={rec.scope!r} status={rec.status!r}"
)

print("\n== 4. 线程池/子线程是否继承当前 trace（contextvars 不跨线程传播） ==")
observed = {}
with start_trace(http_request_id="h", mode=TraceMode.LOCAL, scope=SCOPE):
    def worker():
        observed["current"] = current_trace()
    t = threading.Thread(target=worker)
    t.start()
    t.join(10)
print(f"子线程 current_trace() = {observed['current']!r}")

print("\n== 5. validate_required_spans 对非法 JSON 文本的容忍度（fail-open?） ==")
rec = TraceRecord(
    trace_id="t", request_id="r", mode="local", scope=SCOPE,
    path="rag", outcome_kind="answer", content_mode="hash", status="ok",
)
required = ["parse", "recall", "fuse", "answer", "commit"]
for field in ("filter_decisions_json", "retrieval_counts_json"):
    bad = replace(rec, **{field: "{not-json"})
    print(f"{field}='{{not-json' -> missing={validate_required_spans(bad, required)}（条件属性无法读取，被忽略）")

print("\n== 6. Span 属性不可序列化时的兜底（报告已列为风险） ==")
spy = Spy()
with start_trace(http_request_id="h", mode=TraceMode.LOCAL, scope=SCOPE, repo=spy) as tr:
    with tr.span("bad", obj=object()):
        pass
    tr.set_outcome("answer")
spans = spy.calls[0][1]
print(f"attributes_json={spans[0].attributes_json!r} status={spans[0].status!r}")

print("\n== 7. 空 question 字符串是否视为“未设置” ==")
spy = Spy()
with start_trace(http_request_id="h", mode=TraceMode.LOCAL, scope=SCOPE, repo=spy, question="") as tr:
    tr.set_outcome("answer")
rec = spy.calls[0][0]
print(f"question='' -> question_hash={rec.question_hash!r} question_chars={rec.question_chars!r}")

print("\n== 8. 非法 filter_decisions_json 是否在 annotate 处 fail closed ==")
spy = Spy()
with start_trace(http_request_id="h", mode=TraceMode.LOCAL, scope=SCOPE, repo=spy) as tr:
    try:
        tr.annotate(filter_decisions_json="{not-json")
        print("annotate(filter_decisions_json='{not-json') 未抛")
    except ValueError as exc:
        print(f"annotate 立即 fail closed：ValueError: {exc}")
    tr.set_outcome("answer")
print(f"write calls={len(spy.calls)}")

print("\n== 9. current_trace() 返回上下文中的同一对象 ==")
with start_trace(http_request_id="h", mode=TraceMode.LOCAL, scope=SCOPE) as tr:
    print(f"current_trace() is trace: {current_trace() is tr}")

print("\nEDGE-OBSERVATIONS-DONE")
