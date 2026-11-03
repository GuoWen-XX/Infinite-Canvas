#!/usr/bin/env python3
"""Stage Windows CPython 3.10 wheels without modifying shipped packages.

A staged directory is NOT a release. Run an isolated Windows install and
pip check before promoting it. Network access is only used by pip download.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def download_command(python: str, requirements: Path, destination: Path) -> list[str]:
    return [python, "-m", "pip", "download", "--disable-pip-version-check",
            "--only-binary=:all:", "--implementation", "cp",
            "--python-version", "3.10", "--abi", "cp310",
            "--platform", "win_amd64", "--dest", str(destination),
            "--requirement", str(requirements)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True,
                        help="New/empty staging folder OUTSIDE shipped packages/")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    root, target = args.root.resolve(), args.output.resolve()
    packages = (root / "packages").resolve()
    if target == packages or packages in target.parents or root in target.parents:
        parser.error("output must be outside repository and shipped packages/")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        parser.error("output folder must be an empty directory")
    req = root / "requirements.txt"
    if not req.is_file():
        parser.error("requirements.txt not found")
    cmd = download_command(args.python, req, target)
    if args.dry_run:
        print(json.dumps({"command": cmd, "output": str(target)}, ensure_ascii=False))
        return 0
    target.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(cmd, check=False)
    if result.returncode:
        print("pip download failed; do not use staged wheels", file=sys.stderr)
        return result.returncode
    sys.path.insert(0, str(root / "tools"))
    from check_s08_wheelhouse import audit
    report = audit(req, target, root / "python", target_python="3.10")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report["passed"] or report["incompatible_wheels"]:
        print("Static wheel gate failed; do not publish", file=sys.stderr)
        return 1
    print("Candidate for isolated Windows Python 3.10 install and pip check; NOT release-approved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
