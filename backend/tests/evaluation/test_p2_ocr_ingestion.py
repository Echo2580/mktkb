"""P2-T204：受控 OCR 导入 / 来源身份 / 页级费用回执 / 缓存准入（Mock-only，零真实调用）。

本文件只验 `mktkb.evaluation.p2_ingestion` 的模块契约，不建产品应用：
- 12 页/图调用计划（D07 8 页 + D08 2 页 + D09 1 图 + D10 1 图）与实际 Mock 调用逐页一致，
  页与图分别计数，每页分片数不超过产品上限 `ParseLimits().ocr_max_tiles`；
- 每次调用都绑定 document/version/page/input hash/provider/model/region，页级 reserve/settle
  归属到 `ocr` 成本中心，回执能用 `reservation_id` + `request_sha256` 对回账本行；
- 合法缓存命中（身份一致、有产品成功审计行、未过期）与真实调用分别计数、且命中不重复计费；
- 同页不同文档/不同版本/不同 input hash 的缓存串用一律拒绝；伪造/过期/模拟来源条目拒绝；
- 页失败/预算不足/缺 usage/空片段立即停止，不把空片段记成功，不绕过 OCR 计费。

零真实调用：只使用 `MockOcrTransport`（`httpx` 传输替身，不出网）+ 外置 socket 闸门；
不读 `.env`、不写共享账本/GO、不装依赖。
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有验收级网络闸门（不复制实现）
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support import ocr_transcripts  # noqa: E402
from acceptance.support.netguard import t09_network_guard  # noqa: F401  (pytest fixture)

from mktkb.evaluation.p2_ingestion import (  # noqa: E402
    CACHE_HIT,
    CACHE_INPUT_HASH_MISMATCH,
    CACHE_MISS,
    CACHE_REJECTED,
    CACHE_SOURCE_IDENTITY_MISMATCH,
    OCR_EMPTY_RESULT,
    OCR_PAGE_CALL_LIMIT,
    OCR_PAGE_NOT_PLANNED,
    OCR_SOURCE_UNBOUND,
    OCR_USAGE_MISSING,
    MockOcrTransport,
    OcrCallIdentity,
    OcrDocumentPlan,
    OcrImportPlan,
    OcrIngestionError,
    OcrPageReceipt,
    OcrResultCache,
    OcrTranscript,
    P2OcrIngestion,
    ProductOcrSuccess,
)
from mktkb.ingestion.parsers.types import ParseLimits  # noqa: E402
from mktkb.providers.ocr_budgeted import OCRBudgetRefused  # noqa: E402
from mktkb.providers.types import OCRInput, OCRUnavailable  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
NORMAL = ROOT / "fixtures" / "acceptance" / "normal"

FILES: dict[str, tuple[Path, str, int, int, str]] = {
    # key: (path, kind, page_count, image_count, expected_mode)
    "D07": (NORMAL / "D07_活动申请扫描件.pdf", "pdf", 8, 0, "text"),
    "D08": (NORMAL / "D08_仓库安全须知扫描件.pdf", "pdf", 2, 0, "text"),
    "D09": (NORMAL / "D09_物料领用通知.png", "png", 1, 1, "text"),
    "D10": (NORMAL / "D10_盘点通知.jpg", "jpg", 1, 1, "table"),
}
TEXT_PRICE = 0.5
TABLE_PRICE = 0.15


def plan(keys: tuple[str, ...] = ("D07", "D08", "D09", "D10"), **overrides) -> OcrImportPlan:
    documents = []
    for key in keys:
        path, kind, pages, images, mode = FILES[key]
        documents.append(
            OcrDocumentPlan(
                document_key=key,
                path=path,
                file_kind=kind,
                page_count=overrides.get("page_count", pages),
                image_count=images,
                tiles_per_page=overrides.get("tiles_per_page", 1),
                expected_mode=overrides.get("expected_mode", mode),
            )
        )
    return OcrImportPlan(documents=tuple(documents), label="p2-t204-unit")


def transcripts(keys: tuple[str, ...] = ("D07", "D08", "D09", "D10")) -> dict[str, OcrTranscript]:
    result = {}
    for key in keys:
        spec = ocr_transcripts.OCR_BINDINGS[key]
        result[key] = OcrTranscript(
            document_key=key,
            pages=dict(spec["pages"]),
            table=spec.get("table"),
        )
    return result


def ingestion(
    tmp_path: Path,
    keys: tuple[str, ...] = ("D07", "D08", "D09", "D10"),
    *,
    stage_limit_cny: float = 9.66,
    cache: OcrResultCache | None = None,
    max_calls: int | None = None,
    **overrides,
) -> P2OcrIngestion:
    chosen_plan = plan(keys, **overrides)
    instance = P2OcrIngestion.isolated_mock(
        tmp_path / f"ocr-{uuid.uuid4().hex[:8]}",
        plan=chosen_plan,
        transcripts=transcripts(keys),
        stage_limit_cny=stage_limit_cny,
        max_calls=max_calls,
    )
    if cache is not None:
        instance.cache = cache
    return instance


def bound(instance: P2OcrIngestion, key: str, *, document_id: uuid.UUID | None = None, version_id: uuid.UUID | None = None):
    return instance.bind(
        key,
        document_id=document_id or uuid.uuid4(),
        version_id=version_id or uuid.uuid4(),
    )


def page_input(binding, page: int, *, content: bytes | None = None, mode: str = "text") -> OCRInput:
    return OCRInput(
        content=content if content is not None else f"tile-{binding.document_key}-p{page}-{mode}".encode(),
        mime_type="image/png",
        page=page,
        bbox=None,
        source_scope=binding.source_scope,
    )


def ledger_events(instance: P2OcrIngestion, kind: str) -> list[dict]:
    return [event for event in instance.ledger_events() if event.get("event") == kind]


def record_from_receipt(receipt: OcrPageReceipt, *, request_id: str | None = None) -> ProductOcrSuccess:
    identity = receipt.identity
    return ProductOcrSuccess(
        record_id=str(uuid.uuid4()),
        document_id=identity.document_id,
        version_id=identity.version_id,
        page=identity.page,
        mode=identity.mode,
        input_sha256=identity.input_sha256,
        provider_request_id=request_id if request_id is not None else receipt.provider_request_id,
    )


# --------------------------------------------------------------------------- #
# 1. 计划：页/图分别计数、分片按产品上限
# --------------------------------------------------------------------------- #


def test_plan_counts_pages_and_images_with_tiles_within_product_limit() -> None:
    chosen = plan()
    assert chosen.pages == 10, "D07(8) + D08(2) 是页"
    assert chosen.images == 2, "D09/D10 是图"
    assert chosen.planned_calls == 12
    assert {doc.document_key: doc.planned_calls for doc in chosen.documents} == {
        "D07": 8,
        "D08": 2,
        "D09": 1,
        "D10": 1,
    }
    assert chosen.by_key["D10"].expected_mode == "table", "D10 是规则表格图（产品 looks_like_rule_table=True）"
    limit = int(ParseLimits().ocr_max_tiles)
    assert all(doc.tiles_per_page <= limit for doc in chosen.documents)
    payload = chosen.as_dict()
    assert payload["planned_calls"] == 12 and len(payload["documents"]) == 4
    assert all(len(doc["sha256"]) == 64 for doc in payload["documents"])


def test_plan_rejects_impossible_shapes() -> None:
    with pytest.raises(ValueError):
        plan(tiles_per_page=0)
    with pytest.raises(ValueError):
        plan(tiles_per_page=int(ParseLimits().ocr_max_tiles) + 1)
    with pytest.raises(ValueError):
        plan(("D07",), page_count=14)  # 单份资料 14 页 > 受控 13 次上限
    with pytest.raises(ValueError):
        OcrDocumentPlan(
            document_key="D09", path=FILES["D09"][0], file_kind="png", page_count=2, image_count=1
        )
    with pytest.raises(ValueError):
        OcrImportPlan(documents=(plan(("D09",)).documents[0], plan(("D09",)).documents[0]))


def test_transcripts_must_cover_exactly_the_planned_pages(tmp_path: Path) -> None:
    chosen = plan(("D07", "D09"))
    partial = transcripts(("D07", "D09"))
    partial["D07"] = OcrTranscript(
        document_key="D07", pages={page: lines for page, lines in list(partial["D07"].pages.items())[:-1]}
    )
    with pytest.raises(ValueError):
        P2OcrIngestion.isolated_mock(tmp_path / "missing", plan=chosen, transcripts=partial)
    extra = transcripts(("D07", "D09"))
    extra["D09"] = OcrTranscript(document_key="D09", pages={1: ("x",), 2: ("y",)})
    with pytest.raises(ValueError):
        P2OcrIngestion.isolated_mock(tmp_path / "extra", plan=chosen, transcripts=extra)
    with pytest.raises(ValueError):
        P2OcrIngestion.isolated_mock(tmp_path / "nocover", plan=chosen, transcripts={"D07": transcripts(("D07",))["D07"]})


def test_provider_client_uses_mock_transport_only(tmp_path: Path) -> None:
    instance = ingestion(tmp_path, ("D09",))
    assert isinstance(instance.transport, MockOcrTransport)
    assert instance.uses_mock_transport is True, "真实客户端只能接传输替身，不得接真实 HTTP 传输"
    assert instance.transport.requests == [] and instance.transport.violations == []


# --------------------------------------------------------------------------- #
# 2. 12 次 Mock 调用：计划=实际、页级预留/结算归属 ocr、回执可对回账本
# --------------------------------------------------------------------------- #


def test_twelve_mock_calls_match_plan_and_are_charged_to_ocr_center(tmp_path: Path) -> None:
    instance = ingestion(tmp_path)
    expected_calls = 0
    for document in instance.plan.documents:
        binding = bound(instance, document.document_key)
        mode = document.expected_mode
        for page in document.planned_pages:
            result = instance.gateway.recognize(page_input(binding, page, mode=mode), mode=mode)
            assert result.provider_request_id, "成功结果必须有供应商请求 id（usage 证据）"
            expected_calls += 1
    assert expected_calls == 12

    requests = instance.transport.requests
    assert len(requests) == instance.plan.planned_calls == 12
    assert instance.transport.violations == []
    per_document = {}
    for row in requests:
        per_document[row["document_id"]] = per_document.get(row["document_id"], 0) + 1
    assert sorted(per_document.values()) == [1, 1, 2, 8]
    assert [row["mode"] for row in requests].count("table") == 1, "只有 D10 是 table 模式"
    assert all(row["input_sha256"] == row["expected_input_sha256"] for row in requests)
    assert all(row["region"] == "ap-guangzhou" for row in requests)

    reserved = ledger_events(instance, "reserved")
    settled = ledger_events(instance, "result")
    assert len(reserved) == len(settled) == 12
    assert all(event["cost_center"] == "ocr" for event in reserved)
    assert all(event["kind"] == "ocr" and event["provider"] == "tencent" for event in reserved)
    assert {event["model"] for event in reserved} == {"GeneralAccurateOCR", "RecognizeTableAccurateOCR"}
    expected_cny = 11 * TEXT_PRICE + TABLE_PRICE
    assert round(sum(float(event["conservative_charge_cny"]) for event in settled), 8) == expected_cny
    summary = instance.ledger_summary()
    assert summary["center_accounted_cny"] == {"ocr": expected_cny}
    assert summary["stage_accounted_cny"] == pytest.approx(expected_cny)

    receipts = instance.receipts
    assert len(receipts) == 12
    reservation_ids = {event["reservation_id"] for event in reserved}
    for receipt in receipts:
        payload = receipt.as_dict()
        identity = payload["identity"]
        assert receipt.reservation_id in reservation_ids, "每页回执必须能对回账本预留行"
        assert receipt.ledger_request_sha256 == identity["request_sha256"]
        assert identity["provider"] == "tencent"
        assert identity["model"] in {"GeneralAccurateOCR", "RecognizeTableAccurateOCR"}
        assert identity["region"] == "ap-guangzhou"
        assert len(identity["input_sha256"]) == 64 and identity["page"] >= 1
        assert receipt.bound_cny == (TABLE_PRICE if identity["mode"] == "table" else TEXT_PRICE)
        assert receipt.charged_cny == receipt.bound_cny
        assert receipt.tiles == 1


# --------------------------------------------------------------------------- #
# 3. 合法缓存命中：身份一致 + 产品成功审计行 + 未过期，且不重复计费
# --------------------------------------------------------------------------- #


def test_same_identity_second_call_hits_legal_cache_without_new_charge(tmp_path: Path) -> None:
    instance = ingestion(tmp_path, ("D09",))
    binding = bound(instance, "D09")
    page = page_input(binding, 1)
    first = instance.gateway.recognize(page, mode="text")
    receipt = instance.receipts[-1]
    assert receipt.cache == CACHE_MISS

    summary = instance.finalize(
        document_id=binding.document_id,
        version_id=binding.version_id,
        records=[record_from_receipt(receipt)],
    )
    assert summary.pages[0]["admission"] == "admitted"
    assert len(instance.cache) == 1

    second = instance.gateway.recognize(page, mode="text")
    hit = instance.receipts[-1]
    assert second.text == first.text == "\n".join(transcripts(("D09",))["D09"].pages[1])
    assert hit.cache == CACHE_HIT and hit.status == "succeeded"
    assert hit.charged_cny == 0.0 and hit.bound_cny == TEXT_PRICE
    assert hit.reservation_id is None
    assert hit.provider_request_id == receipt.provider_request_id
    assert len(instance.transport.requests) == 1, "缓存命中不得再发一次供应商请求"
    assert len(ledger_events(instance, "reserved")) == 1, "缓存命中不得再预留一次"


# --------------------------------------------------------------------------- #
# 4. 缓存串用：不同文档 page1 / 同文档不同 version / 不同 input hash 一律拒绝
# --------------------------------------------------------------------------- #


def test_cache_reuse_across_documents_versions_and_tiles_is_rejected(tmp_path: Path) -> None:
    instance = ingestion(tmp_path, ("D09",), max_calls=13)
    first_binding = bound(instance, "D09")
    shared_bytes = b"identical-page-1-bytes"
    instance.gateway.recognize(page_input(first_binding, 1, content=shared_bytes), mode="text")
    receipt = instance.receipts[-1]
    instance.finalize(
        document_id=first_binding.document_id,
        version_id=first_binding.version_id,
        records=[record_from_receipt(receipt)],
    )
    assert len(instance.cache) == 1

    other_document = bound(instance, "D09")
    served = instance.gateway.recognize(
        page_input(other_document, 1, content=shared_bytes), mode="text"
    )
    cross_document = instance.receipts[-1]
    assert cross_document.cache == f"{CACHE_REJECTED}:{CACHE_SOURCE_IDENTITY_MISMATCH}"
    assert served.text == "\n".join(transcripts(("D09",))["D09"].pages[1]), "串用条目不得被当作结果返回"

    next_version = bound(
        instance, "D09", document_id=uuid.UUID(first_binding.document_id)
    )
    instance.gateway.recognize(page_input(next_version, 1, content=shared_bytes), mode="text")
    cross_version = instance.receipts[-1]
    assert cross_version.cache == f"{CACHE_REJECTED}:{CACHE_SOURCE_IDENTITY_MISMATCH}"

    # 同文档同版本但换了图块：缓存必须按 input hash 拒绝，而不是把旧图的结果当新图。
    new_tile_identity = OcrCallIdentity.of(
        document_id=first_binding.document_id,
        version_id=first_binding.version_id,
        page=1,
        mode="text",
        content=b"different-tile-bytes",
    )
    decision = instance.cache.lookup(new_tile_identity)
    assert decision.status == CACHE_REJECTED
    assert decision.reason == CACHE_INPUT_HASH_MISMATCH and decision.entry is None
    with pytest.raises(OcrIngestionError) as caught:  # 同页第二个 tile 也在发送前被上限挡住
        instance.gateway.recognize(
            page_input(first_binding, 1, content=b"different-tile-bytes"), mode="text"
        )
    assert caught.value.code == OCR_PAGE_CALL_LIMIT

    assert len(instance.transport.requests) == 3, "三次串用都必须真的发一次新调用"
    assert len(ledger_events(instance, "reserved")) == 3
    assert len(instance.cache) == 1, "被拒的串用不得写入缓存"


def test_forged_expired_and_simulated_cache_entries_are_refused(tmp_path: Path) -> None:
    instance = ingestion(tmp_path, ("D09",))
    binding = bound(instance, "D09")
    page = page_input(binding, 1)
    instance.gateway.recognize(page, mode="text")
    receipt = instance.receipts[-1]
    instance.finalize(
        document_id=binding.document_id,
        version_id=binding.version_id,
        records=[record_from_receipt(receipt)],
    )
    legal = instance.cache.as_payload()[0]
    assert legal["origin"] == "observed-provider-call" and legal["product_record_id"]

    now = datetime.now(timezone.utc)
    expired = {**legal, "expires_at": (now - timedelta(seconds=5)).isoformat()}
    simulated = {**legal, "origin": "simulated"}
    forged_provider = {**legal, "identity": {**legal["identity"], "provider": "not-tencent"}}
    forged_model = {**legal, "identity": {**legal["identity"], "model": "GeneralBasicOCR"}}
    forged_region = {**legal, "identity": {**legal["identity"], "region": "ap-shanghai"}}
    missing_provenance = {**legal, "product_record_id": ""}
    malformed = {**legal, "identity": {**legal["identity"], "input_sha256": "NOT-A-HASH"}}

    forged_cache = OcrResultCache.from_payload(
        [forged_provider, forged_model, forged_region, missing_provenance, malformed], now=lambda: now
    )
    assert len(forged_cache.quarantined) == 5, forged_cache.quarantined  # 伪造 provider/model/region + 缺来源 + 畸形 hash
    assert len(forged_cache) == 0, "伪造条目一条都不得进入可用缓存"
    expired_cache = OcrResultCache.from_payload([expired], now=lambda: now)
    simulated_cache = OcrResultCache.from_payload([simulated], now=lambda: now)
    identity = OcrCallIdentity.of(
        document_id=binding.document_id,
        version_id=binding.version_id,
        page=1,
        mode="text",
        content=bytes(page.content),
    )
    assert expired_cache.lookup(identity, now=now).reason == "cache_expired"
    assert simulated_cache.lookup(identity, now=now).reason == "cache_simulated"
    assert expired_cache.lookup(identity, now=now).status == CACHE_REJECTED

    # 被拒条目不得被当成结果返回：新实例带同一份被拒（过期）缓存，仍必须真的调用供应商。
    fresh = ingestion(tmp_path, ("D09",), cache=expired_cache)
    fresh_binding = bound(fresh, "D09")
    served = fresh.gateway.recognize(page_input(fresh_binding, 1), mode="text")
    assert served.text == "\n".join(transcripts(("D09",))["D09"].pages[1])
    assert fresh.receipts[-1].cache.startswith(CACHE_REJECTED)
    assert len(fresh.transport.requests) == 1


# --------------------------------------------------------------------------- #
# 5. 反例：未登记来源/未计划页/超单页上限在预留与发送前拒绝
# --------------------------------------------------------------------------- #


def test_unbound_source_and_unplanned_page_are_refused_before_reserve(tmp_path: Path) -> None:
    instance = ingestion(tmp_path, ("D09",))
    unbound = OCRInput(content=b"x", mime_type="image/png", page=1, source_scope="f" * 64)
    with pytest.raises(OcrIngestionError) as caught:
        instance.gateway.recognize(unbound, mode="text")
    assert caught.value.code == OCR_SOURCE_UNBOUND
    binding = bound(instance, "D09")
    with pytest.raises(OcrIngestionError) as caught:
        instance.gateway.recognize(page_input(binding, 3), mode="text")
    assert caught.value.code == OCR_PAGE_NOT_PLANNED
    assert instance.transport.requests == []
    assert ledger_events(instance, "reserved") == []

    instance.gateway.recognize(page_input(binding, 1), mode="text")
    with pytest.raises(OcrIngestionError) as caught:
        instance.gateway.recognize(page_input(binding, 1, content=b"second-tile"), mode="text")
    assert caught.value.code == OCR_PAGE_CALL_LIMIT
    assert len(instance.transport.requests) == 1
    assert len(ledger_events(instance, "reserved")) == 1


def test_page_failure_stops_later_pages(tmp_path: Path) -> None:
    instance = ingestion(tmp_path, ("D07",))
    binding = bound(instance, "D07")
    instance.transport.fail_on(2, mode="unavailable")
    for page in range(1, 3):
        if page == 2:
            with pytest.raises(OCRUnavailable):
                instance.gateway.recognize(page_input(binding, page), mode="text")
        else:
            instance.gateway.recognize(page_input(binding, page), mode="text")
    with pytest.raises(OcrIngestionError) as caught:
        instance.gateway.recognize(page_input(binding, 3), mode="text")
    assert caught.value.code == "OCR_INGESTION_STOPPED"
    assert len(instance.transport.requests) == 2, "失败后不得继续下一页"
    reserved = ledger_events(instance, "reserved")
    assert len(reserved) == 2
    failed = [item for item in instance.receipts if item.status == "failed"]
    assert len(failed) == 1 and failed[0].error_code == "OCR_UNAVAILABLE"
    assert failed[0].charged_cny == TEXT_PRICE, "失败页按固定价保守留账，不能清零"
    assert instance.stopped and instance.stop_code == "OCR_UNAVAILABLE"


def test_budget_shortage_stops_before_send(tmp_path: Path) -> None:
    instance = ingestion(tmp_path, ("D07",), stage_limit_cny=1.0)
    binding = bound(instance, "D07")
    instance.gateway.recognize(page_input(binding, 1), mode="text")
    instance.gateway.recognize(page_input(binding, 2), mode="text")
    with pytest.raises(OCRBudgetRefused):
        instance.gateway.recognize(page_input(binding, 3), mode="text")
    assert len(instance.transport.requests) == 2
    assert len(ledger_events(instance, "reserved")) == 2
    refused = instance.receipts[-1]
    assert refused.status == "refused" and refused.charged_cny == 0.0
    assert refused.reservation_id is None
    assert instance.ledger_summary()["center_accounted_cny"] == {"ocr": 1.0}


def test_missing_usage_and_empty_text_never_count_as_success(tmp_path: Path) -> None:
    no_usage = ingestion(tmp_path, ("D09",))
    binding = bound(no_usage, "D09")
    no_usage.transport.drop_request_id = True
    with pytest.raises(OcrIngestionError) as caught:
        no_usage.gateway.recognize(page_input(binding, 1), mode="text")
    assert caught.value.code == OCR_USAGE_MISSING
    receipt = no_usage.receipts[-1]
    assert receipt.status == "invalid_output" and receipt.error_code == OCR_USAGE_MISSING
    assert receipt.charged_cny == TEXT_PRICE, "缺 usage 也不得释放已预留的固定价"
    assert no_usage.stopped
    summary = no_usage.finalize(
        document_id=binding.document_id, version_id=binding.version_id, records=[]
    )
    assert summary.pages[0]["source"] == "failed"
    assert summary.pages[0]["error_code"] == OCR_USAGE_MISSING
    assert len(no_usage.cache) == 0

    empty = ingestion(tmp_path, ("D09",))
    empty_binding = bound(empty, "D09")
    empty.transport.empty_text = True
    with pytest.raises(OcrIngestionError) as caught:
        empty.gateway.recognize(page_input(empty_binding, 1), mode="text")
    assert caught.value.code == OCR_EMPTY_RESULT
    assert empty.receipts[-1].status == "invalid_output"
    assert empty.stopped and len(empty.cache) == 0


# --------------------------------------------------------------------------- #
# 6. 缓存准入只认产品成功审计行（迟到/丢弃结果不得复活）
# --------------------------------------------------------------------------- #


def test_cache_admission_requires_product_success_record(tmp_path: Path) -> None:
    instance = ingestion(tmp_path, ("D09",))
    binding = bound(instance, "D09")
    instance.gateway.recognize(page_input(binding, 1), mode="text")
    receipt = instance.receipts[-1]
    legal = record_from_receipt(receipt)
    assert legal.has_usage

    missing = instance.finalize(
        document_id=binding.document_id, version_id=binding.version_id, records=[]
    )
    assert missing.pages[0]["admission"] == "rejected:cache_provenance_missing"
    assert len(instance.cache) == 0

    mismatched = instance.finalize(
        document_id=binding.document_id,
        version_id=binding.version_id,
        records=[replace_hash(legal)],
    )
    assert mismatched.pages[0]["admission"] == f"rejected:{CACHE_INPUT_HASH_MISMATCH}"
    assert len(instance.cache) == 0

    no_usage = instance.finalize(
        document_id=binding.document_id,
        version_id=binding.version_id,
        records=[record_from_receipt(receipt, request_id="")],
    )
    assert no_usage.pages[0]["admission"] == "rejected:cache_provenance_missing"
    assert len(instance.cache) == 0

    admitted = instance.finalize(
        document_id=binding.document_id, version_id=binding.version_id, records=[legal]
    )
    assert admitted.pages[0]["admission"] == "admitted"
    assert len(instance.cache) == 1
    assert admitted.plan_matches_provider_requests is True
    assert admitted.provider_requests == 1 and admitted.attempts == 1
    assert admitted.charged_cny == TEXT_PRICE and admitted.bound_cny == TEXT_PRICE


def replace_hash(record: ProductOcrSuccess) -> ProductOcrSuccess:
    """把审计行的 input hash 改成另一张图（模拟"同页不同图"的串用）：必须拒绝。"""
    return ProductOcrSuccess(
        record_id=record.record_id,
        document_id=record.document_id,
        version_id=record.version_id,
        page=record.page,
        mode=record.mode,
        input_sha256="a" * 64,
        provider_request_id=record.provider_request_id,
    )
