#!/usr/bin/env python3
"""Copy a directory into a new timestamped backup directory."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


def is_excluded(path: Path, suffixes: set[str]) -> bool:
    return path.suffix.lower() in suffixes or any(part in {".git", "__pycache__"} for part in path.parts)


def copy_stable(source: Path, target: Path) -> None:
    for _ in range(2):
        before = source.stat()
        shutil.copy2(source, target)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
            return
    raise RuntimeError(f"source changed while being copied: {source}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--exclude", action="append", default=[], metavar=".EXT")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    destination = args.destination.expanduser().resolve()
    if not source.is_dir():
        parser.error(f"source is not a directory: {source}")
    if destination == source or source in destination.parents:
        parser.error("destination must not be inside the source directory")

    suffixes = {value.lower() if value.startswith(".") else f".{value.lower()}" for value in args.exclude}
    backup = destination / f"{source.name}-{datetime.now():%Y%m%d-%H%M%S-%f}"
    incomplete = backup.with_name(f"{backup.name}.incomplete")
    paths = [path for path in source.rglob("*")
             if not path.is_symlink() and not is_excluded(path.relative_to(source), suffixes)]
    directories = [path for path in paths if path.is_dir()]
    files = [path for path in paths if path.is_file()]

    print(f"Backing up {len(files)} files to {backup}")
    if not args.dry_run:
        incomplete.mkdir(parents=True)
        for path in directories:
            (incomplete / path.relative_to(source)).mkdir(parents=True)
    for path in files:
        target = incomplete / path.relative_to(source)
        print(f"  {path.relative_to(source)}")
        if not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            copy_stable(path, target)

    if not args.dry_run:
        incomplete.rename(backup)

    print("Dry run complete; no files copied." if args.dry_run else "Backup complete.")


if __name__ == "__main__":
    main()
