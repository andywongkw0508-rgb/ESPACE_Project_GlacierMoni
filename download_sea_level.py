from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_AOI = PROJECT_ROOT / "config" / "aoi.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "sea_level"
DEFAULT_DATASET_ID = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
DEFAULT_VARIABLE = "zos"
DEFAULT_START_DATE = "2017-01-01"
DEFAULT_END_DATE = "2026-05-26"


def main() -> int:
    load_env_file(PROJECT_ROOT / ".env")
    args = parse_args()
    bbox = load_bbox(args.aoi, args.buffer_degrees)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_filename = args.output_filename or default_output_filename(args.start_date, args.end_date, args.variable)
    command = build_command(args, bbox, output_dir, output_filename)

    print("Copernicus Marine sea-level download")
    print(f"Dataset: {args.dataset_id}")
    print(f"Variable: {args.variable}")
    print(f"Period: {args.start_date} to {args.end_date}")
    print(
        "BBox: "
        f"west={bbox['west']:.4f}, south={bbox['south']:.4f}, "
        f"east={bbox['east']:.4f}, north={bbox['north']:.4f}"
    )
    print(f"Output: {output_dir / output_filename}")

    if args.dry_run:
        print("\nCommand:")
        print(" ".join(quote(part) for part in command))
        return 0

    if not copernicusmarine_available():
        print(
            "\nCopernicus Marine toolbox is not installed in this Python environment.\n"
            "Install/update the project environment first:\n"
            "  conda env update -f environment.yml\n"
            "  conda activate glacier-monitoring\n",
            file=sys.stderr,
        )
        return 2

    if not credentials_are_configured():
        print(
            "\nNo Copernicus Marine credentials were found in environment variables.\n"
            "The toolbox may still use saved credentials if you already ran `copernicusmarine login`.\n"
            "Otherwise set COPERNICUSMARINE_SERVICE_USERNAME and "
            "COPERNICUSMARINE_SERVICE_PASSWORD before running this script.\n"
        )

    return subprocess.call(command)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download Copernicus Marine sea surface height for the project AOI. "
            "The default product is the Global Ocean Physics Reanalysis daily sea "
            "surface height above geoid (`zos`)."
        )
    )
    parser.add_argument("--aoi", type=Path, default=DEFAULT_AOI, help="AOI JSON file with bbox west/south/east/north.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Folder for downloaded NetCDF files.")
    parser.add_argument("--output-filename", default="", help="Optional NetCDF output filename.")
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET_ID, help="Copernicus Marine dataset ID.")
    parser.add_argument("--variable", default=DEFAULT_VARIABLE, help="Variable to download, default `zos`.")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="Start date, YYYY-MM-DD.")
    parser.add_argument(
        "--end-date",
        default=DEFAULT_END_DATE,
        help=(
            "End date, YYYY-MM-DD. Default is the latest date currently covered by "
            "GLOBAL_MULTIYEAR_PHY_001_030 in this project setup."
        ),
    )
    parser.add_argument(
        "--buffer-degrees",
        type=float,
        default=0.0,
        help="Optional lat/lon buffer added around the project AOI.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the command without downloading.")
    return parser.parse_args()


def load_bbox(path: Path, buffer_degrees: float) -> dict[str, float]:
    with path.open(encoding="utf-8") as handle:
        config = json.load(handle)
    bbox = config.get("bbox", config)
    west = float(bbox["west"]) - buffer_degrees
    south = float(bbox["south"]) - buffer_degrees
    east = float(bbox["east"]) + buffer_degrees
    north = float(bbox["north"]) + buffer_degrees
    return {
        "west": max(-180.0, west),
        "south": max(-90.0, south),
        "east": min(180.0, east),
        "north": min(90.0, north),
    }


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def default_output_filename(start_date: str, end_date: str, variable: str) -> str:
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    return f"vatnajokull_28wds_sea_level_{variable}_{start}_{end}.nc"


def build_command(
    args: argparse.Namespace,
    bbox: dict[str, float],
    output_dir: Path,
    output_filename: str,
) -> list[str]:
    executable = shutil.which("copernicusmarine")
    command = [executable] if executable else [sys.executable, "-m", "copernicusmarine"]
    command.extend(
        [
            "subset",
            "--dataset-id",
            args.dataset_id,
            "--variable",
            args.variable,
            "--minimum-longitude",
            str(bbox["west"]),
            "--maximum-longitude",
            str(bbox["east"]),
            "--minimum-latitude",
            str(bbox["south"]),
            "--maximum-latitude",
            str(bbox["north"]),
            "--start-datetime",
            f"{args.start_date}T00:00:00",
            "--end-datetime",
            f"{args.end_date}T23:59:59",
            "--output-directory",
            str(output_dir),
            "--output-filename",
            output_filename,
            "--force-download",
        ]
    )
    return command


def copernicusmarine_available() -> bool:
    if shutil.which("copernicusmarine"):
        return True
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "copernicusmarine", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def credentials_are_configured() -> bool:
    username = os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME") or os.environ.get("COPERNICUSMARINE_USERNAME")
    password = os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD") or os.environ.get("COPERNICUSMARINE_PASSWORD")
    return bool(username and password)


def quote(value: str) -> str:
    if not value or any(char.isspace() for char in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


if __name__ == "__main__":
    raise SystemExit(main())
