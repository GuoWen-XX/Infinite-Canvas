# -*- coding: utf-8 -*-
"""
MeansCanvas (开卷画布) Rhino 3D Viewport Direct-Push Bridge
=====================================================
Captures the active Rhino viewport and pushes it directly into MeansCanvas (开卷画布).

Compatible with:
  Rhino 6 (Windows)
  Rhino 7 (Windows / Mac)
  Rhino 8 (Windows / Mac, IronPython 2.7 & CPython 3)

Usage in Rhino:
  1. In Rhino command line, run:
     -_RunPythonScript "C:/path/to/Infinite-Canvas/tools/rhino/infinite_canvas_rhino.py"
  2. Or assign it to a toolbar button or alias (e.g. MCPush / ICPush).
"""

import sys
import os
import json
import time

# MeansCanvas API endpoint (default port is 3333)
DEFAULT_ENDPOINT = os.getenv("MEANS_CANVAS_ENDPOINT") or os.getenv("INFINITE_CANVAS_ENDPOINT", "http://127.0.0.1:3333/api/canvas/rhino-capture")

def capture_rhino_viewport():
    try:
        import Rhino
        import System
        import System.Drawing
        import System.Drawing.Imaging
        import System.IO
    except ImportError:
        print("[Infinite-Canvas] Error: This script must be executed inside Rhino 3D.")
        return None

    doc = Rhino.RhinoDoc.ActiveDoc
    if not doc:
        print("[Infinite-Canvas] Error: No active document found.")
        return None

    view = doc.Views.ActiveView
    if not view:
        print("[Infinite-Canvas] Error: No active viewport found.")
        return None

    vp = view.ActiveViewport
    view_name = vp.Name

    # Capture viewport to bitmap
    try:
        capture = Rhino.Display.ViewCapture()
        capture.Width = vp.Size.Width
        capture.Height = vp.Size.Height
        capture.ScaleScreenItems = False
        capture.DrawGrid = True
        capture.DrawAxes = True
        capture.TransparentBackground = False
        bitmap = capture.CaptureToBitmap(view)
    except Exception:
        bitmap = view.CaptureToBitmap()

    if not bitmap:
        print("[Infinite-Canvas] Error: Failed to capture viewport bitmap.")
        return None

    # Encode bitmap to PNG Base64
    ms = System.IO.MemoryStream()
    bitmap.Save(ms, System.Drawing.Imaging.ImageFormat.Png)
    png_bytes = ms.ToArray()
    b64_string = System.Convert.ToBase64String(png_bytes)
    ms.Dispose()
    bitmap.Dispose()

    # Camera metadata
    camera_info = {
        "location": [round(vp.CameraLocation.X, 3), round(vp.CameraLocation.Y, 3), round(vp.CameraLocation.Z, 3)],
        "target": [round(vp.CameraTarget.X, 3), round(vp.CameraTarget.Y, 3), round(vp.CameraTarget.Z, 3)],
        "lens_35mm": round(vp.Camera35mmLensLength, 1) if hasattr(vp, "Camera35mmLensLength") else 50.0,
        "is_perspective": vp.IsPerspectiveProjection,
    }

    payload = {
        "image_base64": "data:image/png;base64," + b64_string,
        "view_name": view_name,
        "camera": camera_info,
        "timestamp": int(time.time() * 1000)
    }

    return payload

def send_to_infinite_canvas(payload, endpoint=DEFAULT_ENDPOINT):
    payload_json = json.dumps(payload)

    # Strategy 1: Try .NET WebClient (standard in Rhino IronPython)
    try:
        import System.Net
        client = System.Net.WebClient()
        client.Headers[System.Net.HttpRequestHeader.ContentType] = "application/json; charset=utf-8"
        response = client.UploadString(endpoint, "POST", payload_json)
        client.Dispose()
        return True, response
    except Exception as e_net:
        pass

    # Strategy 2: Python standard library (CPython in Rhino 8)
    try:
        try:
            import urllib.request as urllib_req
        except ImportError:
            import urllib2 as urllib_req

        req = urllib_req.Request(
            endpoint,
            data=payload_json.encode("utf-8") if sys.version_info[0] >= 3 else payload_json,
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        resp = urllib_req.urlopen(req, timeout=10)
        res_data = resp.read()
        return True, res_data
    except Exception as e_py:
        return False, str(e_py)

def main():
    print("[MeansCanvas] Capturing active viewport...")
    payload = capture_rhino_viewport()
    if not payload:
        return

    print("[MeansCanvas] Viewport [{0}] captured ({1} bytes). Sending to MeansCanvas...".format(
        payload["view_name"], len(payload["image_base64"])
    ))

    success, info = send_to_infinite_canvas(payload)
    if success:
        print("[MeansCanvas] SUCCESS: Viewport [{0}] inserted into MeansCanvas!".format(payload["view_name"]))
    else:
        print("[MeansCanvas] WARNING: Could not connect to MeansCanvas at {0}.".format(DEFAULT_ENDPOINT))
        print("[MeansCanvas] Detail: {0}".format(info))
        print("[MeansCanvas] Please ensure MeansCanvas is running on http://127.0.0.1:3333")

if __name__ == "__main__":
    main()
