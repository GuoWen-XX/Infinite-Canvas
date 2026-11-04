#!/usr/bin/env python3
"""Check updater URLs without importing or executing the application."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


UPDATER_NAMES = frozenset({
    "GITHUB_REPO_URL", "GITHUB_BRANCH", "GITHUB_VERSION_URL",
    "GITHUB_TREE_URL", "GITHUB_RAW_ROOT", "GITHUB_UPDATE_NOTES_URL",
})


def _assigned_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_assigned_names(child) for child in target.elts))
    return set()


def _literal_expression(node: ast.expr, known: dict[str, str]) -> str | None:
    """Support only strings, references, safe f-strings and concatenation."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return known.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)
            elif (isinstance(part, ast.FormattedValue) and part.conversion == -1
                  and part.format_spec is None and isinstance(part.value, ast.Name)
                  and part.value.id in known):
                parts.append(known[part.value.id])
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_expression(node.left, known)
        right = _literal_expression(node.right, known)
        return left + right if left is not None and right is not None else None
    return None


def updater_constants(source: str) -> tuple[dict[str, str], list[str]]:
    tree = ast.parse(source, filename="main.py")
    values: dict[str, str] = {}
    encountered: set[str] = set()
    violations: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = set().union(*(_assigned_names(t) for t in node.targets))
            for name in targets & UPDATER_NAMES:
                if name in encountered:
                    violations.append(f"duplicate assignment to {name}")
                encountered.add(name)
                value = _literal_expression(node.value, values)
                if value is None:
                    violations.append(f"dynamic/unsupported value for {name}")
                else:
                    values[name] = value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            for name in _assigned_names(node.target) & UPDATER_NAMES:
                violations.append(f"unsupported assignment to {name}")
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                for name in _assigned_names(target) & UPDATER_NAMES:
                    violations.append(f"deletion of {name}")
    return values, violations


def audit(path: Path, expected_repo: str, expected_branch: str) -> dict:
    values, violations = updater_constants(path.read_text(encoding="utf-8-sig"))
    slug = expected_repo.strip().strip("/")
    branch = expected_branch.strip()
    expected = {
        "GITHUB_REPO_URL": f"https://github.com/{slug}",
        "GITHUB_BRANCH": branch,
        "GITHUB_VERSION_URL": f"https://raw.githubusercontent.com/{slug}/{branch}/VERSION",
        "GITHUB_TREE_URL": f"https://api.github.com/repos/{slug}/git/trees/{branch}?recursive=1",
        "GITHUB_RAW_ROOT": f"https://raw.githubusercontent.com/{slug}/{branch}",
        "GITHUB_UPDATE_NOTES_URL": f"https://raw.githubusercontent.com/{slug}/{branch}/static/update-notes.json",
    }
    problems = violations + [
        f"{name} differs from expected source"
        for name, value in expected.items() if values.get(name) != value
    ]
    return {
        "passed": not problems,
        "repo_url": values.get("GITHUB_REPO_URL"),
        "branch": values.get("GITHUB_BRANCH"),
        "expected_repo_url": expected["GITHUB_REPO_URL"],
        "expected_branch": expected["GITHUB_BRANCH"],
        "problems": problems,
        "reason": "" if not problems else "Updater source/branch or derived URLs are inconsistent",
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
        for problem in result["problems"]:
            print("-", problem)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
