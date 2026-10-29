import unittest
import os
import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

class TestRuntimeIssuesFix(unittest.TestCase):
    def test_gemini_cli_lock_exists(self):
        """Issue 1: Ensure Antigravity CLI lock was removed per design for concurrency."""
        import routers.integrations as integrations
        self.assertFalse(hasattr(integrations, '_GEMINI_CLI_LOCK'))

    def test_gemini_cli_disk_fallback_on_error(self):
        """Issue 1: If CLI throws an error but the file was created on disk, succeed anyway."""
        import routers.integrations as integrations
        from fastapi import HTTPException

        async def run_test():
            target_path = os.path.join(integrations.OUTPUT_OUTPUT_DIR, "test_agy_fallback.png")
            try:
                # Create dummy target file
                with open(target_path, "wb") as f:
                    f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")

                with patch.object(integrations, "run_gemini_cli", side_effect=HTTPException(status_code=502, detail="EOF error")):
                    with patch("uuid.uuid4") as mock_uuid:
                        mock_uuid.return_value.hex = "fallback0000"
                        # Mock the target_path construction to match our dummy file
                        with patch("os.path.join", return_value=target_path):
                            res, info = await integrations.generate_gemini_cli_provider_image(
                                prompt="test", size="1024x1024", model="auto"
                            )
                            self.assertEqual(res["type"], "url")
                            self.assertIn("test_agy_fallback.png", res["value"])
            finally:
                if os.path.isfile(target_path):
                    try:
                        os.remove(target_path)
                    except Exception:
                        pass

        asyncio.run(run_test())

    def test_i18n_adaptive_ratio(self):
        """Issue 2: Verify i18n translation is updated to '适配原图'."""
        i18n_path = os.path.join("static", "js", "i18n", "canvas.js")
        with open(i18n_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('"canvas.adaptiveRatio": { zh: "适配原图", en: "Match Source" }', content)

    def test_canvas_js_default_ratio_is_source(self):
        """Issue 2: Check canvas.js and smart-canvas.js default ratio is 'source'."""
        canvas_js_path = os.path.join("static", "js", "canvas.js")
        with open(canvas_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("ratio:'source'", content)
        self.assertIn("if(!node.ratio) node.ratio = 'source';", content)

        smart_js_path = os.path.join("static", "js", "smart-canvas.js")
        with open(smart_js_path, "r", encoding="utf-8") as f:
            smart_content = f.read()
        self.assertIn("ratio:'source'", smart_content)

    def test_canvas_js_grouping_supports_output(self):
        """Issue 3: Check grouping and reference extraction support output nodes."""
        canvas_js_path = os.path.join("static", "js", "canvas.js")
        with open(canvas_js_path, "r", encoding="utf-8") as f:
            content = f.read()
        # groupSelectedImages includes output
        self.assertIn("n.type === 'output'", content)
        # port out on frame_group
        self.assertIn('<div class="port out" title="${tr(\'canvas.dragConnect\')}"></div>', content)
        # link-group action in selectionHub
        self.assertIn('data-action="link-group"', content)
        self.assertIn('startSelectionLink(e, \'images\')', content)

    def test_smart_canvas_viewport_and_fit_button(self):
        """Issue 4: Check smart-canvas viewport auto-fit and button exist."""
        html_path = os.path.join("static", "smart-canvas.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="smartFitBtn"', html)
        self.assertIn('fitAllNodesViewport()', html)

        smart_js_path = os.path.join("static", "js", "smart-canvas.js")
        with open(smart_js_path, "r", encoding="utf-8") as f:
            js = f.read()
        self.assertIn('hasVisibleNode', js)
        self.assertIn('fitAllNodesViewport()', js)

        # 视口往返：自建临时画布，不依赖作者本机 data/ 下的固定 UUID 文件
        from starlette.testclient import TestClient
        from main import app
        client = TestClient(app)
        created = client.post("/api/canvases", json={"title": "viewport-roundtrip", "kind": "classic"})
        self.assertEqual(created.status_code, 200)
        canvas_id = created.json()["canvas"]["id"]
        try:
            saved = client.put(f"/api/canvases/{canvas_id}", json={
                "title": "viewport-roundtrip",
                "nodes": [], "connections": [],
                "viewport": {"x": 10, "y": 20, "scale": 0.75},
            })
            self.assertEqual(saved.status_code, 200)
            data = client.get(f"/api/canvases/{canvas_id}").json()["canvas"]
            self.assertIn("viewport", data)
            self.assertGreater(data["viewport"].get("scale", 0), 0)
        finally:
            client.delete(f"/api/canvases/{canvas_id}")
            client.delete(f"/api/canvases/{canvas_id}/purge")

if __name__ == "__main__":
    unittest.main()
