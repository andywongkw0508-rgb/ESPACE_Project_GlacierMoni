from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from .config import DATA_ROOT, MANIFEST, PROJECT_ROOT


def load_rows() -> list[dict[str, str]]:
    if not MANIFEST.exists():
        raise FileNotFoundError(f"Missing manifest: {MANIFEST}")

    rows: list[dict[str, str]] = []
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row["date"] = format_date(row.get("datetime", ""))
            row["cloud_value"] = parse_float(row.get("cloud_cover", ""))
            preview = row.get("preview_file", "")
            row["preview_path"] = str(resolve_preview_path(preview)) if preview else ""
            rows.append(row)
    return rows


def resolve_preview_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path

    parts = path.parts
    if DATA_ROOT.name in parts:
        root_index = parts.index(DATA_ROOT.name)
        return (DATA_ROOT / Path(*parts[root_index + 1 :])).resolve()

    data_root_candidate = (DATA_ROOT / path).resolve()
    if data_root_candidate.exists():
        return data_root_candidate

    return (PROJECT_ROOT / path).resolve()


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
