"""T204 verifier probes (read-only): fixture shape, D10 mode, shared-ledger recon,
cache identity matrix (seven-field identity), forged/expired/simulated payload handling.

Independent of T204's own tests: uses only product modules + p2_ingestion public API.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from PIL import Image
import pdfplumber

from mktkb.ingestion.parsers.image import looks_like_rule_table, image_is_near_blank
from mktkb.evaluation.p2_ingestion import OcrCallIdentity, OcrResultCache
from mktkb.providers.types import OCRPageResult

out = {}

# ---- 1. fixture shapes / D10 mode (product rule, not T204's plan field) ----
base = ROOT / "fixtures" / "acceptance" / "normal"
shapes = {}
for name in ["D09_物料领用通知.png", "D10_盘点通知.jpg"]:
    with Image.open(base / name) as im:
        im.load()
        shapes[name] = {
            "size": list(im.size),
            "looks_like_rule_table": bool(looks_like_rule_table(im)),
            "near_blank": bool(image_is_near_blank(im)),
        }
for name in ["D07_活动申请扫描件.pdf", "D08_仓库安全须知扫描件.pdf"]:
    with pdfplumber.open(str(base / name)) as doc:
        shapes[name] = {
            "pages": len(doc.pages),
            "text_layer_chars": [len((p.extract_text() or "").strip()) for p in doc.pages],
        }
out["fixture_shapes"] = shapes
out["planned_calls_recomputed"] = {
    "D07": 8, "D08": 2, "D09": 1, "D10": 1, "total": 12,
    "price": {"text": 0.5, "table": 0.15},
    "if_D10_table": round(11 * 0.5 + 1 * 0.15, 8),
    "if_all_text": round(12 * 0.5, 8),
}

# ---- 2. shared ledger recon (read-only; T204 must not add rows) ----
ledger = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
reserved = results = 0
centers = {}
ocr_pages = []
for line in ledger.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    row = json.loads(line)
    if row.get("event") == "reserved":
        reserved += 1
        key = row.get("cost_center") or row.get("kind")
        centers[key] = centers.get(key, 0) + 1
    elif row.get("event") == "result":
        results += 1
out["shared_ledger"] = {"reserved": reserved, "result": results, "centers": centers}

# ---- 3. seven-field identity / cache matrix (hand-built, no T204 test helpers) ----
content = b"same-tile-bytes"
def ident(**kw):
    args = dict(document_id="doc-A", version_id="ver-1", page=1, mode="text", content=content)
    args.update(kw)
    return OcrCallIdentity.of(**args)

base_identity = ident()
cache = OcrResultCache(ttl_seconds=600)
cache.admit(
    base_identity,
    OCRPageResult(text="tile text", table_rows=(), provider_request_id="req-1"),
    product_record_id="rec-1",
)
matrix = {}
cases = {
    "same_identity": ident(),
    "other_document_page1_same_bytes": ident(document_id="doc-B"),
    "same_document_new_version_same_bytes": ident(version_id="ver-2"),
    "same_page_other_tile_bytes": ident(content=b"other-tile-bytes"),
    "same_document_page2": ident(page=2),
    "same_page_table_mode": ident(mode="table"),
}
for label, identity in cases.items():
    decision = cache.lookup(identity)
    matrix[label] = {"status": decision.status, "reason": decision.reason,
                     "has_entry": decision.entry is not None}
out["cache_matrix"] = matrix

# identity field guards (forged provider/model/region / bad page)
guards = {}
for label, kwargs in {
    "forged_provider": {"provider": "not-tencent"},
    "forged_model": {"model": "GeneralBasicOCR"},
    "forged_region": {"region": "ap-shanghai"},
    "page_zero": {"page": 0},
}.items():
    try:
        OcrCallIdentity(
            document_id="doc-A", version_id="ver-1", page=kwargs.get("page", 1),
            mode="text", input_sha256="a" * 64, request_sha256="b" * 64,
            provider=kwargs.get("provider", "tencent"),
            model=kwargs.get("model", "GeneralAccurateOCR"),
            region=kwargs.get("region", "ap-guangzhou"),
        )
        guards[label] = "ACCEPTED"
    except (ValueError, TypeError) as exc:
        guards[label] = f"rejected:{type(exc).__name__}"
out["identity_guards"] = guards

# forged / expired / simulated payload handling through the public restore path
legal = cache.as_payload()
now_payload = legal[0]
forged = json.loads(json.dumps(now_payload))
forged["identity"]["provider"] = "not-tencent"
expired = json.loads(json.dumps(now_payload))
expired["expires_at"] = "2000-01-01T00:00:00.000+00:00"
simulated = json.loads(json.dumps(now_payload))
simulated["origin"] = "simulated"
restored = {}
for label, payload in {"forged_provider": forged, "expired": expired, "simulated": simulated}.items():
    cache2 = OcrResultCache.from_payload([payload])
    decision = cache2.lookup(base_identity)
    restored[label] = {
        "quarantined": list(cache2.quarantined),
        "usable_entries": len(cache2),
        "lookup_status": decision.status,
        "lookup_reason": decision.reason,
    }
out["restored_payloads"] = restored

# ---- 4. raw ledger recon of the probe's isolated ledgers (if the probe was run) ----
def recon(ledger_path):
    reserved = results = 0
    centers = set()
    models = {}
    settled = {}
    unmatched = 0
    for line in Path(ledger_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("event") == "reserved":
            reserved += 1
            centers.add(row.get("cost_center"))
            models[row.get("model")] = models.get(row.get("model"), 0) + 1
        elif row.get("event") == "result":
            results += 1
            settled[row.get("reservation_id")] = row
    total = 0.0
    for line in Path(ledger_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("event") != "reserved":
            continue
        hit = settled.get(row.get("reservation_id"))
        if hit is None:
            unmatched += 1
        else:
            total += float(hit.get("conservative_charge_cny") or 0.0)
    return {
        "reserved": reserved, "result": results, "centers": sorted(c for c in centers if c),
        "models": models, "charged_sum_cny": round(total, 8),
        "unmatched_reservations": unmatched,
        "distinct_request_sha256": len({
            json.loads(line).get("request_sha256")
            for line in Path(ledger_path).read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("event") == "reserved"
        }),
    }

scratch = ROOT / "backend" / ".pytest-tmp" / "p2-t204-evidence"
ledgers = {
    "A_single_document_12": scratch / "a" / "p2-ocr-ledger.jsonl",
    "B_product_chain_12": scratch / "b" / "ocr" / "p2-ocr-ledger.jsonl",
    "C_cross_use_3": scratch / "c" / "ocr" / "p2-ocr-ledger.jsonl",
    "C_retry_9": scratch / "c" / "ocr-d07" / "p2-ocr-ledger.jsonl",
    "C_cancel_3": scratch / "c" / "ocr-cancel_version" / "p2-ocr-ledger.jsonl",
    "C_delete_3": scratch / "c" / "ocr-delete_document" / "p2-ocr-ledger.jsonl",
}
out["probe_ledger_recon"] = {
    label: (recon(p) if p.exists() else "probe scratch missing (run probe_t204.py)")
    for label, p in ledgers.items()
}

print(json.dumps(out, ensure_ascii=False, indent=1))
