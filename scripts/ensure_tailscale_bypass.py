# -*- coding: utf-8 -*-
"""
Ensure Tailscale (100.64.0.0/10) is whitelisted in SakuraCat / Mihomo TUN bypass.
Dynamically searches for active Mihomo / SakuraCat controller ports (39790-39810, 9090, 7890).
"""
import urllib.request
import json
import sys

CANDIDATE_PORTS = list(range(39790, 39810)) + [9090, 7890, 9097]

def find_mihomo_api():
    for port in CANDIDATE_PORTS:
        url = f"http://127.0.0.1:{port}"
        try:
            req = urllib.request.Request(f"{url}/version")
            with urllib.request.urlopen(req, timeout=0.15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("meta") or data.get("version"):
                    return f"{url}/configs"
        except Exception:
            continue
    return None

def check_and_patch(verbose=False):
    api_url = find_mihomo_api()
    if not api_url:
        if verbose:
            print("[INFO] SakuraCat/Mihomo helper API not reachable (SakuraCat might not be running).")
        return False

    try:
        req = urllib.request.Request(api_url)
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            cfg = json.loads(resp.read().decode("utf-8"))

        tun = cfg.get("tun", {})
        exclude = tun.get("route-exclude-address", []) or []

        target = "100.64.0.0/10"
        if target in exclude:
            if verbose:
                print(f"[OK] SakuraCat TUN already has '{target}' in route-exclude-address (via {api_url}).")
            return True

        exclude.append(target)
        payload = json.dumps({
            "tun": {
                "enable": tun.get("enable", True),
                "route-exclude-address": exclude
            }
        }).encode("utf-8")

        patch_req = urllib.request.Request(api_url, data=payload, method="PATCH")
        patch_req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(patch_req, timeout=2) as resp:
            if resp.status in (200, 204):
                print(f"[SUCCESS] Added '{target}' to SakuraCat TUN route-exclude-address (via {api_url}).")
                return True
            else:
                if verbose:
                    print(f"[WARN] Patch returned status {resp.status}")
                return False
    except Exception as e:
        if verbose:
            print(f"[ERROR] {e}")
        return False

if __name__ == "__main__":
    success = check_and_patch(verbose=True)
    sys.exit(0 if success else 1)
