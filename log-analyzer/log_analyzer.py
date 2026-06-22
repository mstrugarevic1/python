#!/usr/bin/env python3
"""Summarize common log levels and messages in a text log file."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path


LOG_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})?.*?\b"
    r"(?P<level>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\b[\s:|-]*(?P<message>.*)$",
    re.IGNORECASE,
)


def analyze(path: Path) -> tuple[int, Counter[str], Counter[str], Counter[str]]:
    levels: Counter[str] = Counter()
    dates: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    total = 0

    with path.open(encoding="utf-8", errors="replace") as log_file:
        for line in log_file:
            total += 1
            match = LOG_PATTERN.search(line.strip())
            if not match:
                continue

            level = match["level"].upper()
            if level == "WARN":
                level = "WARNING"
            levels[level] += 1
            if match["date"]:
                dates[match["date"]] += 1
            if level in {"ERROR", "CRITICAL"}:
                errors[match["message"] or "(no message)"] += 1

    return total, levels, dates, errors


def export_errors(path: Path, errors: Counter[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["message", "count"])
        writer.writerows(errors.most_common())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_file", type=Path)
    parser.add_argument("--top", type=int, default=5, help="number of errors to show")
    parser.add_argument("--csv", type=Path, help="export error counts to CSV")
    args = parser.parse_args()

    if not args.log_file.is_file():
        parser.error(f"file not found: {args.log_file}")

    total, levels, dates, errors = analyze(args.log_file)
    print(f"Lines read: {total}")
    print("Levels:", ", ".join(f"{name}={count}" for name, count in levels.most_common()) or "none")
    print("Events by date:", ", ".join(f"{date}={count}" for date, count in sorted(dates.items())) or "none")
    print("Most common errors:")
    for message, count in errors.most_common(max(args.top, 0)):
        print(f"  {count:>3}  {message}")

    if args.csv:
        export_errors(args.csv, errors)
        print(f"CSV written to {args.csv}")


if __name__ == "__main__":
    main()
