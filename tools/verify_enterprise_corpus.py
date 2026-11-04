#!/usr/bin/env python
r"""企业模拟资料库离线校验（零真实调用，可证明）。

校验四件事：
1. 完整性：manifest 里每个文件都在、哈希一致。
2. 可解析与上限：用产品自身的解析器（parse_document）跑一遍；默认 ParseLimits 即产品的
   20MB / 50 页 / 5000 行 / 2000 万像素口径，正常资料必须过、boundary 必须按预期被拒。
3. 事实一致性：questions.json 每题的期望值，必须能在其 expected_sources 指向的文件正文里
   找到（字符串或等值数字）；no_answer 题的实体必须确实不在台账里。
4. 无网络：全程把 socket.socket 替换为抛异常的实现，任何真实调用企图都会直接失败并计入报告。

用法：
    .\.venv\Scripts\python.exe -B tools\verify_enterprise_corpus.py --corpus tmp\corpus_check1
    .\.venv\Scripts\python.exe -B tools\verify_enterprise_corpus.py --determinism   # 两次生成比对哈希
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.ingestion.parsers import ParseError, ParseLimitError, ParseLimits, ParseServices, parse_document  # noqa: E402

NETWORK_ATTEMPTS: list[str] = []


class _NoNetwork(socket.socket):
    def __init__(self, *args, **kwargs) -> None:
        NETWORK_ATTEMPTS.append("socket")
        raise RuntimeError("校验器禁止任何网络访问（真实模型/OCR 调用）")


def block_network() -> None:
    socket.socket = _NoNetwork  # type: ignore[misc]
    socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("网络被禁止"))  # type: ignore[assignment]


block_network()

KIND_BY_SUFFIX = {".xlsx": "xlsx", ".docx": "docx", ".pdf": "pdf", ".png": "png", ".jpg": "jpg", ".jpeg": "jpeg"}
EXPECTED_LIMIT_FAILURES = {"B02": "页数", "B03": None, "B04": "行数", "B05": None, "B06": None, "B07": None, "B08": None, "B09": None, "B01": None}
BOUNDARY_ALLOWED_ERRORS = (ParseLimitError, ParseError, Exception)

NUM = re.compile(r"\d+(?:\.\d+)?")


def normalize(text: str) -> str:
    return re.sub(r"[\s　,，。；;：:、（）()【】\[\]\"'「」/\\\-—–_]+", "", text)


def numbers(text: str) -> set[float]:
    out: set[float] = set()
    for token in NUM.findall(text):
        try:
            out.add(float(token))
        except ValueError:
            pass
    return out


UNIT_CHARS = set("元％%天日分米面张个个件条把根台卷瓶罐箱组月每两至到以下第时小时工资号区位层路店铺人次数岁学分档级")


def value_matches(expected: str, haystack_norm: str, haystack_numbers: set[float]) -> bool:
    """两级判定：原文片段命中，或“纯数字+单位”写法命中。

    含描述性文字（去掉数字与单位后仍≥3 个字符）的期望值只允许原文命中，
    避免被表格里大量无关数字兜底通过。
    """
    norm = normalize(expected)
    if norm and norm in haystack_norm:
        return True
    residue = "".join(ch for ch in norm if not ch.isdigit() and ch not in UNIT_CHARS)
    if len(residue) >= 3:
        return False
    nums = {float(t) for t in NUM.findall(expected)}
    return bool(nums) and nums <= haystack_numbers


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_corpus(corpus: Path, manifest: dict) -> tuple[dict[str, dict], list[dict]]:
    """用产品解析器读取每份文件，返回 {code: {text, units, error}} 与解析层结论。"""
    results: dict[str, dict] = {}
    rows: list[dict] = []
    services = ParseServices(limits=ParseLimits())
    for entry in manifest["files"]:
        code, path = entry["code"], corpus / entry["path"]
        kind = KIND_BY_SUFFIX[path.suffix.lower()]
        record = {"units": 0, "text": "", "error": None, "kind": kind}
        try:
            units = list(parse_document(path, kind, ParseServices(limits=services.limits)))
            record["units"] = len(units)
            record["text"] = "\n".join(
                " ".join(part for part in [
                    u.text,
                    " ".join(f"{k}={v}" for k, v in (u.fields or {}).items()),
                    " ".join(str(v) for v in (u.locator or {}).values()),
                    u.sheet or "",
                ] if part)
                for u in units
            )
            record["kinds"] = sorted({u.kind for u in units})
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        results[code] = record
        rows.append({
            "code": code, "group": entry["group"], "kind": kind, "units": record["units"],
            "error": record["error"], "purpose_ok": bool(entry.get("purpose")),
        })
    return results, rows


def check_files(corpus: Path, manifest: dict, parse_results: dict, rows: list[dict]) -> list[dict]:
    findings: list[dict] = []
    by_code = {r["code"]: r for r in rows}
    for entry in manifest["files"]:
        path = corpus / entry["path"]
        if not path.is_file():
            findings.append({"level": "FAIL", "code": entry["code"], "check": "missing_file", "detail": entry["path"]})
            continue
        if sha256(path) != entry["sha256"]:
            findings.append({"level": "FAIL", "code": entry["code"], "check": "sha_mismatch", "detail": entry["path"]})
        if entry["bytes"] > 20 * 1024 * 1024 and entry.get("expected_rejection") != "upload":
            findings.append({"level": "FAIL", "code": entry["code"], "check": "over_20mb", "detail": str(entry["bytes"])})
        if entry["group"] == "scan" and entry["kind"] == "image" and entry.get("pixels", 0) > 20_000_000:
            findings.append({"level": "FAIL", "code": entry["code"], "check": "over_20mp", "detail": str(entry["pixels"])})

    for entry in manifest["files"]:
        code = entry["code"]
        record = parse_results[code]
        if entry["group"] == "boundary":
            continue
        if entry["group"] == "scan":
            continue
        if record["error"]:
            findings.append({"level": "FAIL", "code": code, "check": "parse_error", "detail": record["error"]})
        elif record["units"] <= 0:
            findings.append({"level": "FAIL", "code": code, "check": "zero_units", "detail": "解析成功但 0 个来源单元"})

    # 扫描件必须无文字层（这样才真正考验 OCR）
    for entry in manifest["files"]:
        if entry["kind"] != "scan_pdf":
            continue
        import pdfplumber

        with pdfplumber.open(corpus / entry["path"]) as pdf:
            has_text = any((page.extract_text() or "").strip() for page in pdf.pages)
        findings.append({"level": "INFO" if not has_text else "FAIL", "code": entry["code"],
                         "check": "scan_has_no_text_layer", "detail": f"pages={len(pdf.pages)} text_layer={has_text}"})

    # 边界样本：按 manifest 标注的预期拒绝层判定
    for entry in manifest["files"]:
        if entry["group"] != "boundary":
            continue
        record = parse_results[entry["code"]]
        layer = entry.get("expected_rejection", "none")
        failed = record["error"] is not None
        if layer == "parse" and not failed:
            findings.append({"level": "FAIL", "code": entry["code"], "check": "should_fail_in_parser", "detail": f"units={record['units']}"})
        if layer == "none" and failed:
            findings.append({"level": "FAIL", "code": entry["code"], "check": "should_parse_cleanly", "detail": record["error"]})
        if layer == "upload":
            findings.append({"level": "INFO", "code": entry["code"], "check": "upload_layer_rejection",
                             "detail": f"bytes={entry['bytes']}，解析层可通过 {not failed}；应由 20MB 上传校验拦下"})
        if layer == "ocr":
            findings.append({"level": "INFO", "code": entry["code"], "check": "image_requires_real_ocr", "detail": record["error"] or f"units={record['units']}"})
    return findings


def check_facts(corpus: Path, manifest: dict, parse_results: dict, questions: list[dict]) -> list[dict]:
    findings: list[dict] = []
    checked = 0
    for q in questions:
        if q["group"] not in {"exact", "stale", "semantic", "legal", "rrem", "conflict"}:
            continue
        codes = [s.get("file") for s in q.get("expected_sources", []) if s.get("file") and s.get("file") in parse_results]
        if not codes:
            findings.append({"level": "FAIL", "code": q["id"], "check": "source_code_not_in_corpus", "detail": f"来源代码不存在：{q.get('expected_sources')}"})
            continue
        merged_norm = normalize("\n".join(parse_results[c]["text"] for c in codes))
        merged_nums = set().union(*(numbers(parse_results[c]["text"]) for c in codes))
        for expected in q["expected_values"]:
            checked += 1
            if not value_matches(expected, merged_norm, merged_nums):
                findings.append({"level": "FAIL", "code": q["id"], "check": "fact_not_in_source",
                                 "detail": f"期望「{expected}」未出现在 {codes}｜题面：{q['question'][:40]}"})
    findings.append({"level": "INFO", "code": "summary", "check": "fact_checks", "detail": f"{checked} 项期望值已核对"})

    # 无答案题的实体不得出现在台账中
    ledger_norm = normalize("\n".join(parse_results[c]["text"] for c in ("E01", "E02") if c in parse_results))
    for entity in ["星河湾店", "荧光棒", "共享充电宝柜机"]:
        if normalize(entity) in ledger_norm:
            findings.append({"level": "FAIL", "code": "no_answer", "check": "entity_leaked_into_ledger", "detail": entity})
    return findings


def run_determinism() -> int:
    dirs = []
    try:
        for _ in range(2):
            directory = Path(tempfile.mkdtemp(prefix="enterprise-corpus-"))
            subprocess.run([sys.executable, "-B", str(ROOT / "tools" / "build_enterprise_corpus.py"),
                            "--output", str(directory)], check=True, capture_output=True)
            dirs.append(directory)
        first = {p.relative_to(dirs[0]).as_posix(): sha256(p) for p in sorted(dirs[0].rglob("*")) if p.is_file()}
        second = {p.relative_to(dirs[1]).as_posix(): sha256(p) for p in sorted(dirs[1].rglob("*")) if p.is_file()}
        diff = [k for k in set(first) | set(second) if first.get(k) != second.get(k)]
        print(json.dumps({"files_run1": len(first), "files_run2": len(second), "hash_diff": diff[:10],
                          "deterministic": not diff}, ensure_ascii=False))
        return 0 if not diff else 1
    finally:
        for directory in dirs:
            import shutil

            shutil.rmtree(directory, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线校验企业模拟资料库（不调用网络）")
    parser.add_argument("--corpus", help="语料目录")
    parser.add_argument("--determinism", action="store_true", help="两次生成并比对哈希")
    args = parser.parse_args(argv)

    if args.determinism:
        return run_determinism()
    if not args.corpus:
        parser.error("--corpus 必填（或使用 --determinism）")

    corpus = Path(args.corpus)
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    questions = json.loads((corpus / "questions.json").read_text(encoding="utf-8"))["questions"]

    parse_results, rows = parse_corpus(corpus, manifest)
    findings = check_files(corpus, manifest, parse_results, rows)
    findings += check_facts(corpus, manifest, parse_results, questions)

    failures = [f for f in findings if f["level"] == "FAIL"]
    scans = [e["code"] for e in manifest["files"] if e["group"] == "scan"]
    report = {
        "files": len(manifest["files"]),
        "questions": len(questions),
        "parse_units_total": sum(r["units"] for r in parse_results.values()),
        "failures": len(failures),
        "findings_sample": failures[:40],
        "network_attempts": len(NETWORK_ATTEMPTS),
        "unverified_ocr_files": scans,
        "unverified_note": "scan/ 组的识别质量需真实 OCR 才能验证，本次未调用；仅验证其为无文字层的图像 PDF 与合规尺寸图片。",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures or NETWORK_ATTEMPTS else 0


if __name__ == "__main__":
    raise SystemExit(main())
