"""C6 独立复核：首错停 / 自动重试 0 / 阻断后续发送 / 清理仍执行。

自建变体：把 writer 的封存上限压到不可能通过的大小，令第一回合在写盘阶段失败；
核“首个硬错误即停、零自动重试、后续发送被阻断、清理仍执行”。另引用 A 的
runner 级用例（run_p2 aborted、后续题不执行）作为同一对象的补充证据。
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ci_support as sup  # noqa: E402

# 本副本导入模块（记录 attempt 次数）；构建侧仍用产品装配逻辑。
from mktkb.evaluation.p2_evidence_capture import BINDING_KEYS  # noqa: E402

rows: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    rows.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


async def main() -> int:
    sup.install_network_guard()
    from cryptography.fernet import Fernet

    from mktkb.evaluation.p2_evidence_capture import EvidenceCaptureBlocked, EvidenceCaptureConfig
    from mktkb.evaluation.p2_evidence_io import EvidenceWriter
    from mktkb.evaluation.product_adapter import (
        IngestSource,
        MockChatBackend,
        P2IngestPlan,
        P2RunDataset,
        ProductEvalAdapter,
    )

    tmp = sup.fresh_temp("t207-ci-first-error-")
    print("tmp_root=", tmp)
    bindings = {key: "ci-" + key for key in BINDING_KEYS}
    bindings.update(
        {
            "fixture_kind": "local_mock",
            "run_id": "ci-first-error-run",
            "dataset_version": "ci-synthetic-dataset-v1",
            "plan_sha256": "c" * 64,
        }
    )
    writer = EvidenceWriter(
        root_dir=tmp / "evidence",
        key=Fernet.generate_key(),
        bindings=bindings,
        run_name="ci",
        max_envelope_bytes=64,
    )
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp / "product",
        chat=chat,
        dataset=P2RunDataset(visibility="public", cases=(), identity={"dataset_version": "v", "label_version": "l", "suite": "s", "manifest_sha256": "4" * 64, "case_count": 0}),
        ingest_plan=P2IngestPlan(sources=(IngestSource(sup.D01), IngestSource(sup.D04)), label="ci"),
        evidence_capture=EvidenceCaptureConfig(
            root_dir=tmp / "evidence",
            bindings=bindings,
            writer=writer,
            capture_schema_version=sup.V03,
        ),
        purge_traces_on_close=True,
    )
    close_error: BaseException | None = None
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation()
        session = adapter._evidence_session
        assert session is not None
        await adapter.ask_turn(
            "活动策划一般要做哪些准备步骤？",
            user_id="employee",
            conversation_id=conversation,
            client_request_id=str(uuid.uuid4()),
        )
        record("第一回合在封存失败时必须抛错（不得静默通过）", False, "ask_turn 未抛错")
        return 1
    except Exception as exc:  # noqa: BLE001 - 期望固定失败
        first_error = f"{type(exc).__name__}:{exc}"
        record("第一回合在封存失败时抛固定错误", True, first_error)
    finally:
        try:
            await adapter.close()
        except Exception as exc:  # noqa: BLE001 - 清理阶段固定失败
            close_error = exc

    session = adapter._evidence_session
    calls_after_failure = chat.call_count
    record(
        "失败后会话 blocked 且 writer 固定 failed",
        session is not None and session.blocked is True and writer.status == "failed",
        f"blocked={None if session is None else session.blocked} writer={writer.status} last_error={writer.last_error}",
    )
    record(
        "零自动重试：首个错误只发生一次模型调用",
        calls_after_failure == 1,
        f"chat.call_count={calls_after_failure}",
    )
    record(
        "失败回合未落任何 turn 密文（不把未封存当已封存）",
        [item for item in writer.written if item["kind"] == "turn"] == [],
        str(writer.written),
    )
    blocked_error = ""
    try:
        await adapter.ask_turn(
            "城东店的宣传海报记录有哪些？",
            user_id="employee",
            conversation_id="ci-synthetic-conversation",
            client_request_id=str(uuid.uuid4()),
        )
    except EvidenceCaptureBlocked as exc:
        blocked_error = str(exc)
    record(
        "后续提问被阻断且不再有供应商发送",
        blocked_error == "evidence_capture_session_blocked" and chat.call_count == calls_after_failure,
        f"blocked_error={blocked_error} calls={chat.call_count} (before={calls_after_failure})",
    )
    record("清理仍执行：trace 库已删除", not adapter.paths.trace_db.exists(), str(adapter.paths.trace_db))
    record("close() 以固定 IO 错暴露封存失败", isinstance(close_error, Exception), repr(close_error))
    record("manifest 未生成（失败 run 不得声称已封存）", adapter.evidence_capture_manifest() is None)
    record("网络边界：真实外连 0", sup.external_attempts() == [], str(sup.external_attempts()))

    sup.remove_tree(tmp)
    failed = [row for row in rows if not row[1]]
    print(f"\nFIRST-ERROR TOTAL={len(rows)} FAILED={len(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
