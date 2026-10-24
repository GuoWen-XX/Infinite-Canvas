#!/usr/bin/env python3
"""Helper script to download pinned dependency wheels for offline installation.
Reads requirements.txt dynamically and downloads matching wheels into packages/.
"""
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REQ_FILE = ROOT / "requirements.txt"
PACKAGES_DIR = ROOT / "packages"

def parse_pinned_requirements():
    """Parse exact pinned packages from requirements.txt."""
    if not REQ_FILE.is_file():
        raise FileNotFoundError(f"requirements.txt not found at {REQ_FILE}")
    pinned = {}
    for line in REQ_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\s*([A-Za-z0-9_.\-]+)\s*==\s*([^\s;#]+)", line)
        if m:
            pinned[m.group(1)] = m.group(2)
        else:
            print(f"Warning: requirement is not strictly pinned with '==': {line}", file=sys.stderr)
    return pinned

def main():
    PACKAGES_DIR.mkdir(exist_ok=True)
    pinned = parse_pinned_requirements()
    print(f"Found {len(pinned)} pinned dependencies in {REQ_FILE.name}:")
    for pkg, ver in pinned.items():
        print(f"  - {pkg} == {ver}")

    print(f"\nDownloading wheels into {PACKAGES_DIR}...")
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "-r",
        str(REQ_FILE),
        "-d",
        str(PACKAGES_DIR),
    ]
    res = subprocess.run(cmd)
    if res.returncode == 0:
        print("\nOffline dependencies downloaded successfully to packages/.")
    else:
        print("\nFailed to download offline dependencies.", file=sys.stderr)
        sys.exit(res.returncode)

if __name__ == "__main__":
    main()
