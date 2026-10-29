#!/usr/bin/env python3
"""Validate decor-mappings.csv and generate the JSON consumed by the catalog."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "decor-mappings.csv"
JSON_PATH = ROOT / "decor-mappings.json"
FIELDS = ["manufacturer", "decor", "edge", "comment"]
MIN_ROWS = 800


def main() -> None:
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS:
            raise SystemExit(
                f"Unexpected CSV columns: {reader.fieldnames!r}; expected {FIELDS!r}"
            )
        rows = []
        for line_number, raw in enumerate(reader, start=2):
            row = {field: (raw.get(field) or "").strip() for field in FIELDS}
            if not row["manufacturer"] or not row["decor"]:
                raise SystemExit(
                    f"CSV row {line_number}: manufacturer and decor are required"
                )
            rows.append(row)

    if len(rows) < MIN_ROWS:
        raise SystemExit(
            f"Only {len(rows)} rows found; refusing to publish fewer than {MIN_ROWS}"
        )

    JSON_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Validated {len(rows)} decor mappings and wrote {JSON_PATH.name}")


if __name__ == "__main__":
    main()
