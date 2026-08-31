#!/usr/bin/env python3
"""Fail when known private Piano Tutor paths are tracked or reachable."""

from __future__ import annotations

import argparse
import subprocess
import sys


PRIVATE_EXACT = {
    "docs/pdfs/piano-songs.pdf",
    "frontend/src/data/familyScores.json",
    "frontend/src/data/familyScores.private.json",
}
PRIVATE_PREFIXES = ("scores/family/",)


def git(*args: str) -> str:
    return subprocess.run(
        ("git", *args),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout


def is_private(path: str) -> bool:
    return path in PRIVATE_EXACT or path.startswith(PRIVATE_PREFIXES)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--history",
        action="store_true",
        help="also inspect objects reachable from the current branch",
    )
    args = parser.parse_args()

    findings = {
        path for path in git("ls-files").splitlines() if is_private(path)
    }

    if args.history:
        for line in git("rev-list", "--objects", "HEAD").splitlines():
            _, separator, path = line.partition(" ")
            if separator and is_private(path):
                findings.add(path)

    if findings:
        print("Private release paths are still tracked or reachable:", file=sys.stderr)
        for path in sorted(findings):
            print(f"  - {path}", file=sys.stderr)
        print("See docs/PUBLIC_RELEASE.md before publishing.", file=sys.stderr)
        return 1

    home_path_pattern = "/" + "Users/[^/]+"
    absolute_paths = subprocess.run(
        ("git", "grep", "-n", "-I", "-E", home_path_pattern, "HEAD", "--", "."),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    if absolute_paths:
        print("Machine-specific home-directory paths remain in the public tree:", file=sys.stderr)
        print(absolute_paths, file=sys.stderr)
        return 1

    print("Public-tree path check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
