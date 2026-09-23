#!/usr/bin/env python3
"""Relocate source-home absolute paths after the project is copied to A100."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


TEXT_SUFFIXES = {
    ".csv",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".service",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_PARTS = {".git", "__pycache__", ".pytest_cache"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--old-home", default="/home/onsesang")
    parser.add_argument("--new-home", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = args.project_root.expanduser().resolve()
    old = args.old_home.encode("utf-8")
    new = str(args.new_home.expanduser().resolve()).encode("utf-8")
    if not root.is_dir():
        raise SystemExit(f"project root not found: {root}")
    if old == new:
        print("No relocation needed; source and destination home are identical.")
        return 0

    changed: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if relative == Path("A100_CODEX_MIGRATION_HANDOFF.md"):
            continue
        if relative.parts[:2] == ("migration", "a100"):
            continue
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        before = path.read_bytes()
        count = before.count(old)
        if not count:
            continue
        after = before.replace(old, new)
        changed.append(
            {
                "path": str(relative),
                "replacement_count": count,
                "sha256_before": sha256(before),
                "sha256_after": sha256(after),
            }
        )
        if not args.dry_run:
            path.write_bytes(after)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "project_root": str(root),
        "old_home": old.decode(),
        "new_home": new.decode(),
        "files_changed": len(changed),
        "replacements": sum(int(row["replacement_count"]) for row in changed),
        "files": changed,
    }
    report = root / "migration" / "a100" / "path_relocation_manifest.json"
    if args.dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Relocated {result['replacements']} references in {result['files_changed']} files")
        print(f"Manifest: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
