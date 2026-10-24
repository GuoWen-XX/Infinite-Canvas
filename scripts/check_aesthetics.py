#!/usr/bin/env python3
"""CI Guard: Enforce typography font-weight limits and zero-rainbow-color aesthetic contract (AGENTS.md)."""
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

PATTERNS = [
    ("invalid_font_weight_css", re.compile(r'font-weight\s*:\s*(100|200|300|650|750|780|800|850|900|950|bolder|lighter)(?!\d)', re.IGNORECASE)),
    ("invalid_font_weight_js", re.compile(r'fontWeight\s*[:=]\s*[\'"]?(100|200|300|650|750|780|800|850|900|950|bolder|lighter)(?!\d)', re.IGNORECASE)),
    ("invalid_font_shorthand_js", re.compile(r'(?:ctx|style|el)\.font\s*=\s*[`\'"](100|200|300|650|750|780|800|850|900|950)(?!\d)', re.IGNORECASE)),
    ("invalid_font_shorthand_css", re.compile(r'(?<![-\w])font\s*:\s*(100|200|300|650|750|780|800|850|900|950)(?!\d)', re.IGNORECASE)),
    ("font_black_utility", re.compile(r'\bfont-(black|extrabold)\b', re.IGNORECASE)),
    ("rainbow_color_utility", re.compile(r'\b(?:text|bg|border|ring|from|to|via|fill|stroke|shadow|outline|decoration|accent|caret|divide|placeholder)-(?:red|green|blue|purple|amber|rose|emerald|cyan|sky|violet|fuchsia|lime|teal|indigo|yellow|orange|pink)-\d{2,3}\b', re.IGNORECASE)),
    ("colorful_emoji", re.compile(r'[\U0001f300-\U0001f9ff\u2600-\u26ff\u2700-\u27bf]')),
]

def check_aesthetics():
    violations = []
    scanned_count = 0
    for base in ("static", "tools"):
        for root, _, files in os.walk(base):
            if any(x in root for x in ("vendor", "node_modules", ".git")):
                continue
            for f in files:
                if not f.endswith((".js", ".css", ".html")):
                    continue
                p = os.path.normpath(os.path.join(root, f)).replace("\\", "/")
                scanned_count += 1
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                        for idx, line in enumerate(fp, 1):
                            for name, pat in PATTERNS:
                                m = pat.search(line)
                                if m:
                                    violations.append((p, idx, name, m.group(0), line.strip()))
                except Exception as exc:
                    violations.append((p, 0, "read_error", str(exc), ""))

    if violations:
        print(f"FAIL: Found {len(violations)} aesthetic/typography contract violations:")
        for v in violations:
            print(f"  - {v[0]}:{v[1]}: [{v[2]}] {v[3]} -> {v[4][:100]}")
        return False

    print(f"Aesthetic check passed: {scanned_count} frontend files comply with typography and palette contract.")
    return True

if __name__ == "__main__":
    if not check_aesthetics():
        sys.exit(1)
    sys.exit(0)
