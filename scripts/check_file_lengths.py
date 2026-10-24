#!/usr/bin/env python3
"""CI Guard: File length budget & ratchet mechanism.
Enforces that new files stay under 1500 lines (or category defaults),
and legacy oversized files do not expand beyond their baseline ceilings.
"""
import os
import sys

SCAN_TARGETS = [
    ("routers", ".py", 1500),
    ("core", ".py", 1500),
    ("static/js", ".js", 1500),
    ("static/css", ".css", 2500),
    ("tools", ".js", 2000),
]

# Baseline ceilings for pre-existing legacy monoliths (+1~3% ratchet buffer)
LEGACY_LIMITS = {
    "static/js/smart-canvas.js": 19500,     # current 19089
    "static/js/canvas.js": 18000,           # current 17780
    "static/js/asset-manager.js": 5200,     # current 5078
    "static/js/api-settings.js": 4950,      # current 4869
    "static/js/ltx-director-timeline.js": 4250, # current 4153
    "static/js/studio-shell.js": 2850,      # current 2749
    "static/js/canvas-agent.js": 1600,      # current 1523
    "routers/integrations.py": 4200,        # current 4108
    "routers/assets.py": 3200,              # current 3136
    "routers/online_image.py": 2950,        # current 2898
    "routers/video.py": 2400,               # current 2346
    "core/providers.py": 2400,   # current 2376（新增 _MtimeCache 通用缓存构件）              # current 2239
    "routers/chat.py": 1750,                # current 1702
    "static/css/api-settings.css": 7450,    # current 7353
    "static/css/canvas.css": 3950,          # current 3886
    "static/css/theme.css": 2350,           # current 2289
    "static/css/studio-shell.css": 2250,    # current 2203
    "static/css/smart-canvas.css": 1700,    # current 1644
    "tools/photoshop-asset-connector/style.css": 1600,
}

def check_file_lengths():
    errors = []
    checked_count = 0
    for base, ext, default_limit in SCAN_TARGETS:
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for f in files:
                if not f.endswith(ext):
                    continue
                p = os.path.normpath(os.path.join(root, f)).replace("\\", "/")
                # Skip third-party vendor bundles and node_modules
                if "/vendor/" in p or p.startswith("static/vendor/") or "/node_modules/" in p or "node_modules" in p:
                    continue
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                        lines = sum(1 for _ in fp)
                except Exception as e:
                    errors.append(f"Cannot read {p}: {e}")
                    continue
                checked_count += 1
                limit = LEGACY_LIMITS.get(p, default_limit)
                if lines > limit:
                    errors.append(f"{p}: {lines} lines (ceiling is {limit})")

    if errors:
        print("FAIL: File length budget exceeded:")
        for err in errors:
            print(f"  - {err}")
        return False
    print(f"File length budget check passed: {checked_count} files comply with ratchet line limits.")
    return True

if __name__ == "__main__":
    if not check_file_lengths():
        sys.exit(1)
    sys.exit(0)
