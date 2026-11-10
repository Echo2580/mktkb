"""T203 独立验收探针 1：外部出站=0 + 只走产品入口 + 不直接调 RagIndex.ask。

自写（不 import 开发用例），断言：
1. 自写 socket/httpx netguard：任何**外部**出站立即失败；运行结束外部尝试必须为 0；
2. 评测代码不直接调 RagIndex.ask：用 caller 归因证明只有产品模块 mktkb.qa.service 调用它；
3. 产品问答确实经过 HTTP（ASGI）：记录会话客户端的每一次请求方法与路径；
4. 引用转换/持久化/来源详情权限(200/403)/有效版本复核(410 superseded → 重新提问版本>=2)；
5. 同 client_request_id 重复提交：消息数不变、chat 调用数不变（不重复付费）；
6. RAG 与 legacy 两个分支都出现在产品 trace 里。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import traceback
from pathlib import Path

RESULT_NAME = "probe1_result.json"


def _result_path(argv: list[str]) -> Path:
    """结果文件位置：``--out <path>`` 优先；否则系统临时目录下固定子目录。

    绝不默认写进仓库（旧实现写在自己旁边，复跑一次就在 evidence/ 里多一个未跟踪文件）。
    """
    if len(argv) >= 2 and argv[0] == "--out":
        return Path(argv[1])
    return Path(tempfile.gettempdir()) / "mktkb-p2-t203-probe1" / RESULT_NAME

REPO = Path(__file__).resolve().parents[8]
sys.path.insert(0, str(REPO / "backend" / "src"))

import socket  # noqa: E402
import httpx  # noqa: E402

LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}
EXTERNAL: list[str] = []
LOCAL: list[str] = []


def _is_local(address) -> bool:
    if isinstance(address, str):
        return address.startswith("\\\\.\\pipe\\") or address.startswith("/")
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("utf-8", "replace")
        return isinstance(host, str) and (host in LOOPBACK or host.startswith("127."))
    return False


def install_netguard() -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection
    real_gai = socket.getaddrinfo

    def connect(self, address, *a, **k):
        if _is_local(address):
            LOCAL.append(f"socket.connect {address!r}")
            return real_connect(self, address, *a, **k)
        EXTERNAL.append(f"socket.connect {address!r}")
        raise RuntimeError(f"外部出站被验收闸门拦截: {address!r}")

    def connect_ex(self, address, *a, **k):
        if _is_local(address):
            LOCAL.append(f"socket.connect_ex {address!r}")
            return real_connect_ex(self, address, *a, **k)
        EXTERNAL.append(f"socket.connect_ex {address!r}")
        raise RuntimeError(f"外部出站被验收闸门拦截: {address!r}")

    def create_connection(address, *a, **k):
        if _is_local(address):
            LOCAL.append(f"create_connection {address!r}")
            return real_create(address, *a, **k)
        EXTERNAL.append(f"create_connection {address!r}")
        raise RuntimeError(f"外部出站被验收闸门拦截: {address!r}")

    def getaddrinfo(host, *a, **k):
        if not (isinstance(host, str) and (host in LOOPBACK or host.startswith("127."))):
            EXTERNAL.append(f"getaddrinfo {host!r}")
            raise RuntimeError(f"外部域名解析被验收闸门拦截: {host!r}")
        return real_gai(host, *a, **k)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = create_connection
    socket.getaddrinfo = getaddrinfo

    def sync_http(self, request):
        EXTERNAL.append(f"httpx.HTTPTransport {request.url}")
        raise RuntimeError(f"真实同步 HTTP 被拦截: {request.url}")

    async def async_http(self, request):
        EXTERNAL.append(f"httpx.AsyncHTTPTransport {request.url}")
        raise RuntimeError(f"真实异步 HTTP 被拦截: {request.url}")

    httpx.HTTPTransport.handle_request = sync_http
    httpx.AsyncHTTPTransport.handle_async_request = async_http


class _LoggingTransport:
    """包在 ASGITransport 外：记录评测驱动对产品路由的每一次调用。"""

    def __init__(self, inner, log: list[tuple[str, str]]) -> None:
        self.inner = inner
        self.log = log

    async def handle_async_request(self, request):
        self.log.append((request.method, request.url.path))
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        closer = getattr(self.inner, "aclose", None)
        if closer is not None:
            await closer()


def main() -> int:
    install_netguard()
    from mktkb.evaluation.product_adapter import (
        IngestSource,
        MockChatBackend,
        P2IngestPlan,
        P2RunDataset,
        ProductEvalAdapter,
    )
    from mktkb.qa.service import QaEngine
    from mktkb.rag import providers as rag_providers
    from mktkb.rag.index import RagIndex

    rag_providers.reset_post_counters()

    ask_callers: list[str] = []
    answer_callers: list[str] = []
    real_ask = RagIndex.ask
    real_answer = QaEngine.answer

    def tracing_ask(self, *a, **k):
        ask_callers.append(sys._getframe(1).f_globals.get("__name__", "?"))
        return real_ask(self, *a, **k)

    def tracing_answer(self, *a, **k):
        answer_callers.append(sys._getframe(1).f_globals.get("__name__", "?"))
        return real_answer(self, *a, **k)

    RagIndex.ask = tracing_ask
    QaEngine.answer = tracing_answer

    import tempfile

    root = Path(tempfile.mkdtemp(prefix="p2t203-probe1-"))

    fixtures = REPO / "fixtures" / "acceptance" / "normal"
    d01 = fixtures / "D01_物品位置表.xlsx"
    d04 = fixtures / "D04_活动策划流程.docx"
    dataset = P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "verify-probe-v1",
            "label_version": "verify-probe-v1",
            "suite": "probe",
            "manifest_sha256": "a" * 64,
            "case_count": 0,
        },
    )

    rag_q = "把城东店和城西店的宣传海报记录都列出来"
    legacy_q = "活动策划需要哪些步骤？"
    http_log: list[tuple[str, str]] = []
    result: dict = {"probe": "product_entry_netguard", "ok": False, "checks": []}
    result["scratch_root"] = str(root)

    def check(name: str, ok: bool, detail=None) -> None:
        result["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            raise AssertionError(f"{name} 失败: {detail!r}")

    async def scenario() -> None:
        chat = MockChatBackend()
        adapter = ProductEvalAdapter(
            root / "app",
            chat=chat,
            dataset=dataset,
            ingest_plan=P2IngestPlan(
                sources=(IngestSource(path=d01), IngestSource(path=d04)), label="probe"
            ),
        )
        try:
            await adapter.start()
            for session in adapter._sessions.values():
                session.client._transport = _LoggingTransport(session.client._transport, http_log)

            receipts = await adapter.ingest()
            check("ingest_via_product_upload", [r.upload_status for r in receipts] == [202, 202])
            check("ingest_worker_and_publish", all(r.job_state == "succeeded" and r.published for r in receipts))

            conv = await adapter.open_conversation()
            rag = await adapter.ask_turn(
                rag_q, user_id="employee", conversation_id=conv,
                client_request_id="aaaaaaaa-1111-4111-8111-000000000001",
            )
            legacy = await adapter.ask_turn(
                legacy_q, user_id="employee", conversation_id=conv,
                client_request_id="aaaaaaaa-1111-4111-8111-000000000002",
            )
            check("rag_turn_answered", rag.kind == "answer" and rag.trace_path == "rag", rag.as_dict(include_text=False))
            check("legacy_turn_answered", legacy.kind == "answer" and legacy.trace_path == "legacy", legacy.as_dict(include_text=False))

            # 3) 产品 HTTP 调用确实发生
            paths = [p for (_, p) in http_log]
            check("http_message_route_used", any(p == f"/api/v1/conversations/{conv}/messages" for p in paths), paths[:8])
            check("http_upload_and_publish_used",
                  any(p == "/api/v1/documents" for p in paths)
                  and any(p.endswith("/publish") for p in paths), paths[:8])

            # 2) caller 归因：评测模块绝不直接调 RagIndex.ask
            check("rag_ask_only_from_product", ask_callers and set(ask_callers) == {"mktkb.qa.service"}, sorted(set(ask_callers)))
            check("no_evaluation_module_in_rag_callers",
                  all(not c.startswith("mktkb.evaluation") for c in ask_callers), sorted(set(ask_callers)))
            check("qa_answer_only_from_product",
                  answer_callers and all(c.startswith("mktkb.conversations") for c in answer_callers),
                  sorted(set(answer_callers)))

            # 4) 引用转换 + 持久化 + 权限
            code, listing = await adapter.list_messages(conv)
            check("messages_persisted", code == 200 and listing["total"] == 4, {"code": code, "total": listing.get("total")})
            assistant = [m for m in listing["items"] if m["role"] == "assistant"]
            source = assistant[0]["sources"][0]
            check("citation_converted",
                  source["status"] == "active" and source.get("locator") and source.get("document_name"),
                  {k: source.get(k) for k in ("status", "document_name", "version_number")})
            owner_code, owner_detail = await adapter.source_detail(assistant[0]["id"], source["source_id"])
            other_code, _ = await adapter.source_detail(assistant[0]["id"], source["source_id"], user_id="admin")
            check("source_detail_owner_200", owner_code == 200 and owner_detail.get("text"), owner_code)
            check("source_detail_other_403", other_code == 403, other_code)

            # 有效版本复核：发布 v2 后旧引用 410 superseded，新提问只用 >=2 版本
            import openpyxl

            wb = openpyxl.load_workbook(d01)
            wb.worksheets[0].cell(row=3, column=1, value="业务更新：verify-probe")
            revised = root / "D01_verify.xlsx"
            wb.save(revised)
            new_receipts = await adapter.ingest(
                P2IngestPlan(sources=(IngestSource(
                    path=revised,
                    document_id=receipts[0].document_id,
                    expected_active_version_id=receipts[0].version_id,
                ),))
            )
            check("v2_published", new_receipts[0].published is True, new_receipts[0].as_dict())
            stale_code, stale = await adapter.source_detail(assistant[0]["id"], source["source_id"])
            check("old_version_410_superseded",
                  stale_code == 410 and stale.get("error", {}).get("details", {}).get("status") == "superseded",
                  {"code": stale_code, "details": stale.get("error", {}).get("details")})
            refreshed = await adapter.ask_turn(
                rag_q, user_id="employee", conversation_id=conv,
                client_request_id="aaaaaaaa-1111-4111-8111-000000000003",
            )
            d01_versions = [s["version_number"] for s in refreshed.sources if str(s.get("document_name", "")).startswith("D01_")]
            check("refreshed_uses_current_version", refreshed.kind == "answer" and all(v >= 2 for v in d01_versions), d01_versions)

            # 4b) 无候选拒答：规则路径 0 次 chat，不冒充模型回答
            before_unknown = chat.call_count
            unknown = await adapter.ask_turn(
                "火星店的宣传海报在哪里？", user_id="employee", conversation_id=conv,
                client_request_id="aaaaaaaa-1111-4111-8111-000000000004",
            )
            check("no_candidate_refusal_not_found", unknown.kind == "not_found" and unknown.source_ids == (),
                  unknown.as_dict(include_text=False))
            check("no_candidate_refusal_zero_chat", chat.call_count == before_unknown,
                  {"before": before_unknown, "after": chat.call_count})

            # 5) 幂等
            before_chat = chat.call_count
            _, before_listing = await adapter.list_messages(conv)
            replay = await adapter.ask_turn(
                rag_q, user_id="employee", conversation_id=conv,
                client_request_id="aaaaaaaa-1111-4111-8111-000000000001",
            )
            _, after_listing = await adapter.list_messages(conv)
            check("replay_same_message", replay.message_id == rag.message_id and replay.request_id == rag.request_id,
                  {"first": rag.message_id, "replay": replay.message_id})
            check("replay_no_new_messages", after_listing["total"] == before_listing["total"], before_listing["total"])
            check("replay_no_new_chat", chat.call_count == before_chat, {"before": before_chat, "after": chat.call_count})

            # 6) 分支与真实出站
            calls = adapter.provider_calls()
            check("branches_rag_and_legacy", {rag.trace_path, legacy.trace_path} == {"rag", "legacy"})
            check("provider_outbound_zero", calls["outbound_network"] == 0 and calls["chat"]["outbound_network"] == 0, calls["chat"])
            counters = rag_providers.post_counters()
            check("rag_vendor_post_counters_zero",
                  all(v == 0 for kind in counters.values() for v in kind.values()), counters)
            result["chat_calls"] = chat.call_count
            result["http_calls"] = len(http_log)
        finally:
            await adapter.close()

    try:
        asyncio.run(scenario())
        check("external_outbound_zero", len(EXTERNAL) == 0, EXTERNAL[:10])
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()[-2000:]
    finally:
        result["external_attempts"] = EXTERNAL
        result["local_attempts"] = len(LOCAL)
        result["rag_ask_callers"] = sorted(set(ask_callers))
        result["qa_answer_callers"] = sorted(set(answer_callers))
        # T206-PRE：复跑不得往仓库/证据目录写结果（R2-F-R2-5）。默认写系统临时目录，
        # 需要归档时用 --out 显式指定工作区外的位置；只写 JSON、不改任何跟踪文件。
        target = _result_path(sys.argv[1:])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": result.get("ok"), "error": result.get("error"),
                          "checks": len(result["checks"]),
                          "failed": [c["name"] for c in result["checks"] if not c["ok"]],
                          "external_attempts": EXTERNAL, "local_attempts": len(LOCAL),
                          "ask_callers": result["rag_ask_callers"],
                          "answer_callers": result["qa_answer_callers"]}, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
