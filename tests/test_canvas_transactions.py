"""Audit E09: touch / delete / restore / purge / project writes are single-lock transactions."""
import os
import sys
import threading
import unittest

from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app  # noqa: E402
import routers.canvas as canvas_module  # noqa: E402


class TestCanvasTransactions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _create(self):
        r = self.client.post("/api/canvases", json={"title": "txn", "kind": "classic"})
        self.assertEqual(r.status_code, 200)
        return r.json()["canvas"]["id"]

    def test_purge_never_resurrected_by_concurrent_touch(self):
        for _ in range(15):
            cid = self._create()
            barrier = threading.Barrier(2)

            def touch():
                barrier.wait()
                for _ in range(5):
                    try:
                        canvas_module.api_touch_canvas(cid)
                    except Exception:
                        pass

            def purge():
                barrier.wait()
                canvas_module.api_purge_canvas(cid)

            ts = [threading.Thread(target=touch), threading.Thread(target=purge)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.assertFalse(os.path.exists(canvas_module.canvas_path(cid)),
                             "purged canvas file reappeared after a concurrent touch")

    def test_concurrent_project_creation_loses_nothing(self):
        created = []
        lock = threading.Lock()

        def make(i):
            p = canvas_module.api_create_project(canvas_module.ProjectCreateRequest(name=f"txn-proj-{i}"))
            with lock:
                created.append(p["project"]["id"])

        ts = [threading.Thread(target=make, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        try:
            ids = {p["id"] for p in canvas_module.load_projects()}
            missing = [c for c in created if c not in ids]
            self.assertEqual(missing, [], "concurrent project creation overwrote sibling projects")
        finally:
            for pid in created:
                canvas_module.api_delete_project(pid)

    def test_delete_restore_roundtrip(self):
        cid = self._create()
        try:
            self.assertEqual(self.client.delete(f"/api/canvases/{cid}").status_code, 200)
            self.assertEqual(self.client.post(f"/api/canvases/{cid}/restore").status_code, 200)
            self.assertEqual(self.client.post(f"/api/canvases/{cid}/touch").status_code, 200)
        finally:
            self.client.delete(f"/api/canvases/{cid}/purge")


if __name__ == "__main__":
    unittest.main()
