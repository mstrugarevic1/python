#!/usr/bin/env python3
"""Manage named, metadata-preserving tar backups."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tarfile
import time
from datetime import datetime
from pathlib import Path, PurePosixPath


def config_path() -> Path:
    return Path(os.environ.get("BACKUP_UTILITY_CONFIG", "~/.config/backup-utility/sets.json")).expanduser()


def load_sets() -> dict[str, dict[str, object]]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot read config {path}: {error}") from error
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid config {path}: expected an object")
    return data


def save_sets(sets: dict[str, dict[str, object]]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(sets, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def tar_is_gnu() -> bool:
    result = subprocess.run(["tar", "--version"], text=True, capture_output=True, check=False)
    return "GNU tar" in result.stdout


def run_tar(arguments: list[str], verbose: bool = False) -> None:
    subprocess.run(["tar", *arguments], check=True, text=True,
                   stdout=None if verbose else subprocess.DEVNULL)


def safe_archive(archive: Path) -> None:
    try:
        with tarfile.open(archive) as contents:
            for member in contents:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts:
                    raise RuntimeError(f"unsafe archive path: {member.name}")
    except tarfile.TarError as error:
        raise RuntimeError(f"invalid tar archive: {archive}") from error


def format_size(size: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def backup_set(name: str, settings: dict[str, object], dry_run: bool, verbose: bool) -> Path:
    source = Path(str(settings["source"])).expanduser().resolve()
    destination = Path(str(settings["destination"])).expanduser().resolve()
    if not source.is_dir():
        raise RuntimeError(f"source is not a directory: {source}")
    if destination == source or source in destination.parents:
        raise RuntimeError("destination must not be inside the source directory")

    archive = destination / f"{name}-{datetime.now():%Y%m%d-%H%M%S-%f}.tar.gz"
    print(f"[{datetime.now():%H:%M:%S}] backup {name} started")
    if dry_run:
        print(f"Would create {archive} from {source}")
        return archive

    destination.mkdir(parents=True, exist_ok=True)
    incomplete = archive.with_suffix(f"{archive.suffix}.incomplete")
    arguments = ["-czf", str(incomplete)]
    if tar_is_gnu():
        arguments += ["--acls", "--xattrs", "--selinux", "--numeric-owner", "--sparse"]
    for pattern in settings.get("exclude", []):
        arguments += ["--exclude", str(pattern)]
    if verbose:
        arguments.append("-v")
    arguments += ["-C", str(source), "."]

    started = time.monotonic()
    try:
        run_tar(arguments, verbose)
        incomplete.replace(archive)
    except Exception:
        print(f"Incomplete archive retained at {incomplete}")
        raise
    print(f"[{datetime.now():%H:%M:%S}] backup {name} complete: "
          f"{format_size(archive.stat().st_size)}, {time.monotonic() - started:.1f}s")
    return archive


def restore(archive: Path, destination: Path, verbose: bool) -> None:
    archive = archive.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not archive.is_file():
        raise RuntimeError(f"archive is not a file: {archive}")
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError(f"restore destination is not empty: {destination}")
    safe_archive(archive)
    destination.mkdir(parents=True, exist_ok=True)

    arguments = ["-xzf", str(archive), "-C", str(destination), "-p"]
    if tar_is_gnu():
        arguments += ["--acls", "--xattrs", "--selinux", "--same-owner", "--same-permissions"]
    if verbose:
        arguments.append("-v")
    print(f"[{datetime.now():%H:%M:%S}] restore started")
    run_tar(arguments, verbose)
    print(f"[{datetime.now():%H:%M:%S}] restore complete: {destination}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    set_parser = commands.add_parser("set", help="create or update a backup set")
    set_parser.add_argument("name")
    set_parser.add_argument("source", type=Path)
    set_parser.add_argument("destination", type=Path)
    set_parser.add_argument("--exclude", action="append", default=[])

    list_parser = commands.add_parser("list", help="list backup sets")
    list_parser.add_argument("name", nargs="?")

    backup_parser = commands.add_parser("backup", help="run a backup set")
    backup_parser.add_argument("name")
    backup_parser.add_argument("--dry-run", action="store_true")
    backup_parser.add_argument("--verbose", action="store_true")

    restore_parser = commands.add_parser("restore", help="restore an archive")
    restore_parser.add_argument("archive", type=Path)
    restore_parser.add_argument("destination", type=Path)
    restore_parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        sets = load_sets()
        if args.command == "set":
            source, destination = args.source.expanduser().resolve(), args.destination.expanduser().resolve()
            if not source.is_dir():
                parser.error(f"source is not a directory: {source}")
            sets[args.name] = {"source": str(source), "destination": str(destination), "exclude": args.exclude}
            save_sets(sets)
            print(f"Saved backup set {args.name}")
        elif args.command == "list":
            selected = {args.name: sets[args.name]} if args.name in sets else sets if args.name is None else None
            if selected is None:
                parser.error(f"unknown backup set: {args.name}")
            for name, settings in selected.items():
                excludes = ", ".join(map(str, settings.get("exclude", []))) or "none"
                print(f"{name}: {settings['source']} -> {settings['destination']} (exclude: {excludes})")
        elif args.command == "backup":
            if args.name not in sets:
                parser.error(f"unknown backup set: {args.name}")
            backup_set(args.name, sets[args.name], args.dry_run, args.verbose)
        else:
            restore(args.archive, args.destination, args.verbose)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
