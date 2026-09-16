#!/usr/bin/env python3
"""Descobre e executa proteções declaradas em regressions/manifest.json."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path


def _values(items: list[str]) -> set[str]:
    return {str(item).strip().casefold() for item in items if str(item).strip()}


def _matches(entry: dict, args: argparse.Namespace) -> bool:
    requested = bool(args.changed_file or args.component or args.domain or args.tag)
    if not requested:
        return True
    if _values(entry.get("components", [])) & _values(args.component):
        return True
    if _values(entry.get("domains", [])) & _values(args.domain):
        return True
    if _values(entry.get("tags", [])) & _values(args.tag):
        return True
    patterns = [str(value).replace("\\", "/") for value in entry.get("file_globs", [])]
    return any(
        fnmatch.fnmatch(str(path).replace("\\", "/"), pattern)
        for path in args.changed_file
        for pattern in patterns
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--manifest", default="regressions/manifest.json")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--component", action="append", default=[])
    parser.add_argument("--domain", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    manifest_path = repo / args.manifest
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"REGRESSION_GUARD_ERROR manifest={manifest_path} detail={exc}", file=sys.stderr)
        return 2

    matches = [entry for entry in manifest.get("regressions", []) if _matches(entry, args)]
    print(json.dumps({
        "manifest": str(manifest_path),
        "matched": [entry.get("id") for entry in matches],
        "criteria": {
            "files": args.changed_file,
            "components": args.component,
            "domains": args.domain,
            "tags": args.tag,
        },
    }, ensure_ascii=False))
    if not matches:
        return 0

    failed = False
    for entry in matches:
        protections = entry.get("protections") or []
        if entry.get("severity") == "CRITICA" and not protections:
            print(f"{entry.get('id')}: proteção crítica ausente", file=sys.stderr)
            failed = True
            continue
        print(f"{entry.get('id')} [{entry.get('severity')}]: {entry.get('title')}")
        print(f"INVARIANTE: {entry.get('invariant')}")
        for protection in protections:
            command = [
                sys.executable if value == "{python}" else str(value)
                for value in protection.get("command", [])
            ]
            print("PROTEÇÃO:", " ".join(command))
            if not args.run:
                continue
            result = subprocess.run(command, cwd=repo, check=False)
            if result.returncode:
                failed = True
                print(
                    f"{entry.get('id')}: proteção falhou com código {result.returncode}",
                    file=sys.stderr,
                )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
