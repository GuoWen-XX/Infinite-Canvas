#!/usr/bin/env python3
"""Static release gate: verify updater origin without importing or running main.py."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


def updater_constants(source: str) -> dict[str, str]:
    """Evaluate only literal strings and f-strings referencing audited constants."""
    tree = ast.parse(source, filename="main.py")
    wanted = {
        "GITHUB_REPO_URL", "GITHUB_BRANCH", "GITHUB_VERSION_URL",
        "GITHUB_TREE_URL", "GITHUB_RAW_ROOT",
    }
    found: dict[str, str] = {}

    def literal(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return found.get(node.id)
        if isinstance(node, ast.JoinedStr):
            parts = []
            for part in node.values:
                if isinstance(part, ast.FormattedValue):
                    value = literal(part.value)
                else:
                    value = literal(part)
                if value is None:
                    return None
                parts.append(value)
            return "".join(parts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = literal(node.left), literal(node.right)
            return left + right if left is not None and right is not None else None
        return None

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in wanted:
                value = literal(node.value)
                if value is None:
                    found.pop(target.id, None)
                else:
                    found[target.id] = value
    return found


def audit(path: Path, expected_repo: str, expected_branch: str) -> dict:
    values = updater_constants(path.read_text(encoding="utf-8-sig"))
    repo = expected_repo.strip().strip("/")
    expected_url = "https://github.com/" + repo
    expected = {
        "GITHUB_REPO_URL": expected_url,
        "GITHUB_BRANCH": expected_branch,
        "GITHUB_VERSION_URL": f"https://raw.githubusercontent.com/{repo}/{expected_branch}/VERSION",
        "GITHUB_TREE_URL": f"https://api.github.com/repos/{repo}/git/trees/{expected_branch}?recursive=1",
        "GITHUB_RAW_ROOT": f"https://raw.githubusercontent.com/{repo}/{expected_branch}",
    }
    mismatches = {
        key: {"actual": values.get(key), "expected": value}
        for key, value in expected.items() if values.get(key) != value
    }
    return {
        "passed": not mismatches,
        "repo_url": values.get("GITHUB_REPO_URL"),
        "branch": values.get("GITHUB_BRANCH"),
        "expected_repo_url": expected_url,
        "expected_branch": expected_branch,
        "mismatches": mismatches,
        "reason": "" if not mismatches else "Updater download endpoints differ from the approved repository/branch",
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
