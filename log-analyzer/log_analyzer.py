#!/usr/bin/env python3
"""Summarize Apache/Nginx common and combined access logs."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path


ACCESS_LOG_PATTERN = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<request>[^"]*)" (?P<status>\d{3}) (?P<size>\d+|-)'
    r'(?: "(?P<referrer>[^"]*)" "(?P<user_agent>[^"]*)")?$'
)


def parse_request(request: str) -> tuple[str, str, str]:
    parts = request.split()
    if len(parts) != 3:
        return "-", request or "-", "-"
    return parts[0], parts[1], parts[2]


def analyze(path: Path) -> tuple[int, int, int, Counter[str], Counter[str], Counter[str], Counter[str], Counter[str]]:
    statuses: Counter[str] = Counter()
    paths: Counter[str] = Counter()
    ips: Counter[str] = Counter()
    methods: Counter[str] = Counter()
    problem_paths: Counter[str] = Counter()
    total = 0
    parsed = 0
    bytes_served = 0

    with path.open(encoding="utf-8", errors="replace") as log_file:
        for line in log_file:
            total += 1
            match = ACCESS_LOG_PATTERN.search(line.strip())
            if not match:
                continue

            method, request_path, _protocol = parse_request(match["request"])
            status = match["status"]
            parsed += 1
            statuses[status] += 1
            paths[request_path] += 1
            ips[match["ip"]] += 1
            methods[method] += 1
            if status.startswith(("4", "5")):
                problem_paths[f"{status} {request_path}"] += 1
            if match["size"] != "-":
                bytes_served += int(match["size"])

    return total, parsed, bytes_served, statuses, paths, ips, methods, problem_paths


def export_report(
    path: Path,
    statuses: Counter[str],
    paths: Counter[str],
    ips: Counter[str],
    methods: Counter[str],
    problem_paths: Counter[str],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["section", "value", "count"])
        for section, counter in (
            ("status", statuses),
            ("path", paths),
            ("ip", ips),
            ("method", methods),
            ("4xx_5xx_path", problem_paths),
        ):
            for value, count in counter.most_common():
                writer.writerow([section, value, count])


def print_counter(title: str, counter: Counter[str], top: int) -> None:
    print(f"{title}:")
    for value, count in counter.most_common(max(top, 0)):
        print(f"  {count:>3}  {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_file", type=Path)
    parser.add_argument("--top", type=int, default=5, help="number of rows per section")
    parser.add_argument("--csv", type=Path, help="export counters to CSV")
    args = parser.parse_args()

    if not args.log_file.is_file():
        parser.error(f"file not found: {args.log_file}")

    total, parsed, bytes_served, statuses, paths, ips, methods, problem_paths = analyze(args.log_file)
    print(f"Lines read: {total}")
    print(f"Parsed access log lines: {parsed}")
    print(f"Skipped lines: {total - parsed}")
    print(f"Bytes served: {bytes_served}")
    print_counter("Status codes", statuses, args.top)
    print_counter("Methods", methods, args.top)
    print_counter("Top paths", paths, args.top)
    print_counter("Top IPs", ips, args.top)
    print_counter("Top 4xx/5xx paths", problem_paths, args.top)

    if args.csv:
        export_report(args.csv, statuses, paths, ips, methods, problem_paths)
        print(f"CSV written to {args.csv}")


if __name__ == "__main__":
    main()
