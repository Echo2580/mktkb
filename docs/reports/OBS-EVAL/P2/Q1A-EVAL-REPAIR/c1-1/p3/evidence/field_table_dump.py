"""C1-P3 证据：导出字段表 / 固定码表 / 公开摘要键（机器可读，无秘密）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[8]
if str(ROOT / "backend" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation.p2_evidence_snapshot_v03 import (  # noqa: E402
    CONTRACT_VERSION,
    ENTITY_CODES,
    FAIL_CLOSED_CODES,
    PUBLIC_SUMMARY_KEYS,
    RECORD_IDENTITY_CODES,
    SNAPSHOT_SCHEMA_VERSION,
    TEMPORAL_CODES,
    EMPTY_USE_CODES,
    identity_field_table,
)


def run() -> dict:
    rows = identity_field_table()
    return {
        "schema_version": "c1p3-field-table/v0.1",
        "contract_version": CONTRACT_VERSION,
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "field_count": len(rows),
        "required_count": sum(1 for row in rows if row["required"]),
        "nullable_count": sum(1 for row in rows if row["nullable"]),
        "top_level_paths": sorted(
            {row["path"].split(".", 1)[0].split("[", 1)[0] for row in rows}
        ),
        "fields": list(rows),
        "fail_closed_codes": dict(sorted(FAIL_CLOSED_CODES.items())),
        "fail_closed_code_count": len(FAIL_CLOSED_CODES),
        "public_summary_keys": list(PUBLIC_SUMMARY_KEYS),
        "public_summary_key_count": len(PUBLIC_SUMMARY_KEYS),
        "record_identity_codes": list(RECORD_IDENTITY_CODES),
        "entity_codes": list(ENTITY_CODES),
        "temporal_codes": list(TEMPORAL_CODES),
        "empty_use_codes": list(EMPTY_USE_CODES),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    payload = run()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "field_count": payload["field_count"],
                "required_count": payload["required_count"],
                "nullable_count": payload["nullable_count"],
                "fail_closed_code_count": payload["fail_closed_code_count"],
                "public_summary_key_count": payload["public_summary_key_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
