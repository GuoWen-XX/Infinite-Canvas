#!/usr/bin/env python3
"""Static release gate: verify updater origin without importing or running main.py."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


def updater_constants(source: str) -> dict[str, str]:
    tree = ast.parse(source, filename="main.py")
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in {"GITHUB_REPO_URL", "GITHUB_BRANCH"}:
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    found[target.id] = node.value.value
    return found


def audit(path: Path, expected_repo: str, expected_branch: str) -> dict:
    values = updater_constants(path.read_text(encoding="utf-8-sig"))
    expected_url = "https://github.com/" + expected_repo.strip().strip("/")
    actual_url = values.get("GITHUB_REPO_URL")
    actual_branch = values.get("GITHUB_BRANCH")
    matches = actual_url == expected_url and actual_branch == expected_branch
    return {
        "passed": matches, "repo_url": actual_url, "branch": actual_branch,
        "expected_repo_url": expected_url, "expected_branch": expected_branch,
        "reason": "" if matches else "Updater points to a different repository/branch; release may overwrite this fork",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected-repo", default="GuoWen-XX/Infinite-Canvas")
    parser.add_argument("--expected-branch", default="main")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit(args.root / "main.py", args.expected_repo, args.expected_branch)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Update source:", "PASS" if result["passed"] else "FAIL")
        print(f"Actual: {result['repo_url']} @ {result['branch']}")
        print(f"Target: {result['expected_repo_url']} @ {result['expected_branch']}")
        if result["reason"]:
            print(result["reason"])
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
