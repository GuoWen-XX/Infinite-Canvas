#!/usr/bin/env python3
"""Offline wheelhouse release check; no installs, network, or account access."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def pinned_requirements(path: Path) -> dict[str, str]:
    result = {}
    for row in path.read_text(encoding="utf-8-sig").splitlines():
        text = row.split("#", 1)[0].strip()
        if not text:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+~-]+)", text)
        if match is None:
            raise ValueError(f"Unsupported/unpinned requirement: {text}")
        result[normalize_name(match.group(1))] = match.group(2)
    return result


def wheels_in(folder: Path) -> list[dict]:
    wheels = []
    for file in sorted(folder.glob("*.whl")):
        # PEP 427: distribution-version[-build]-python-abi-platform.whl.
        pieces = file.name[:-4].split("-")
        if len(pieces) < 5:
            continue
        wheels.append({
            "filename": file.name, "name": normalize_name(pieces[0]),
            "version": pieces[1], "python_tag": pieces[-3],
            "abi_tag": pieces[-2], "platform_tag": pieces[-1],
        })
    return wheels


def bundled_python_version(python_dir: Path) -> str | None:
    versions = []
    for dll in python_dir.glob("python3*.dll"):
        match = re.fullmatch(r"python(3)(\d{1,2})\.dll", dll.name, flags=re.I)
        if match:
            versions.append(f"{match.group(1)}.{int(match.group(2))}")
    return versions[0] if len(set(versions)) == 1 and versions else None


def wheel_compatible(wheel: dict, target_python: str, platform="win_amd64") -> bool:
    major, minor = target_python.split(".", 1)
    tags = wheel["python_tag"].split(".")
    abis = wheel["abi_tag"].split(".")
    platforms = wheel["platform_tag"].split(".")
    # Pure-Python wheels tagged for older 3.x minors can run on Python 3.10.
    older_pure = (major == "3" and "none" in abis and any(
        re.fullmatch(r"py3(\d+)", tag) and int(tag[3:]) <= int(minor)
        for tag in tags
    ))
    python_ok = (f"py{major}" in tags or f"py{major}{minor}" in tags
                 or f"cp{major}{minor}" in tags or older_pure)
    if not python_ok and "abi3" in abis:
        python_ok = any(re.fullmatch(r"cp3(\d+)", tag)
                        and int(tag[3:]) <= int(minor) for tag in tags)
    abi_ok = ("none" in abis or "abi3" in abis or f"cp{major}{minor}" in abis)
    return python_ok and abi_ok and ("any" in platforms or platform in platforms)


def audit(requirements: Path, packages: Path, python_dir: Path,
          target_python: str | None = None) -> dict:
    pinned = pinned_requirements(requirements)
    wheels = wheels_in(packages)
    target = target_python or bundled_python_version(python_dir)
    if not target:
        return {"passed": False, "target_python": None,
                "error": "Unable to identify one bundled Python version"}
    problems, matched = [], []
    for name, version in sorted(pinned.items()):
        available = [w for w in wheels if w["name"] == name]
        correct = [w for w in available if w["version"] == version]
        usable = [w for w in correct if wheel_compatible(w, target)]
        if usable:
            matched.append({"name": name, "version": version,
                            "wheel": usable[0]["filename"]})
        else:
            reason = ("missing" if not available else "version_mismatch"
                      if not correct else "incompatible_wheel_tags")
            problems.append({"name": name, "pinned_version": version,
                             "reason": reason,
                             "found": [w["filename"] for w in available]})
    incompatible = [w["filename"] for w in wheels if not wheel_compatible(w, target)]
    return {
        "passed": not problems, "target_python": target,
        "wheel_count": len(wheels), "pinned_count": len(pinned),
        "matched": matched, "problems": problems,
        "incompatible_wheels": incompatible,
        "note": "Static wheelhouse check; runtime installation and transitive dependencies must still be tested",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--target-python", help="Override bundled version, e.g. 3.10")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit(args.root / "requirements.txt", args.root / "packages",
                   args.root / "python", args.target_python)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Offline wheelhouse: {'PASS' if result['passed'] else 'FAIL'} "
              f"(target Python {result.get('target_python')})")
        for item in result.get("problems", []):
            print(f"  {item['name']}=={item['pinned_version']}: {item['reason']}; "
                  f"found: {', '.join(item['found']) or 'none'}")
        print(result.get("note", result.get("error", "")))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
