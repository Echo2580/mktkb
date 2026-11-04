"""T09-D1 证据落盘：唯一新增证据目录、JSON 写入与环境事实。

本模块只负责把**实际执行结果**写成证据，不生成任何未执行过的结论。
证据根目录固定为 ``docs/evidence/T09/D1``（开工前已核对不存在，由本轮创建）。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"
FIXTURES = ROOT / "fixtures" / "acceptance"


def _resolve_evidence_root() -> Path:
    """证据根目录：默认 T09/D1；用 ``T09_EVIDENCE_ROOT`` 指向别轮目录（如 T09/D2），避免覆盖旧证据。"""
    override = os.environ.get("T09_EVIDENCE_ROOT")
    if not override:
        return ROOT / "docs" / "evidence" / "T09" / "D1"
    path = Path(override)
    return path if path.is_absolute() else ROOT / path


EVIDENCE_ROOT = _resolve_evidence_root()
MANIFEST_PATH = FIXTURES / "manifest.json"
QUESTIONS_PATH = FIXTURES / "questions.json"

LAYER = "L"
PROVIDER_TAG = "L/controlled:EvidenceEchoGateway + OCRTranscriptStandIn（真实解析器/SQLite/HTTP/worker/检索，替身只替代模型文本与 OCR 识别结果）"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump_json(relative_path: str | Path, payload) -> Path:
    """写入证据 JSON；不覆盖既有内容由调用方按 label 唯一化保证。"""
    target = EVIDENCE_ROOT / Path(relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False, default=str) + "\n"
    target.write_text(text, encoding="utf-8")
    return target


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_manifest() -> dict:
    return load_json(MANIFEST_PATH)


def load_questions() -> list[dict]:
    return load_json(QUESTIONS_PATH)["questions"]


def package_versions(names: tuple[str, ...] = ("fastapi", "sqlalchemy", "pydantic", "pytest", "openpyxl", "pdfplumber", "pypdfium2", "Pillow", "jieba", "httpx")) -> dict:
    from importlib import metadata

    versions = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:  # pragma: no cover - 环境缺包时如实记录
            versions[name] = "not-installed"
    return versions


def environment(*, basetemp: str | None = None) -> dict:
    """本轮运行环境事实；模型/OCR 服务侧一律未配置真实值（见 b0.make_settings 的假密钥）。"""
    manifest = load_manifest()
    return {
        "layer": LAYER,
        "provider": PROVIDER_TAG,
        "recorded_at": now_iso(),
        "workspace": str(ROOT),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "packages": package_versions(),
        "pytest_basetemp": basetemp,
        "fixtures": {
            "manifest_sha256": sha256_path(MANIFEST_PATH),
            "questions_sha256": sha256_path(QUESTIONS_PATH),
            "manifest_built_at": manifest.get("built_at"),
            "questions_version": load_json(QUESTIONS_PATH).get("version"),
        },
        "real_calls": {"model": 0, "ocr": 0, "note": "本轮任务单禁止真实调用；详见 netguard 断言"},
        "git": {"initialized": (ROOT / ".git").exists(), "note": "本轮不执行任何 Git 操作"},
    }


def env_fingerprint_for_report() -> dict:
    """去掉可变时间戳后的环境摘要，便于逐题记录复用。"""
    env = environment()
    env.pop("recorded_at", None)
    return env


def git_head() -> str | None:
    if not (ROOT / ".git").exists():
        return None
    try:
        output = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True, timeout=20
        )
    except Exception:  # pragma: no cover - 无 git 或权限问题
        return None
    return output.stdout.strip() or None


def os_environ_names(prefixes: tuple[str, ...] = ("MKTKB_", "DEEPSEEK", "TENCENT", "OCR_", "MODEL_")) -> list[str]:
    """只返回可能影响配置的环境变量**名字**，绝不返回值。"""
    names = []
    for key in os.environ:
        if any(key.startswith(prefix) for prefix in prefixes):
            names.append(key)
    return sorted(names)
