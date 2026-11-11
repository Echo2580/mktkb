"""T207-FIX-LIVECAP 探针：无 OCR 计划的 embedding POST 数 / 降级标记（修复前后）+ fail-closed。

零真实调用：全部出站由 httpx.MockTransport 接住（外层另有 socket 闸门不参与，因为这里是
独立进程脚本）；账本/预算/GO 全在系统临时目录，跑完即删；不读 .env / H1 / H2。

"修复前"用 monkeypatch 把 p2_live.resolve_request_ceiling 退回旧语义
（effective = plan.reserve_peak_cny，无 fail-closed），其余代码/transport/计划完全一致。

用法（仓库根目录）：
    .venv\\Scripts\\python.exe -B -X utf8 docs\\reports\\OBS-EVAL\\P2\\T207-FIX-LIVECAP\\evidence\\probe-livecap.py --out ...
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[6]
for extra in (ROOT / "backend" / "src", ROOT / "backend" / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from mktkb.evaluation import p2_live  # noqa: E402
from mktkb.rag.providers import post_counters, reset_post_counters  # noqa: E402


def _load_test_helpers() -> Any:
    """复用本包新增回归的同一份计划/数据集/transport 构造（避免第三份副本）。"""
    path = ROOT / "backend" / "tests" / "evaluation" / "test_p2_live_request_ceiling.py"
    spec = importlib.util.spec_from_file_location("p2_ceiling_helpers", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Monkey:
    def __init__(self) -> None:
        self._saved: list[tuple[Any, str, Any]] = []
        self._env: list[tuple[str, str | None]] = []

    def setattr(self, obj: Any, name: str, value: Any) -> None:
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def setenv(self, name: str, value: str) -> None:
        import os

        self._env.append((name, os.environ.get(name)))
        os.environ[name] = value

    def undo(self) -> None:
        import os

        for obj, name, value in reversed(self._saved):
            setattr(obj, name, value)
        for name, value in reversed(self._env):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _legacy_resolver(rag_config: Any, *, plan_peak_cny: float, authorization_cny: float):
    """旧接线：effective 就是计划串行峰值（不看 provider 单次预留、不 fail-closed）。"""
    return p2_live.RequestCeiling(
        plan_peak_cny=float(plan_peak_cny),
        provider_bounds_cny={},
        authorization_cny=float(authorization_cny),
        effective_cny=float(plan_peak_cny),
    )


def _run_case(helpers: Any, *, with_ocr: bool, max_request_cny: float, legacy: bool) -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix="p2-livecap-"))
    monkey = _Monkey()
    saved = p2_live.resolve_request_ceiling
    if legacy:
        monkey.setattr(p2_live, "resolve_request_ceiling", _legacy_resolver)
    try:
        env = helpers._prepare(
            tmp, monkey, with_ocr=with_ocr, max_request_cny=max_request_cny
        )
        embedding_calls: list[dict] = []
        rerank_calls: list[dict] = []
        ocr_calls: list[dict] = []
        chat = helpers._UsageChatBackend(
            behaviors=(helpers.ChatBehavior(answer="位置：B区1号货架第二层"),)
        )
        reset_post_counters()
        payload: dict[str, Any] = {
            "plan": "with_ocr" if with_ocr else "no_ocr",
            "go_max_request_cny": float(max_request_cny),
            "wiring": "legacy(plan_peak)" if legacy else "fixed(effective)",
        }
        try:
            result, build, gate = helpers._run(
                env,
                tmp,
                embedding_calls=embedding_calls,
                rerank_calls=rerank_calls,
                ocr_calls=ocr_calls,
                chat=chat,
            )
        except p2_live.P2LiveConfigError as exc:
            payload.update(
                {
                    "refused": True,
                    "refused_code": str(exc.code),
                    "refused_detail": str(exc.detail),
                    "embedding_posts": len(embedding_calls),
                    "rerank_posts": len(rerank_calls),
                    "ocr_posts": len(ocr_calls),
                    "chat_posts": int(chat.call_count),
                    "ledger_reserved": 0,
                    "degraded": None,
                }
            )
            payload["ledger_reserved"] = len(
                [row for row in helpers._events(env.ledger) if row.get("event") == "reserved"]
            )
            return payload
        status = build.adapter.index_status()
        payload.update(
            {
                "refused": False,
                "run_status": result.status,
                "stop_code": result.stop_code,
                "requests_sent": int(result.requests_sent),
                "embedding_posts": len(embedding_calls),
                "rerank_posts": len(rerank_calls),
                "ocr_posts": len(ocr_calls),
                "chat_posts": int(chat.call_count),
                "rag_post_attempts": post_counters()["attempts"],
                "index_status": {
                    "ready": status.get("ready"),
                    "degraded": list(status.get("degraded") or ()),
                    "error_code": status.get("error_code"),
                    "documents": status.get("documents"),
                    "chunks": status.get("chunks"),
                },
                "request_ceiling": build.wiring.request_ceiling,
                "effective_max_request_cny": (build.wiring.request_ceiling or {}).get(
                    "effective_max_request_cny"
                ),
                "go_authorization_cny": float(gate.authorization.max_request_cny),
            }
        )
        # 产物只留计数：删掉隔离运行目录（业务库/索引/trace 全在临时目录）。
        shutil.rmtree(tmp, ignore_errors=True)
        return payload
    finally:
        p2_live.resolve_request_ceiling = saved
        monkey.undo()
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T207-FIX-LIVECAP 零调用探针")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    helpers = _load_test_helpers()
    report: dict[str, Any] = {
        "schema": "t207-fix-livecap-probe/v1",
        "real_calls": 0,
        "cases": [
            _run_case(helpers, with_ocr=False, max_request_cny=0.5, legacy=True),
            _run_case(helpers, with_ocr=False, max_request_cny=0.5, legacy=False),
            _run_case(helpers, with_ocr=False, max_request_cny=0.02, legacy=False),
            _run_case(helpers, with_ocr=True, max_request_cny=0.5, legacy=True),
            _run_case(helpers, with_ocr=True, max_request_cny=0.5, legacy=False),
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
