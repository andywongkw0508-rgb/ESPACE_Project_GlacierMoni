from __future__ import annotations

import csv
import datetime as dt

from .config import MANIFEST, PROJECT_ROOT


def load_rows() -> list[dict[str, str]]:
    if not MANIFEST.exists():
        raise FileNotFoundError(f"Missing manifest: {MANIFEST}")

    rows: list[dict[str, str]] = []
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row["date"] = format_date(row.get("datetime", ""))
            row["cloud_value"] = parse_float(row.get("cloud_cover", ""))
            preview = row.get("preview_file", "")
            row["preview_path"] = str((PROJECT_ROOT / preview).resolve()) if preview else ""
            rows.append(row)
    return rows


def parse_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 100.0


def format_date(value: str) -> str:
    if not value:
        return ""
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return value[:10]
