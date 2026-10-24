import os
import sys
import unittest
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
import routers.canvas as canvas_module

class TestCanvasRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_list_projects(self):
        resp = self.client.get("/api/projects")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("projects", data)
        self.assertTrue(isinstance(data["projects"], list))
        project_ids = [p["id"] for p in data["projects"]]
        self.assertIn("default", project_ids)

    def test_02_project_lifecycle(self):
        create_resp = self.client.post("/api/projects", json={"name": "Router Test Project"})
        self.assertEqual(create_resp.status_code, 200)
        proj = create_resp.json().get("project")
        self.assertIsNotNone(proj)
        proj_id = proj["id"]
        self.assertEqual(proj["name"], "Router Test Project")

        update_resp = self.client.post(f"/api/projects/{proj_id}", json={"name": "Renamed Project", "order": 99})
        self.assertEqual(update_resp.status_code, 200)
        updated_proj = update_resp.json().get("project")
        self.assertEqual(updated_proj["name"], "Renamed Project")
        self.assertEqual(updated_proj["order"], 99)

        del_resp = self.client.delete(f"/api/projects/{proj_id}")
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json().get("ok"))

        del_default = self.client.delete("/api/projects/default")
        self.assertEqual(del_default.status_code, 400)

    def test_03_canvas_full_lifecycle(self):
        create_resp = self.client.post("/api/canvases", json={
            "title": "Decoupling Unit Test Canvas",
            "icon": "palette",
            "kind": "classic",
        })
        self.assertEqual(create_resp.status_code, 200)
        canvas = create_resp.json().get("canvas")
        self.assertIsNotNone(canvas)
        canvas_id = canvas["id"]
        self.assertEqual(canvas["title"], "Decoupling Unit Test Canvas")
        self.assertEqual(canvas["icon"], "palette")

        try:
            list_resp = self.client.get("/api/canvases")
            self.assertEqual(list_resp.status_code, 200)
            ids = [c["id"] for c in list_resp.json().get("canvases", [])]
            self.assertIn(canvas_id, ids)

            get_resp = self.client.get(f"/api/canvases/{canvas_id}")
            self.assertEqual(get_resp.status_code, 200)
            self.assertEqual(get_resp.json()["canvas"]["id"], canvas_id)

            meta_resp = self.client.get(f"/api/canvases/{canvas_id}/meta")
            self.assertEqual(meta_resp.status_code, 200)
            self.assertEqual(meta_resp.json()["id"], canvas_id)

            meta_update_resp = self.client.post(f"/api/canvases/{canvas_id}/meta", json={
                "title": "Decoupled Canvas Renamed",
                "color": "teal",
                "pinned": True
            })
            self.assertEqual(meta_update_resp.status_code, 200)
            rec = meta_update_resp.json().get("canvas")
            self.assertEqual(rec["title"], "Decoupled Canvas Renamed")
            self.assertEqual(rec["color"], "teal")
            self.assertTrue(rec["pinned"])

            touch_resp = self.client.post(f"/api/canvases/{canvas_id}/touch")
            self.assertEqual(touch_resp.status_code, 200)
            self.assertIn("updated_at", touch_resp.json())

            put_resp = self.client.put(f"/api/canvases/{canvas_id}", json={
                "title": "Decoupled Canvas Renamed",
                "nodes": [{"id": "node-1", "type": "text", "x": 100, "y": 200}],
                "connections": [],
                "viewport": {"x": 0, "y": 0, "scale": 1},
                "logs": [],
                "settings": {"grid": True},
            })
            self.assertEqual(put_resp.status_code, 200)
            updated_canvas = put_resp.json().get("canvas")
            self.assertEqual(len(updated_canvas["nodes"]), 1)

            conflict_resp = self.client.put(f"/api/canvases/{canvas_id}", json={
                "title": "Conflict Test",
                "base_updated_at": 1000,
                "nodes": [],
                "connections": [],
            })
            self.assertEqual(conflict_resp.status_code, 409)

            del_resp = self.client.delete(f"/api/canvases/{canvas_id}")
            self.assertEqual(del_resp.status_code, 200)
            self.assertTrue(del_resp.json().get("ok"))

            active_ids = [c["id"] for c in self.client.get("/api/canvases").json().get("canvases", [])]
            self.assertNotIn(canvas_id, active_ids)

            trash_resp = self.client.get("/api/canvases/trash")
            self.assertEqual(trash_resp.status_code, 200)
            trashed_ids = [c["id"] for c in trash_resp.json().get("canvases", [])]
            self.assertIn(canvas_id, trashed_ids)

            restore_resp = self.client.post(f"/api/canvases/{canvas_id}/restore")
            self.assertEqual(restore_resp.status_code, 200)
            self.assertIsNone(restore_resp.json()["canvas"].get("deleted_at"))

            active_ids = [c["id"] for c in self.client.get("/api/canvases").json().get("canvases", [])]
            self.assertIn(canvas_id, active_ids)

        finally:
            purge_resp = self.client.delete(f"/api/canvases/{canvas_id}/purge")
            self.assertEqual(purge_resp.status_code, 200)
            self.assertTrue(purge_resp.json().get("ok"))
            path = canvas_module.canvas_path(canvas_id)
            self.assertFalse(os.path.exists(path))

    def test_04_canvas_resource_budget_limits(self):
        create_resp = self.client.post("/api/canvases", json={"title": "Budget Test"})
        self.assertEqual(create_resp.status_code, 200)
        canvas_id = create_resp.json()["canvas"]["id"]

        try:
            # 1. Reject > 2000 nodes
            excess_nodes = [{"id": f"n_{i}", "type": "image"} for i in range(2001)]
            resp = self.client.put(f"/api/canvases/{canvas_id}", json={
                "title": "Too Many Nodes",
                "nodes": excess_nodes,
                "connections": []
            })
            self.assertEqual(resp.status_code, 422)
            self.assertIn("2000", str(resp.json().get("detail", "")))

            # 2. Reject > 5000 connections
            excess_conns = [{"id": f"c_{i}", "from": "n1", "to": "n2"} for i in range(5001)]
            resp = self.client.put(f"/api/canvases/{canvas_id}", json={
                "title": "Too Many Conns",
                "nodes": [],
                "connections": excess_conns
            })
            self.assertEqual(resp.status_code, 422)
            self.assertIn("5000", str(resp.json().get("detail", "")))

            # 3. Reject oversized inline Base64 (>15MB)
            huge_base64 = "data:image/png;base64," + "A" * (16 * 1024 * 1024)
            resp = self.client.put(f"/api/canvases/{canvas_id}", json={
                "title": "Oversized Base64",
                "nodes": [{"id": "huge_node", "name": "超大图片", "type": "image", "url": huge_base64}],
                "connections": []
            })
            self.assertEqual(resp.status_code, 422)
            detail = str(resp.json().get("detail", ""))
            self.assertIn("Base64", detail)
            self.assertIn("15MB", detail)

        finally:
            self.client.delete(f"/api/canvases/{canvas_id}/purge")


if __name__ == "__main__":
    unittest.main()
